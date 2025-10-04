import os
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
import logging
from logging.handlers import RotatingFileHandler


class AppConfig(BaseModel):
    telegram_token: Optional[str] = Field(default=None, alias="TELEGRAM_TOKEN")
    bybit_api_key: Optional[str] = Field(default=None, alias="BYBIT_API_KEY")
    bybit_api_secret: Optional[str] = Field(default=None, alias="BYBIT_API_SECRET")
    base_currency: str = Field(default="USDC", alias="BASE_CURRENCY")
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    admin_user_id: Optional[int] = Field(default=None, alias="ADMIN_USER_ID")
    
    # Comma separated, e.g. "10,20,50"
    buy_amounts: List[float] = Field(default_factory=lambda: [10.0, 20.0], alias="BUY_AMOUNTS")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: str = Field(default="logs", alias="LOG_DIR")

    @field_validator("buy_amounts", mode="before")
    @classmethod
    def parse_buy_amounts(cls, v):
        if v is None or v == "":
            return [10.0, 20.0]
        if isinstance(v, list):
            return [float(x) for x in v]
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return [float(p) for p in parts]
        return v


_CONFIG: Optional[AppConfig] = None
_LOGGER: Optional[logging.Logger] = None


def load_config() -> AppConfig:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    load_dotenv(override=False)
    env = {k: os.getenv(k) for k in [
        "TELEGRAM_TOKEN",
        "BYBIT_API_KEY",
        "BYBIT_API_SECRET",
        "BASE_CURRENCY",
        "DRY_RUN",
        "ADMIN_USER_ID",
        "BUY_AMOUNTS",
        "LOG_LEVEL",
        "LOG_DIR",
    ]}
    # pydantic accepts aliases via model_validate
    _CONFIG = AppConfig.model_validate(env)
    return _CONFIG


def get_logger(name: str = "app") -> logging.Logger:
    global _LOGGER
    cfg = load_config()
    level = getattr(logging, str(cfg.log_level).upper(), logging.INFO)

    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    os.makedirs(cfg.log_dir, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        os.path.join(cfg.log_dir, "app.log"), maxBytes=2 * 1024 * 1024, backupCount=3
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # Clear existing handlers to avoid duplicates if reloaded
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _LOGGER = logger
    return logger


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 6:
        return "******"
    return value[:3] + "***" + value[-3:]

