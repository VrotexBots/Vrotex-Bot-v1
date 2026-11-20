
import os
import math
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")


def env_list(name: str, default: str) -> tuple:
    return tuple(
        item.strip().upper()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    )


@dataclass(frozen=True)
class Settings:

    # ==================================================
    # BOT IDENTITY
    # ==================================================

    BOT_NAME: str = "Vrotex Bot V1"

    # ==================================================
    # OPERATING MODE
    # ==================================================

    BOT_MODE: str = os.getenv(
        "BOT_MODE", "DEMO"
    ).strip().upper()

    # Automatic execution enabled in DEMO and REAL.
    ORDER_EXECUTION_ENABLED: bool = True

    # ==================================================
    # AUTOMATIC TRADING
    # ==================================================

    AUTO_TRADING_ENABLED: bool = True

    # A+ setup threshold
    MIN_SETUP_SCORE: int = int(
        os.getenv("MIN_SETUP_SCORE", "85")
    )

    # ==================================================
    # EXNESS CREDENTIALS
    # ==================================================

    EXN_API_KEY: str = os.getenv(
        "EXN_API_KEY", ""
    ).strip()

    EXN_PRIVATE_KEY: str = os.getenv(
        "EXN_PRIVATE_KEY", ""
    ).strip()

    EXN_ACCOUNT_ID: str = os.getenv(
        "EXN_ACCOUNT_ID", ""
    ).strip()

    EXN_GATEWAY_HOST: str = os.getenv(
        "EXN_GATEWAY_HOST", ""
    ).strip()

    # ==================================================
    # APPROVED ACTIVE INSTRUMENTS
    # ==================================================

    INSTRUMENTS: tuple = env_list(
        "INSTRUMENTS",
        "EURUSD,GBPUSD,BTCUSD"
    )

    # ==================================================
    # STRATEGY TIMEFRAMES
    # ==================================================

    ANALYSIS_TIMEFRAMES: tuple = (
        "H1",
        "M5",
        "M1",
    )

    # ==================================================
    # MARKET DATA TIMEFRAMES
    # ==================================================

    DATA_TIMEFRAMES: tuple = (
        "D1",
        "H4",
        "H1",
        "M30",
        "M15",
        "M5",
        "M1",
    )

    # ==================================================
    # RISK MANAGEMENT
    # ==================================================

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

    # ==================================================
    # SCANNER
    # ==================================================

    SCAN_INTERVAL_SECONDS: int = int(
        os.getenv("SCAN_INTERVAL_SECONDS", "15")
    )

    # ==================================================
    # LOGGING
    # ==================================================

    LOG_LEVEL: str = os.getenv(
        "LOG_LEVEL", "INFO"
    ).upper()


settings = Settings()


# ======================================================
# CONFIGURATION VALIDATION
# ======================================================

def validate_settings():

    if settings.BOT_MODE not in ("DEMO", "REAL"):
        raise ValueError(
            "BOT_MODE must be DEMO or REAL."
        )

    if settings.ORDER_EXECUTION_ENABLED is not True:
        raise RuntimeError(
            "Automatic order execution must be enabled."
        )

    if settings.AUTO_TRADING_ENABLED is not True:
        raise RuntimeError(
            "Automatic trading must be enabled."
        )

    # Exactly three approved instruments, without duplicates.
    approved_instruments = (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    )

    if settings.INSTRUMENTS != approved_instruments:
        raise ValueError(
            "Vrotex Bot V1 must use exactly "
            "EURUSD, GBPUSD and BTCUSD, without duplicates. "
            "Check the INSTRUMENTS environment variable."
        )

    # Strategy timeframe validation.
    if settings.ANALYSIS_TIMEFRAMES != (
        "H1",
        "M5",
        "M1",
    ):
        raise ValueError(
            "Strategy timeframes must be H1, M5 and M1."
        )

    # Market data timeframe validation.
    approved_data_timeframes = (
        "D1",
        "H4",
        "H1",
        "M30",
        "M15",
        "M5",
        "M1",
    )

    if settings.DATA_TIMEFRAMES != approved_data_timeframes:
        raise ValueError(
            "Market data timeframes do not match V1."
        )

    # Exact approved risk settings.
    if not math.isclose(settings.RISK_PERCENT, 1.0):
        raise ValueError(
            "Risk per trade must be exactly 1%."
        )

    if settings.MIN_SETUP_SCORE < 85:
        raise ValueError(
            "Minimum A+ setup score cannot be below 85."
        )

    if settings.MAX_DAILY_TRADES != 5:
        raise ValueError(
            "Maximum daily trades must be exactly 5."
        )

    if settings.MAX_CONSECUTIVE_LOSSES != 2:
        raise ValueError(
            "Maximum consecutive losses must be exactly 2."
        )

    if not math.isclose(
        settings.MAX_DAILY_LOSS_PERCENT, 2.0
    ):
        raise ValueError(
            "Maximum daily loss must be exactly 2%."
        )

    if settings.SCAN_INTERVAL_SECONDS < 1:
        raise ValueError(
            "Scanner interval must be at least 1 second."
        )

    # REAL mode credential validation.
    if settings.BOT_MODE == "REAL":

        credentials = (
            settings.EXN_API_KEY,
            settings.EXN_PRIVATE_KEY,
            settings.EXN_ACCOUNT_ID,
            settings.EXN_GATEWAY_HOST,
        )

        if not all(credentials):
            raise ValueError(
                "REAL mode requires all four Exness credentials."
            )

    # Configuration report.
    print("=" * 50)
    print("VROTEX BOT V1 CONFIGURATION")
    print("=" * 50)

    print(f"Mode: {settings.BOT_MODE}")
    print(f"Execution enabled: {settings.ORDER_EXECUTION_ENABLED}")
    print(f"Automatic trading: {settings.AUTO_TRADING_ENABLED}")

    print(f"Instruments: {', '.join(settings.INSTRUMENTS)}")

    print(
        f"Strategy: "
        f"{' -> '.join(settings.ANALYSIS_TIMEFRAMES)}"
    )

    print(
        f"Data timeframes: "
        f"{', '.join(settings.DATA_TIMEFRAMES)}"
    )

    print(f"Minimum A+ score: {settings.MIN_SETUP_SCORE}")
    print(f"Risk per trade: {settings.RISK_PERCENT}%")
    print(f"Maximum daily trades: {settings.MAX_DAILY_TRADES}")
    print(
        f"Maximum consecutive losses: "
        f"{settings.MAX_CONSECUTIVE_LOSSES}"
    )
    print(
        f"Maximum daily loss: "
        f"{settings.MAX_DAILY_LOSS_PERCENT}%"
    )

    print("=" * 50)
    print("CONFIGURATION VALIDATION SUCCESSFUL")
    print("=" * 50)


if __name__ == "__main__":
    validate_settings()
