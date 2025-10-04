from __future__ import annotations

import asyncio
from typing import Optional

from .config import load_config, get_logger, mask_secret
from .exchange import BybitClient


async def run_selfcheck():
    logger = get_logger("app.selfcheck")
    cfg = load_config()

    logger.info("Config loaded. DRY_RUN=%s BASE_CURRENCY=%s", cfg.dry_run, cfg.base_currency)
    logger.info("TELEGRAM_TOKEN=%s", mask_secret(cfg.telegram_token))
    logger.info("BYBIT_API_KEY=%s", mask_secret(cfg.bybit_api_key))
    logger.info("ADMIN_USER_ID=%s", str(cfg.admin_user_id) if cfg.admin_user_id else "<none>")

    client = BybitClient()
    try:
        markets = await client.load_markets()
        supports_quote = await client.supports_quote_order_qty()
        logger.info("Loaded %d markets. quoteOrderQty supported: %s", len(markets), supports_quote)

        balances = await client.get_balances()
        logger.info("Balances: USDC=%.4f, USDT=%.4f", balances.get("USDC", 0.0), balances.get("USDT", 0.0))

        # Simulate PEPE flow
        try:
            selection, convert = await client.prepare_buy("PEPE", 10.0)
            if convert:
                logger.info("Would convert USDC->USDT for approx %.4f USDT", convert["convert_needed_usdt"])
            logger.info("Would buy on %s spending 10 USDC-equivalent (quote=%s)", selection.symbol, selection.quote)
        except Exception as e:
            logger.warning("Prepare PEPE buy failed: %s", str(e))
    finally:
        await client.close()


def main():
    asyncio.run(run_selfcheck())


if __name__ == "__main__":
    main()

