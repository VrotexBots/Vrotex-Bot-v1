
"""
VROTEX BOT V1 - ORB ENTRY ENGINE
File: orb_entry_engine.py

Handles:
1. M1 retests of the broken session opening-range boundary.
2. Option A: Limit-entry candidates at the range boundary.
3. Option B: Rejection-candle confirmation candidates.
4. Retest timeout protection.
5. Stop-loss and opposing-liquidity target validation.

This module does NOT place orders.
All candidates must pass the central Vrotex
authorization, risk and execution systems.
"""

from datetime import datetime, timezone, timedelta

from orb_config import (
    ORB_ENABLED,
    ORB_ENTRY_TIMEFRAME,
    ORB_MAX_RETEST_WAIT_MINUTES,
    ORB_REQUIRE_ENTRY_CONFIRMATION,
)


class ORBEntryEngine:

    LIMIT_ENTRY = "LIMIT"
    CONFIRMATION_ENTRY = "CONFIRMATION"

    VALID_MODELS = (
        LIMIT_ENTRY,
        CONFIRMATION_ENTRY,
    )

    VALID_DIRECTIONS = (
        "BULLISH",
        "BEARISH",
    )

    VALID_ZONES = (
        "OB",
        "FVG",
        "ORB_RANGE_BOUNDARY",
    )

    def __init__(self):

        self.pending_retests = {}
        self.completed_candidates = {}

    # --------------------------------------------------------
    # DATETIME
    # --------------------------------------------------------

    @staticmethod
    def _parse_datetime(value):

        if isinstance(value, datetime):
            result = value

        elif isinstance(value, str):
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        else:
            raise ValueError("Invalid datetime.")

        if result.tzinfo is None:
            raise ValueError(
                "Datetime must be timezone-aware."
            )

        return result.astimezone(timezone.utc)

    # --------------------------------------------------------
    # CANDLE VALIDATION
    # --------------------------------------------------------

    @classmethod
    def _validate_candle(cls, candle):

        if not isinstance(candle, dict):
            raise ValueError("Candle must be a dictionary.")

        required = (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
        )

        for field in required:

            if field not in candle:
                raise ValueError(
                    f"Missing candle field: {field}"
                )

        try:

            values = {
                field: float(candle[field])
                for field in (
                    "open",
                    "high",
                    "low",
                    "close",
                )
            }

        except (TypeError, ValueError):

            raise ValueError(
                "Invalid candle prices."
            )

        if any(value <= 0 for value in values.values()):
            raise ValueError("Candle prices must be positive.")

        if values["high"] < max(
            values["open"],
            values["close"],
            values["low"],
        ):
            raise ValueError("Invalid candle high.")

        if values["low"] > min(
            values["open"],
            values["close"],
            values["high"],
        ):
            raise ValueError("Invalid candle low.")

        return {
            "timestamp": cls._parse_datetime(
                candle["timestamp"]
            ),
            **values,
        }

    # --------------------------------------------------------
    # ZONE VALIDATION
    # --------------------------------------------------------

    @staticmethod
    def _validate_zone(zone, direction):

        if not isinstance(zone, dict):
            return False

        zone_type = str(
            zone.get("type", "")
        ).upper()

        zone_direction = str(
            zone.get("direction", "")
        ).upper()

        if zone_type not in ORBEntryEngine.VALID_ZONES:
            return False

        if zone_direction != direction:
            return False

        try:

            zone_high = float(zone["high"])
            zone_low = float(zone["low"])

        except (KeyError, TypeError, ValueError):

            return False

        if zone_low <= 0:
            return False

        if zone_type == "ORB_RANGE_BOUNDARY":
            if zone_high != zone_low:
                return False
        elif zone_high <= zone_low:
            return False

        if zone.get("validated") is not True:
            return False

        return True

    # --------------------------------------------------------
    # RETEST DETECTION
    # --------------------------------------------------------

    @staticmethod
    def _zone_touched(candle, zone, tolerance):

        zone_high = float(zone["high"])
        zone_low = float(zone["low"])

        return (
            candle["low"] <= zone_high + tolerance
            and
            candle["high"] >= zone_low - tolerance
        )

    # --------------------------------------------------------
    # ENTRY PRICE
    # --------------------------------------------------------

    @staticmethod
    def _limit_entry_price(zone):

        if "entry_price" not in zone:
            return None

        try:
            price = float(zone["entry_price"])
        except (TypeError, ValueError):
            return None

        if price <= 0:
            return None

        return price

    # --------------------------------------------------------
    # RISK DATA VALIDATION
    # --------------------------------------------------------

    @staticmethod
    def _validate_trade_levels(
        direction,
        entry_price,
        stop_loss,
        liquidity_target,
    ):

        try:

            entry = float(entry_price)
            stop = float(stop_loss)
            target = float(liquidity_target)

        except (TypeError, ValueError):

            return False

        if min(entry, stop, target) <= 0:
            return False

        if direction == "BULLISH":

            if not stop < entry < target:
                return False

        elif direction == "BEARISH":

            if not target < entry < stop:
                return False

        else:
            return False

        return True

    # --------------------------------------------------------
    # RETEST TIMEOUT
    # --------------------------------------------------------

    def _check_timeout(self, breakout, candle_time):

        detected_at = self._parse_datetime(
            breakout["detected_at"]
        )

        deadline = detected_at + timedelta(
            minutes=ORB_MAX_RETEST_WAIT_MINUTES
        )

        if candle_time > deadline:
            return True

        return False

    # --------------------------------------------------------
    # CONFIRMATION CANDLE
    # --------------------------------------------------------

    @staticmethod
    def _has_rejection_confirmation(
        candle,
        zone,
        direction,
    ):

        zone_high = float(zone["high"])
        zone_low = float(zone["low"])

        if direction == "BEARISH":

            bearish_close = (
                candle["close"] < candle["open"]
                and candle["close"] < zone_low
            )

            upper_wick = (
                candle["high"]
                - max(candle["open"], candle["close"])
            )

            body = abs(
                candle["open"] - candle["close"]
            )

            rejection = (
                bearish_close
                and upper_wick > 0
                and body > 0
            )

            return rejection

        if direction == "BULLISH":

            bullish_close = (
                candle["close"] > candle["open"]
                and candle["close"] > zone_high
            )

            lower_wick = (
                min(candle["open"], candle["close"])
                - candle["low"]
            )

            body = abs(
                candle["close"] - candle["open"]
            )

            rejection = (
                bullish_close
                and lower_wick > 0
                and body > 0
            )

            return rejection

        return False

    # --------------------------------------------------------
    # MAIN ENTRY EVALUATION
    # --------------------------------------------------------

    def evaluate_retest(
        self,
        breakout,
        candle,
        entry_zones,
        entry_model,
        tolerance=0.0,
        stop_loss=None,
        liquidity_target=None,
    ):

        if not ORB_ENABLED:

            return {
                "success": False,
                "reason": "ORB_DISABLED",
            }

        if not isinstance(breakout, dict):

            return {
                "success": False,
                "reason": "INVALID_BREAKOUT",
            }

        if breakout.get("detected") is not True:

            return {
                "success": False,
                "reason": "BREAKOUT_NOT_CONFIRMED",
            }

        if not isinstance(entry_zones, (list, tuple)):

            return {
                "success": False,
                "reason": "INVALID_ENTRY_ZONES",
            }

        direction = str(
            breakout.get("direction", "")
        ).upper()

        if direction not in self.VALID_DIRECTIONS:

            return {
                "success": False,
                "reason": "INVALID_DIRECTION",
            }

        entry_model = str(
            entry_model
        ).upper()

        if entry_model not in self.VALID_MODELS:

            return {
                "success": False,
                "reason": "INVALID_ENTRY_MODEL",
            }

        if entry_model == self.CONFIRMATION_ENTRY:
            if ORB_REQUIRE_ENTRY_CONFIRMATION is False:
                return {
                    "success": False,
                    "reason": "ENTRY_CONFIRMATION_DISABLED",
                }

        try:

            data = self._validate_candle(candle)

            tolerance = float(tolerance)

            if tolerance < 0:
                raise ValueError(
                    "Tolerance cannot be negative."
                )

        except (ValueError, TypeError) as exc:

            return {
                "success": False,
                "reason": str(exc),
            }

        if not entry_zones:

            return {
                "success": False,
                "reason": "NO_VALIDATED_ORB_RANGE_BOUNDARY",
            }

        symbol = breakout.get("symbol")
        session = breakout.get("session")

        if not symbol or not session:

            return {
                "success": False,
                "reason": "MISSING_BREAKOUT_IDENTITY",
            }

        try:

            breakout_time = self._parse_datetime(
                breakout["detected_at"]
            )

        except (KeyError, ValueError, TypeError):

            return {
                "success": False,
                "reason": "INVALID_BREAKOUT_TIME",
            }

        if data["timestamp"] <= breakout_time:

            return {
                "success": False,
                "reason": "CANDLE_NOT_AFTER_BREAKOUT",
            }

        if self._check_timeout(
            breakout,
            data["timestamp"],
        ):

            return {
                "success": False,
                "reason": "RETEST_TIMEOUT_EXPIRED",
            }

        key = (
            session,
            symbol,
            direction,
        )

        if key in self.completed_candidates:

            return {
                "success": False,
                "reason": "ENTRY_CANDIDATE_ALREADY_CREATED",
            }

        touched_zones = []

        for zone in entry_zones:

            if not self._validate_zone(
                zone,
                direction,
            ):
                continue

            if self._zone_touched(
                data,
                zone,
                tolerance,
            ):

                touched_zones.append(zone)

        if not touched_zones:

            return {
                "success": False,
                "reason": "WAITING_FOR_BROKEN_RANGE_BOUNDARY_RETEST",
            }

        for zone in touched_zones:

            if entry_model == self.LIMIT_ENTRY:

                entry_price = self._limit_entry_price(
                    zone
                )

                if entry_price is None:
                    continue

                order_type = (
                    "BUY_LIMIT"
                    if direction == "BULLISH"
                    else "SELL_LIMIT"
                )

                status = "LIMIT_CANDIDATE"

            else:

                confirmed = (
                    self._has_rejection_confirmation(
                        data,
                        zone,
                        direction,
                    )
                )

                if not confirmed:
                    continue

                entry_price = data["close"]

                order_type = (
                    "BUY"
                    if direction == "BULLISH"
                    else "SELL"
                )

                status = "CONFIRMATION_CANDIDATE"

            if not self._validate_trade_levels(
                direction,
                entry_price,
                stop_loss,
                liquidity_target,
            ):
                continue

            candidate = {
                "success": True,
                "status": status,
                "strategy": "ORB",
                "session": session,
                "symbol": symbol,
                "direction": direction,
                "timeframe": ORB_ENTRY_TIMEFRAME,
                "entry_model": entry_model,
                "order_type": order_type,
                "entry_price": entry_price,
                "stop_loss": float(stop_loss),
                "take_profit": float(liquidity_target),
                "target_type": "OPPOSING_LIQUIDITY",
                "zone_type": str(
                    zone["type"]
                ).upper(),
                "zone_high": float(zone["high"]),
                "zone_low": float(zone["low"]),
                "retest_candle": data,
                "breakout_time": breakout_time,
                "created_at": datetime.now(timezone.utc),
                "execution_authorized": False,
                "requires_central_authorization": True,
            }

            self.completed_candidates[key] = candidate.copy()

            return {
                "success": True,
                "reason": status,
                "candidate": candidate.copy(),
            }

        return {
            "success": False,
            "reason": "NO_VALID_ENTRY_CANDIDATE",
        }

    # --------------------------------------------------------
    # STATE ACCESS
    # --------------------------------------------------------

    def get_candidate(
        self,
        session,
        symbol,
        direction,
    ):

        result = self.completed_candidates.get(
            (
                session,
                symbol,
                direction,
            )
        )

        return result.copy() if result else None

    def reset_session(self, session, symbol):

        keys = [
            key
            for key in self.completed_candidates
            if key[0] == session and key[1] == symbol
        ]

        for key in keys:
            self.completed_candidates.pop(key, None)

        pending_keys = [
            key
            for key in self.pending_retests
            if key[0] == session and key[1] == symbol
        ]

        for key in pending_keys:
            self.pending_retests.pop(key, None)
