from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx


COINGECKO_API = "https://api.coingecko.com/api/v3"


@dataclass
class CoinInfo:
    id: str
    symbol: str
    name: str
    image_url: Optional[str]


class CoinGeckoClient:
    def __init__(self):
        self._symbol_map: Dict[str, List[CoinInfo]] = {}

    async def _fetch(self, client: httpx.AsyncClient, url: str, params: Optional[Dict] = None) -> Optional[dict]:
        try:
            resp = await client.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            return None
        return None

    async def ensure_symbol_index(self) -> None:
        if self._symbol_map:
            return
        async with httpx.AsyncClient() as client:
            data = await self._fetch(client, f"{COINGECKO_API}/coins/list")
        if not isinstance(data, list):
            return
        index: Dict[str, List[CoinInfo]] = {}
        for item in data:
            coin_id = item.get("id")
            symbol = (item.get("symbol") or "").upper()
            name = item.get("name") or symbol
            if not coin_id or not symbol:
                continue
            index.setdefault(symbol, []).append(CoinInfo(id=coin_id, symbol=symbol, name=name, image_url=None))
        self._symbol_map = index

    async def resolve_symbol(self, symbol: str) -> Optional[CoinInfo]:
        await self.ensure_symbol_index()
        candidates = self._symbol_map.get(symbol.upper()) or []
        if not candidates:
            return None
        # Pick the first by default; could enhance by market presence later
        coin = candidates[0]
        # Fetch market data for image
        async with httpx.AsyncClient() as client:
            data = await self._fetch(client, f"{COINGECKO_API}/coins/{coin.id}", params={"localization": "false"})
        image_url = None
        if isinstance(data, dict):
            image = data.get("image") or {}
            image_url = image.get("small") or image.get("thumb") or image.get("large")
            name = data.get("name") or coin.name
        else:
            name = coin.name
        return CoinInfo(id=coin.id, symbol=coin.symbol, name=name, image_url=image_url)

