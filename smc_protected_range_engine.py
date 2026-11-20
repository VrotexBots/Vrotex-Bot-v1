
"""
VROTEX BOT V1
SMC PROTECTED RANGE ENGINE

Responsibilities:
- Track protected highs and lows.
- Identify bullish and bearish protected levels.
- Detect wick sweeps without treating them as breaks.
- Confirm breaks using candle-body closes.
- Track invalidated and active protected levels.

This module does not execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCProtectedRangeEngine:

    def __init__(self, tolerance: float = 0.0):
        self.tolerance = max(0.0, float(tolerance))
        self.protected_high: Optional[Dict[str, Any]] = None
        self.protected_low: Optional[Dict[str, Any]] = None
        self.events: List[Dict[str, Any]] = []

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)
            if number != number or number in (
                float("inf"), float("-inf")
            ):
                return None
            return number
        except (TypeError, ValueError):
            return None

    def _candles(
        self,
        candles: List[Dict[str, Any]]
    ) -> List[Dict[str, float]]:

        result = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            values = {
                key: self._number(candle.get(key))
                for key in ("open", "high", "low", "close")
            }

            if any(value is None for value in values.values()):
                continue

            if values["high"] < max(
                values["open"], values["close"]
            ):
                continue

            if values["low"] > min(
                values["open"], values["close"]
            ):
                continue

            if values["high"] < values["low"]:
                continue

            result.append(values)

        return result

    def identify_swings(
        self,
        candles: List[Dict[str, Any]],
        left: int = 2,
        right: int = 2
    ) -> Dict[str, Any]:

        data = self._candles(candles)
        left = max(1, int(left))
        right = max(1, int(right))

        highs = []
        lows = []

        if len(data) < left + right + 1:
            return {
                "valid": False,
                "status": "INSUFFICIENT_CANDLES",
                "highs": [],
                "lows": [],
            }

        for index in range(left, len(data) - right):

            candle = data[index]

            surrounding = (
                data[index-left:index] +
                data[index+1:index+right+1]
            )

            is_high = all(
                candle["high"] > item["high"]
                for item in surrounding
            )

            is_low = all(
                candle["low"] < item["low"]
                for item in surrounding
            )

            if is_high:
                highs.append({
                    "index": index,
                    "price": candle["high"],
                    "confirmed": True,
                })

            if is_low:
                lows.append({
                    "index": index,
                    "price": candle["low"],
                    "confirmed": True,
                })

        return {
            "valid": True,
            "status": "SWINGS_IDENTIFIED",
            "highs": highs,
            "lows": lows,
        }

    def set_protected_levels(
        self,
        direction: str,
        swing_high: Dict[str, Any],
        swing_low: Dict[str, Any],
    ) -> Dict[str, Any]:

        direction = str(direction).upper()

        if direction not in ("BULLISH", "BEARISH"):
            return {
                "valid": False,
                "error": "INVALID_DIRECTION",
            }

        high = self._number(swing_high.get("price"))
        low = self._number(swing_low.get("price"))

        if high is None or low is None or high <= low:
            return {
                "valid": False,
                "error": "INVALID_SWING_LEVELS",
            }

        if direction == "BULLISH":
            self.protected_low = {
                "price": low,
                "index": swing_low.get("index"),
                "direction": direction,
                "active": True,
                "status": "PROTECTED",
            }

        else:
            self.protected_high = {
                "price": high,
                "index": swing_high.get("index"),
                "direction": direction,
                "active": True,
                "status": "PROTECTED",
            }

        return {
            "valid": True,
            "status": "PROTECTED_LEVELS_UPDATED",
            "direction": direction,
            "protected_high": self.protected_high,
            "protected_low": self.protected_low,
        }

    def update(
        self,
        candles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:

        data = self._candles(candles)

        if not data:
            return {
                "valid": False,
                "status": "NO_VALID_CANDLES",
            }

        candle = data[-1]
        events = []

        if self.protected_low and self.protected_low["active"]:

            level = self.protected_low["price"]

            if candle["close"] < level - self.tolerance:
                self.protected_low["active"] = False
                self.protected_low["status"] = "INVALIDATED"

                events.append({
                    "type": "PROTECTED_LOW_BROKEN",
                    "direction": "BEARISH",
                    "level": level,
                    "confirmed": True,
                    "method": "BODY_CLOSE",
                })

            elif candle["low"] < level - self.tolerance:
                events.append({
                    "type": "PROTECTED_LOW_SWEPT",
                    "direction": "BEARISH",
                    "level": level,
                    "confirmed": False,
                    "method": "WICK_ONLY",
                })

        if self.protected_high and self.protected_high["active"]:

            level = self.protected_high["price"]

            if candle["close"] > level + self.tolerance:
                self.protected_high["active"] = False
                self.protected_high["status"] = "INVALIDATED"

                events.append({
                    "type": "PROTECTED_HIGH_BROKEN",
                    "direction": "BULLISH",
                    "level": level,
                    "confirmed": True,
                    "method": "BODY_CLOSE",
                })

            elif candle["high"] > level + self.tolerance:
                events.append({
                    "type": "PROTECTED_HIGH_SWEPT",
                    "direction": "BULLISH",
                    "level": level,
                    "confirmed": False,
                    "method": "WICK_ONLY",
                })

        self.events.extend(events)
        self.events = self.events[-200:]

        return {
            "valid": True,
            "status": "PROTECTED_LEVELS_UPDATED",
            "events": events,
            "protected_high": self.protected_high,
            "protected_low": self.protected_low,
        }

    def analyse(
        self,
        candles: List[Dict[str, Any]],
        direction: str,
        left: int = 2,
        right: int = 2,
    ) -> Dict[str, Any]:

        swings = self.identify_swings(
            candles,
            left=left,
            right=right,
        )

        if not swings["valid"]:
            return swings

        if not swings["highs"] or not swings["lows"]:
            return {
                "valid": False,
                "status": "SWING_LEVELS_NOT_FOUND",
                "swings": swings,
            }

        swing_high = swings["highs"][-1]
        swing_low = swings["lows"][-1]

        levels = self.set_protected_levels(
            direction,
            swing_high,
            swing_low,
        )

        if not levels["valid"]:
            return levels

        update = self.update(candles)

        return {
            "valid": update["valid"],
            "status": "ANALYSIS_COMPLETE",
            "direction": direction.upper(),
            "swings": swings,
            "levels": levels,
            "update": update,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "module": "SMCProtectedRangeEngine",
            "protected_high": self.protected_high,
            "protected_low": self.protected_low,
            "recent_events": self.events[-20:],
        }


smc_protected_range_engine = SMCProtectedRangeEngine()
