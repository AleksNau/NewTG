from __future__ import annotations

from typing import Any, Dict, Optional


def format_money(amount: float, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def human_coin(symbol: str) -> str:
    return symbol.upper()


def clamp_amount_to_limits(
    exchange, market: Dict[str, Any], amount: float
) -> float:
    # Respect market limits if provided
    limits = market.get("limits") or {}
    amount_limits = limits.get("amount") or {}
    min_amount = amount_limits.get("min")
    max_amount = amount_limits.get("max")
    if min_amount is not None:
        amount = max(amount, float(min_amount))
    if max_amount is not None:
        amount = min(amount, float(max_amount))
    return float(exchange.amount_to_precision(market["symbol"], amount))


def clamp_cost_to_limits(market: Dict[str, Any], cost: float) -> float:
    limits = market.get("limits") or {}
    cost_limits = limits.get("cost") or {}
    min_cost = cost_limits.get("min")
    max_cost = cost_limits.get("max")
    if min_cost is not None:
        cost = max(cost, float(min_cost))
    if max_cost is not None:
        cost = min(cost, float(max_cost))
    return cost


def extract_ticker_symbol(query: str) -> Optional[str]:
    if not query:
        return None
    q = query.strip().upper()
    # Remove common prefixes like "/buy" processed earlier; just sanitize
    return "".join(ch for ch in q if ch.isalnum())

