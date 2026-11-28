
"""
VROTEX BOT V1 - ORB ANALYSIS ENGINE
File: orb_analysis_engine.py

Captures the first five-minute session candle,
establishes the opening range and detects breakouts.

No order execution is performed here.
"""

from datetime import datetime, timezone

from orb_config import (
    ORB_ENABLED,
    ORB_ALLOW_BULLISH_BREAKOUT,
    ORB_ALLOW_BEARISH_BREAKOUT,
    ORB_REQUIRE_CANDLE_CLOSE,
    ORB_CANDLE_DURATION_MINUTES,
)

from orb_session_engine import ORBSessionEngine


class ORBAnalysisEngine:

    def __init__(self, session_engine=None):

        self.session_engine = (
            session_engine or ORBSessionEngine()
        )

        self.opening_ranges = {}
        self.breakout_states = {}

    @staticmethod
    def _parse_datetime(value):

        if isinstance(value, datetime):
            result = value

        elif isinstance(value, str):
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        else:
            raise ValueError(
                "Candle timestamp must be a datetime or ISO string."
            )

        if result.tzinfo is None:
            raise ValueError(
                "Candle timestamp must include a timezone."
            )

        return result.astimezone(timezone.utc)

    @staticmethod
    def _validate_candle(candle):

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
                for field in ("open", "high", "low", "close")
            }
        except (TypeError, ValueError):
            raise ValueError("Invalid OHLC candle values.")

        if any(
            value <= 0
            for value in values.values()
        ):
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
            "timestamp": ORBAnalysisEngine._parse_datetime(
                candle["timestamp"]
            ),
            **values,
        }

    def capture_opening_range(
        self,
        session_name,
        symbol,
        candle,
        now=None,
    ):

        if not ORB_ENABLED:
            return {
                "success": False,
                "reason": "ORB_DISABLED",
            }

        try:
            data = self._validate_candle(candle)
        except ValueError as exc:
            return {
                "success": False,
                "reason": str(exc),
            }

        window = self.session_engine.get_opening_candle_window(
            session_name,
            now,
        )

        if window is None:
            return {
                "success": False,
                "reason": "SESSION_UNAVAILABLE",
            }

        if not window["complete"]:
            return {
                "success": False,
                "reason": "OPENING_CANDLE_NOT_COMPLETE",
            }

        if data["timestamp"] != window["start"]:
            return {
                "success": False,
                "reason": "CANDLE_NOT_SESSION_OPENING_CANDLE",
            }

        key = (session_name, symbol)

        if key in self.opening_ranges:
            return {
                "success": False,
                "reason": "OPENING_RANGE_ALREADY_CAPTURED",
            }

        opening_range = {
            "session": session_name,
            "symbol": symbol,
            "start_time": data["timestamp"],
            "end_time": window["end"],
            "high": data["high"],
            "low": data["low"],
            "open": data["open"],
            "close": data["close"],
            "completed": True,
            "breakout_detected": False,
        }

        self.opening_ranges[key] = opening_range

        self.breakout_states[key] = None

        self.session_engine.update_session_state(
            session_name=session_name,
            symbol=symbol,
            opening_high=data["high"],
            opening_low=data["low"],
            completed=True,
        )

        return {
            "success": True,
            "reason": "OPENING_RANGE_CAPTURED",
            "opening_range": opening_range.copy(),
        }

    def get_opening_range(self, session_name, symbol):

        result = self.opening_ranges.get(
            (session_name, symbol)
        )

        return result.copy() if result else None

    def detect_breakout(
        self,
        session_name,
        symbol,
        candle,
    ):

        if not ORB_ENABLED:
            return {
                "detected": False,
                "reason": "ORB_DISABLED",
            }

        key = (session_name, symbol)

        opening_range = self.opening_ranges.get(key)

        if not opening_range:
            return {
                "detected": False,
                "reason": "OPENING_RANGE_NOT_AVAILABLE",
            }

        if not opening_range["completed"]:
            return {
                "detected": False,
                "reason": "OPENING_RANGE_INCOMPLETE",
            }

        if opening_range["breakout_detected"]:
            return {
                "detected": False,
                "reason": "BREAKOUT_ALREADY_DETECTED",
            }

        try:
            data = self._validate_candle(candle)
        except ValueError as exc:
            return {
                "detected": False,
                "reason": str(exc),
            }

        if data["timestamp"] < opening_range["end_time"]:
            return {
                "detected": False,
                "reason": "CANDLE_BEFORE_OPENING_RANGE_END",
            }

        if ORB_REQUIRE_CANDLE_CLOSE:

            bullish = (
                data["close"] > opening_range["high"]
            )

            bearish = (
                data["close"] < opening_range["low"]
            )

        else:

            bullish = (
                data["high"] > opening_range["high"]
            )

            bearish = (
                data["low"] < opening_range["low"]
            )

        direction = None
        breakout_level = None

        if bullish and ORB_ALLOW_BULLISH_BREAKOUT:
            direction = "BULLISH"
            breakout_level = opening_range["high"]

        elif bearish and ORB_ALLOW_BEARISH_BREAKOUT:
            direction = "BEARISH"
            breakout_level = opening_range["low"]

        if direction is None:
            return {
                "detected": False,
                "reason": "NO_CONFIRMED_BREAKOUT",
            }

        result = {
            "detected": True,
            "session": session_name,
            "symbol": symbol,
            "direction": direction,
            "breakout_level": breakout_level,
            "breakout_candle": data,
            "opening_high": opening_range["high"],
            "opening_low": opening_range["low"],
            "detected_at": data["timestamp"],
        }

        opening_range["breakout_detected"] = True

        self.breakout_states[key] = result

        return result.copy()

    def get_breakout_state(self, session_name, symbol):

        result = self.breakout_states.get(
            (session_name, symbol)
        )

        return result.copy() if result else None

    def reset_session(self, session_name, symbol):

        key = (session_name, symbol)

        self.opening_ranges.pop(key, None)
        self.breakout_states.pop(key, None)

        self.session_engine.reset_session(
            session_name,
            symbol,
        )
