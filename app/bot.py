from __future__ import annotations

import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
)

from .config import load_config, get_logger
from .exchange import BybitClient
from .coingecko import CoinGeckoClient
from ccxt.base.errors import InsufficientFunds, InvalidOrder, NetworkError, DDoSProtection  # type: ignore


logger = get_logger("app.bot")


class BotApp:
    def __init__(self):
        self.cfg = load_config()
        self.bybit = BybitClient()
        self.cg = CoinGeckoClient()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Welcome! Use /buy <TICKER> to purchase.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Commands: /buy <TICKER>, /balance, /pairs <TICKER>, /dryrun on|off")

    async def balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        balances = await self.bybit.get_balances()
        await update.message.reply_text(
            f"USDC: {balances.get('USDC', 0):.2f}\nUSDT: {balances.get('USDT', 0):.2f}"
        )

    async def price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /price <TICKER>")
            return
        ticker = context.args[0].upper()
        usdc, usdt = await self.bybit.find_market_for_ticker(ticker)
        market = usdc or usdt
        if not market or not market.market:
            await update.message.reply_text("Market not found on Bybit")
            return
        try:
            t = await self.bybit.exchange.fetch_ticker(market.symbol)
            price = float(t.get("last") or t.get("close") or 0)
        except Exception:
            price = 0.0
        await update.message.reply_text(f"{market.symbol} ~ {price:.8f}")

    async def pairs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /pairs <TICKER>")
            return
        ticker = context.args[0].upper()
        usdc, usdt = await self.bybit.find_market_for_ticker(ticker)
        parts = []
        if usdc and usdc.market:
            parts.append(f"{usdc.symbol}")
        if usdt and usdt.market:
            parts.append(f"{usdt.symbol}")
        if not parts:
            parts.append("No spot pairs found on Bybit")
        await update.message.reply_text("Available: " + ", ".join(parts))

    async def dryrun(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.cfg.admin_user_id or update.effective_user.id != self.cfg.admin_user_id:
            await update.message.reply_text("Admin only")
            return
        state = (context.args[0].lower() == "on") if context.args else None
        if state is None:
            await update.message.reply_text(f"DRY_RUN is {'ON' if self.cfg.dry_run else 'OFF'}")
            return
        self.cfg.dry_run = bool(state)
        await update.message.reply_text(f"DRY_RUN set to {'ON' if self.cfg.dry_run else 'OFF'}")

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /buy <TICKER>")
            return
        ticker = context.args[0].upper()
        coin = await self.cg.resolve_symbol(ticker)
        usdc, usdt = await self.bybit.find_market_for_ticker(ticker)
        market = usdc or usdt
        if not market or not market.market:
            await update.message.reply_text("Market not found on Bybit")
            return
        price = 0.0
        try:
            t = await self.bybit.exchange.fetch_ticker(market.symbol)
            price = float(t.get("last") or t.get("close") or 0)
        except Exception:
            pass
        name = coin.name if coin else ticker
        img = coin.image_url if coin else None
        text = f"Confirm purchase of {name} ({ticker}/{market.quote}) at ~{price:.8f}?"
        buttons = []
        row = []
        for amt in self.cfg.buy_amounts:
            row.append(InlineKeyboardButton(
                f"Buy {amt:.0f} {self.cfg.base_currency}", callback_data=f"BUY|{ticker}|{amt}"
            ))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("Cancel", callback_data="CANCEL")])
        await update.message.reply_photo(
            photo=img or "https://via.placeholder.com/64",
            caption=text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        if data == "CANCEL":
            await query.edit_message_caption(caption="Cancelled")
            return
        if data.startswith("BUY|"):
            _, ticker, amt_s = data.split("|")
            intended_usdc = float(amt_s)
            try:
                selection, convert = await self.bybit.prepare_buy(ticker, intended_usdc)
                # Convert the intended USDC spend into the selection's quote currency amount
                quote_amount = await self.bybit.quote_amount_for_selection(selection, intended_usdc)
                if convert and not self.cfg.dry_run:
                    await self.bybit.convert_usdc_to_usdt(convert["convert_needed_usdt"])  # best-effort
                order = await self.bybit.place_buy(selection, quote_amount, self.cfg.dry_run)
                if order.get("dry_run"):
                    msg = (
                        f"DRY-RUN: Would buy {selection.base}/{selection.quote} spending {quote_amount:.2f} {selection.quote} "
                        f"at ~{order.get('last_price', 0):.8f}"
                    )
                else:
                    msg = f"Bought {selection.base}/{selection.quote}."
                await query.edit_message_caption(caption=msg)
            except InsufficientFunds:
                await query.edit_message_caption(caption="Insufficient funds. Consider lowering amount or convert USDC→USDT.")
            except InvalidOrder as e:
                await query.edit_message_caption(caption=f"Order rejected: {e}")
            except (NetworkError, DDoSProtection):
                await query.edit_message_caption(caption="Network issue or rate-limit. Please try again shortly.")
            except Exception as e:
                await query.edit_message_caption(caption=f"Error: {e}")

    def build_application(self) -> Application:
        token = self.cfg.telegram_token or ""
        app = ApplicationBuilder().token(token).concurrent_updates(True).build()
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help))
        app.add_handler(CommandHandler("balance", self.balance))
        app.add_handler(CommandHandler("pairs", self.pairs))
        app.add_handler(CommandHandler("dryrun", self.dryrun))
        app.add_handler(CommandHandler("buy", self.buy))
        app.add_handler(CommandHandler("price", self.price))
        app.add_handler(CallbackQueryHandler(self.on_button))
        return app

