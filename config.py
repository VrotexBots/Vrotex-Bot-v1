import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")


def env_list(name: str, default: str) -> list:
    return [
        item.strip().upper()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    ]


@dataclass(frozen=True)
class Settings:

    # Bot identity
    BOT_NAME: str = "Vrotex Bot V1"

    # Environment
    BOT_MODE: str = os.getenv("BOT_MODE", "DEMO").upper()
    ORDER_EXECUTION_ENABLED: bool = env_bool(
        "ORDER_EXECUTION_ENABLED", False
    )

    # Exness credentials
    EXN_API_KEY: str = os.getenv("EXN_API_KEY", "")
    EXN_PRIVATE_KEY: str = os.getenv("EXN_PRIVATE_KEY", "")
    EXN_ACCOUNT_ID: str = os.getenv("EXN_ACCOUNT_ID", "")
    EXN_GATEWAY_HOST: str = os.getenv("EXN_GATEWAY_HOST", "")

    # Approved instruments
    INSTRUMENTS: list = tuple(env_list(
        "INSTRUMENTS",
        "EURUSD,GBPUSD,USDJPY,EURJPY,EURGBP,BTCUSD"
    ))

    # Strategy timeframes
    ANALYSIS_TIMEFRAMES: tuple = ("H1", "M5", "M1")

    # Market data timeframes
    DATA_TIMEFRAMES: tuple = (
        "D1", "H4", "H1", "M30", "M15", "M5", "M1"
    )

    # Setup score
    MIN_SETUP_SCORE: int = int(
        os.getenv("MIN_SETUP_SCORE", "85")
    )

    # Risk controls
    RISK_PERCENT: float = float(
        os.getenv("RISK_PERCENT", "1.0")
    )

    MAX_DAILY_TRADES: int = int(
        os.getenv("MAX_DAILY_TRADES", "5")
    )

    MAX_CONSECUTIVE_LOSSES: int = int(
        os.getenv("MAX_CONSECUTIVE_LOSSES", "2")
    )

    MAX_DAILY_LOSS_PERCENT: float = float(
        os.getenv("MAX_DAILY_LOSS_PERCENT", "2.0")
    )

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()


def validate_settings():

    if settings.BOT_MODE not in ("DEMO", "REAL"):
        raise ValueError("BOT_MODE must be DEMO or REAL")

    if settings.RISK_PERCENT <= 0 or settings.RISK_PERCENT > 1:
        raise ValueError("Risk must be between 0 and 1 percent")

    if settings.MIN_SETUP_SCORE < 85:
        raise ValueError("Minimum setup score cannot be below 85")

    if settings.MAX_DAILY_TRADES < 1:
        raise ValueError("MAX_DAILY_TRADES must be at least 1")

    if settings.MAX_CONSECUTIVE_LOSSES < 1:
        raise ValueError("MAX_CONSECUTIVE_LOSSES must be at least 1")

    if settings.MAX_DAILY_LOSS_PERCENT <= 0:
        raise ValueError("Daily loss limit must be greater than zero")

    if settings.BOT_MODE == "REAL" and not settings.ORDER_EXECUTION_ENABLED:
        print("REAL mode selected but order execution is disabled.")

    if settings.BOT_MODE == "REAL" and settings.ORDER_EXECUTION_ENABLED:
        raise RuntimeError(
            "Real-money execution is locked pending explicit approval."
        )

    if settings.ORDER_EXECUTION_ENABLED and settings.BOT_MODE != "DEMO":
        raise RuntimeError(
            "Order execution is only permitted in DEMO mode."
        )

    print("Vrotex Bot V1 configuration validated.")
    print(f"Mode: {settings.BOT_MODE}")
    print(f"Execution enabled: {settings.ORDER_EXECUTION_ENABLED}")
    print(f"Instruments: {', '.join(settings.INSTRUMENTS)}")
    print(f"Minimum score: {settings.MIN_SETUP_SCORE}")


if __name__ == "__main__":
    validate_settings()
