from __future__ import annotations

from .config import load_config, get_logger
from .bot import BotApp


def main():
    cfg = load_config()
    logger = get_logger("app.main")
    if not cfg.telegram_token:
        logger.error("TELEGRAM_TOKEN missing. Fill .env first.")
    application = BotApp().build_application()
    logger.info("Starting Telegram bot ...")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()

