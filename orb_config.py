
"""
VROTEX BOT V1 - OPENING RANGE BREAKOUT
File: orb_config.py

Dedicated configuration for the ORB strategy.
Does not modify SMC configuration.
"""

from zoneinfo import ZoneInfo


# ============================================================
# STRATEGY IDENTITY
# ============================================================

ORB_ENABLED = True
ORB_STRATEGY_NAME = "OPENING_RANGE_BREAKOUT"
ORB_STRATEGY_VERSION = "1.0"


# ============================================================
# APPROVED VROTEX V1 INSTRUMENTS
# ============================================================

ORB_SYMBOLS = (
    "EURUSD",
    "GBPUSD",
    "BTCUSD",
)


# ============================================================
# SESSION CONFIGURATION
# All session times use their actual local time zones.
# ============================================================

ORB_SESSIONS = {
    "ASIAN": {
        "enabled": True,
        "timezone": "Asia/Tokyo",
        "hour": 9,
        "minute": 0,
    },

    "LONDON": {
        "enabled": True,
        "timezone": "Europe/London",
        "hour": 8,
        "minute": 0,
    },

    "NEW_YORK": {
        "enabled": True,
        "timezone": "America/New_York",
        "hour": 9,
        "minute": 30,
    },
}


# ============================================================
# OPENING RANGE
# ============================================================

ORB_TIMEFRAME = "M5"
ORB_CANDLE_DURATION_MINUTES = 5

ORB_REQUIRE_COMPLETED_CANDLE = True

ORB_MARK_RANGE_HIGH = True
ORB_MARK_RANGE_LOW = True


# ============================================================
# BREAKOUT CONFIGURATION
# ============================================================

ORB_REQUIRE_CANDLE_CLOSE = True

ORB_ALLOW_BULLISH_BREAKOUT = True
ORB_ALLOW_BEARISH_BREAKOUT = True

ORB_REQUIRE_RETEST = True

ORB_RETEST_TOLERANCE_PIPS = 2.0

ORB_MAX_RETEST_WAIT_MINUTES = 60


# ============================================================
# ENTRY CONFIGURATION
# ============================================================

ORB_ENTRY_TIMEFRAME = "M1"

ORB_REQUIRE_ENTRY_CONFIRMATION = True

ORB_ALLOW_MULTIPLE_TRADES_PER_SESSION = False

ORB_MAX_TRADES_PER_SESSION = 1


# ============================================================
# RISK MANAGEMENT
# Uses the existing Vrotex risk manager.
# These values are reference requirements, not an
# independent authorization mechanism.
# ============================================================

ORB_RISK_PER_TRADE_PERCENT = 1.0

ORB_USE_CENTRAL_RISK_MANAGER = True

ORB_USE_CENTRAL_EXECUTION_ENGINE = True

ORB_USE_CENTRAL_TRADE_MANAGER = True


# ============================================================
# LIQUIDITY TARGETING
# ============================================================

ORB_TARGET_OPPOSING_LIQUIDITY = True

ORB_REQUIRE_LIQUIDITY_TARGET = True


# ============================================================
# SAFETY
# ============================================================

ORB_ALLOW_UNCONFIRMED_ENTRIES = False

ORB_ALLOW_DUPLICATE_ORDERS = False

ORB_REQUIRE_MARKET_DATA = True

ORB_REQUIRE_VALID_SESSION = True


# ============================================================
# VALIDATION
# ============================================================

def validate_orb_config():

    if not ORB_ENABLED:
        return False

    if ORB_TIMEFRAME != "M5":
        raise ValueError("ORB opening range must use M5.")

    if ORB_ENTRY_TIMEFRAME != "M1":
        raise ValueError("ORB entry timeframe must use M1.")

    if ORB_CANDLE_DURATION_MINUTES != 5:
        raise ValueError("ORB opening candle must be five minutes.")

    if ORB_RISK_PER_TRADE_PERCENT <= 0:
        raise ValueError("ORB risk percentage must be positive.")

    if not ORB_USE_CENTRAL_RISK_MANAGER:
        raise ValueError(
            "ORB must use the central Vrotex risk manager."
        )

    if not ORB_USE_CENTRAL_EXECUTION_ENGINE:
        raise ValueError(
            "ORB must use the central execution engine."
        )

    for session in ORB_SESSIONS.values():
        ZoneInfo(session["timezone"])

    return True


if __name__ == "__main__":
    print("VROTEX ORB CONFIGURATION")
    print("Validation:", validate_orb_config())
    print("Symbols:", ORB_SYMBOLS)
    print("Sessions:", list(ORB_SESSIONS.keys()))
