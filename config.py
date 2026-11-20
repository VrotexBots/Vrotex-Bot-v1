
import os
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
    # EXNESS CREDENTIALS
    # ==================================================

    EXN_API_KEY: str = os.getenv(
        "EXN_API_KEY", ""
    )

    EXN_PRIVATE_KEY: str = os.getenv(
        "EXN_PRIVATE_KEY", ""
    )

    EXN_ACCOUNT_ID: str = os.getenv(
        "EXN_ACCOUNT_ID", ""
    )

    EXN_GATEWAY_HOST: str = os.getenv(
        "EXN_GATEWAY_HOST", ""
    )

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
    # SETUP VALIDATION
    # ==================================================

    MIN_SETUP_SCORE: int = int(
        os.getenv("MIN_SETUP_SCORE", "85")
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

    if not settings.ORDER_EXECUTION_ENABLED:
        raise RuntimeError(
            "Automatic order execution must be enabled."
        )

    if not settings.INSTRUMENTS:
        raise ValueError(
            "No trading instruments configured."
        )

    approved_instruments = {
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    }

    if set(settings.INSTRUMENTS) != approved_instruments:
        raise ValueError(
            "Vrotex Bot V1 must use exactly "
            "EURUSD, GBPUSD and BTCUSD."
        )

    if not 0 < settings.RISK_PERCENT <= 1:
        raise ValueError(
            "Risk must be greater than 0 and no more than 1%."
        )

    if settings.MIN_SETUP_SCORE < 85:
        raise ValueError(
            "Minimum setup score cannot be below 85."
        )

    if settings.MAX_DAILY_TRADES < 1:
        raise ValueError(
            "MAX_DAILY_TRADES must be at least 1."
        )

    if settings.MAX_CONSECUTIVE_LOSSES < 1:
        raise ValueError(
            "MAX_CONSECUTIVE_LOSSES must be at least 1."
        )

    if settings.MAX_DAILY_LOSS_PERCENT <= 0:
        raise ValueError(
            "Daily loss limit must be greater than zero."
        )

    if settings.BOT_MODE == "REAL":

        credentials = (
            settings.EXN_API_KEY,
            settings.EXN_PRIVATE_KEY,
            settings.EXN_ACCOUNT_ID,
            settings.EXN_GATEWAY_HOST,
        )

        if not all(credentials):
            raise ValueError(
                "REAL mode requires all Exness credentials."
            )

    print("=" * 45)
    print("VROTEX BOT V1 CONFIGURATION")
    print("=" * 45)

    print(f"Mode: {settings.BOT_MODE}")
    print(
        f"Execution enabled: "
        f"{settings.ORDER_EXECUTION_ENABLED}"
    )

    print(
        f"Instruments: "
        f"{', '.join(settings.INSTRUMENTS)}"
    )

    print(
        f"Strategy: "
        f"{' -> '.join(settings.ANALYSIS_TIMEFRAMES)}"
    )

    print(
        f"Minimum setup score: "
        f"{settings.MIN_SETUP_SCORE}"
    )

    print(
        f"Risk per trade: "
        f"{settings.RISK_PERCENT}%"
    )

    print(
        f"Maximum daily trades: "
        f"{settings.MAX_DAILY_TRADES}"
    )

    print(
        f"Maximum consecutive losses: "
        f"{settings.MAX_CONSECUTIVE_LOSSES}"
    )

    print(
        f"Maximum daily loss: "
        f"{settings.MAX_DAILY_LOSS_PERCENT}%"
    )

    print("=" * 45)
    print("Configuration validation successful.")


if __name__ == "__main__":
    validate_settings()
