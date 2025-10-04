from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import ccxt.async_support as ccxt  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import load_config, get_logger
from .utils import clamp_amount_to_limits, clamp_cost_to_limits


logger = get_logger("app.exchange")


@dataclass
class MarketSelection:
    symbol: str
    quote: str
    base: str
    market: Dict


class BybitClient:
    def __init__(self):
        cfg = load_config()
        self.cfg = cfg
        self.exchange = ccxt.bybit({
            "apiKey": cfg.bybit_api_key or "",
            "secret": cfg.bybit_api_secret or "",
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
            },
        })
        self._markets: Optional[Dict[str, Dict]] = None
        self._usdt_per_usdc_cache: Optional[float] = None

    async def close(self):
        try:
            await self.exchange.close()
        except Exception:
            pass

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def load_markets(self) -> Dict[str, Dict]:
        if self._markets is None:
            logger.info("Loading markets from Bybit ...")
            self._markets = await self.exchange.load_markets()
        return self._markets

    async def get_balances(self) -> Dict[str, float]:
        balances: Dict[str, float] = {"USDC": 0.0, "USDT": 0.0}
        try:
            await self.load_markets()
            bal = await self.exchange.fetch_balance()
            total = bal.get("total") or {}
            for k in ["USDC", "USDT"]:
                v = total.get(k) or 0
                try:
                    balances[k] = float(v)
                except Exception:
                    balances[k] = 0.0
        except Exception as e:
            logger.warning("Failed to fetch balances: %s", str(e))
        return balances

    async def get_usdt_per_usdc(self) -> float:
        if self._usdt_per_usdc_cache is not None:
            return self._usdt_per_usdc_cache
        markets = await self.load_markets()
        price = 1.0
        if markets.get("USDT/USDC"):
            try:
                t = await self.exchange.fetch_ticker("USDT/USDC")
                price = float(t.get("last") or t.get("close") or 1.0)
            except Exception:
                price = 1.0
        elif markets.get("USDC/USDT"):
            try:
                t = await self.exchange.fetch_ticker("USDC/USDT")
                v = float(t.get("last") or t.get("close") or 1.0)
                price = 1.0 / v if v else 1.0
            except Exception:
                price = 1.0
        self._usdt_per_usdc_cache = price
        return price

    async def quote_amount_for_selection(self, selection: MarketSelection, intended_usdc_quote: float) -> float:
        # Convert intended USDC-amount to the actual quote currency amount for the selected market
        if selection.quote == "USDC":
            return intended_usdc_quote
        if selection.quote == "USDT":
            rate = await self.get_usdt_per_usdc()
            return intended_usdc_quote * rate
        # Fallback: assume 1:1 for other quotes (unlikely for this bot)
        return intended_usdc_quote

    async def find_market_for_ticker(self, ticker: str) -> Tuple[Optional[MarketSelection], Optional[MarketSelection]]:
        ticker_u = ticker.upper()
        markets = await self.load_markets()
        usdc_symbol = f"{ticker_u}/USDC"
        usdt_symbol = f"{ticker_u}/USDT"
        usdc = markets.get(usdc_symbol)
        usdt = markets.get(usdt_symbol)
        usdc_sel = MarketSelection(symbol=usdc_symbol, quote="USDC", base=ticker_u, market=usdc) if usdc else None
        usdt_sel = MarketSelection(symbol=usdt_symbol, quote="USDT", base=ticker_u, market=usdt) if usdt else None
        return usdc_sel, usdt_sel

    async def supports_quote_order_qty(self) -> bool:
        # Bybit spot supports quoteOrderQty for market buy in many cases, but verify via exceptions
        # There's no explicit capability API, so we simulate by checking exchange.has
        has = self.exchange.has or {}
        return bool(has.get("createOrderQuote", False)) or bool(has.get("createMarketBuyOrderWithCost", False))

    async def _create_market_buy(self, symbol: str, quote_amount: float, fallback_price: Optional[float]) -> Dict:
        # Try quoteOrderQty first
        params = {"quoteOrderQty": self.exchange.cost_to_precision(symbol, quote_amount)}
        try:
            order = await self.exchange.create_order(symbol, "market", "buy", None, None, params)
            return order
        except Exception as e:
            logger.info("quoteOrderQty not accepted, falling back: %s", str(e))
        # Fallback to amount computed from price
        if fallback_price is None or fallback_price <= 0:
            ticker = await self.exchange.fetch_ticker(symbol)
            fallback_price = float(ticker.get("last") or ticker.get("close") or 0)
        if not fallback_price or fallback_price <= 0:
            raise ValueError("Cannot determine price for fallback amount calculation")
        qty = quote_amount / float(fallback_price)
        market = (await self.load_markets()).get(symbol)
        qty = clamp_amount_to_limits(self.exchange, market, qty)
        return await self.exchange.create_order(symbol, "market", "buy", qty)

    async def convert_usdc_to_usdt(self, required_usdt: float) -> Optional[Dict]:
        markets = await self.load_markets()
        rate = await self.get_usdt_per_usdc()  # USDT per 1 USDC
        pair_usdc_usdt = markets.get("USDC/USDT")
        pair_usdt_usdc = markets.get("USDT/USDC")
        if pair_usdt_usdc:
            # Buy USDT (base) on USDT/USDC with base amount = required_usdt
            amount_base_usdt = clamp_amount_to_limits(self.exchange, pair_usdt_usdc, required_usdt)
            try:
                return await self.exchange.create_order("USDT/USDC", "market", "buy", amount_base_usdt)
            except Exception as e:
                logger.warning("USDT/USDC buy failed, will try opposite pair if available: %s", str(e))
                # fall through
        if pair_usdc_usdt:
            # Sell USDC (base) on USDC/USDT to obtain required USDT
            # Compute USDC amount to sell
            price_usdt_per_usdc = 1.0 / rate if rate else 1.0
            if pair_usdc_usdt:
                try:
                    t = await self.exchange.fetch_ticker("USDC/USDT")
                    v = float(t.get("last") or t.get("close") or 0)
                    if v > 0:
                        price_usdt_per_usdc = v
                except Exception:
                    pass
            amount_base_usdc = required_usdt / price_usdt_per_usdc
            amount_base_usdc = clamp_amount_to_limits(self.exchange, pair_usdc_usdt, amount_base_usdc)
            try:
                return await self.exchange.create_order("USDC/USDT", "market", "sell", amount_base_usdc)
            except Exception as e:
                logger.error("USDC/USDT sell failed: %s", str(e))
                return None
        logger.error("No USDC/USDT or USDT/USDC market available for conversion")
        return None

    async def prepare_buy(self, ticker: str, intended_usdc_amount: float) -> Tuple[MarketSelection, Optional[Dict]]:
        # Returns: (market to buy, potential conversion info if needed)
        base = ticker.upper()
        usdc_sel, usdt_sel = await self.find_market_for_ticker(base)
        balances = await self.get_balances()
        if usdc_sel:
            return usdc_sel, None
        if usdt_sel:
            # Compute how much USDT we need to spend to match intended USDC amount
            needed_usdt = await self.quote_amount_for_selection(usdt_sel, intended_usdc_amount)
            usdt_balance = balances.get("USDT", 0.0)
            deficit = max(0.0, needed_usdt - usdt_balance)
            usdc_balance = balances.get("USDC", 0.0)
            if deficit > 0 and usdc_balance > 0:
                convert_needed = deficit * 1.005  # 0.5% buffer
                return usdt_sel, {"convert_needed_usdt": convert_needed}
            return usdt_sel, None
        raise ValueError("Market not found for ticker")

    async def place_buy(self, selection: MarketSelection, quote_amount: float, dry_run: bool) -> Dict:
        ticker = await self.exchange.fetch_ticker(selection.symbol)
        last_price = float(ticker.get("last") or ticker.get("close") or 0)
        if dry_run:
            return {
                "dry_run": True,
                "symbol": selection.symbol,
                "quote": selection.quote,
                "spent_quote": quote_amount,
                "last_price": last_price,
            }
        return await self._create_market_buy(selection.symbol, quote_amount, last_price)

