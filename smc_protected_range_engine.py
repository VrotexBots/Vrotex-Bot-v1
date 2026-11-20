
"""
VROTEX BOT V1
SMC Protected Range Engine

Purpose:
- Identify confirmed swing highs and lows.
- Track protected highs and lows.
- Detect body-close breaks of protected levels.
- Maintain bullish and bearish protected-range context.
- Provide structural invalidation evidence.

Approved rules:
- Bullish structure protects the relevant higher low.
- Bearish structure protects the relevant lower high.
- Wick-only breaks are not structural breaks.
- Full candle-body close beyond a protected level confirms a break.

This module does not authorize order execution.
"""

from typing import Any, Dict, List, Optional


class SMCProtectedRangeEngine:
    VERSION = "2.0"

    def __init__(self, swing_strength: int = 2):
        self.swing_strength = max(1, int(swing_strength))
        self.last_result: Dict[str, Any] = {}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)

            if number != number:
                return None

            if number in (float("inf"), float("-inf")):
                return None

            return number
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    @staticmethod
    def _price(
        candle: Dict[str, Any],
        field: str,
    ) -> Optional[float]:
        value = candle.get(field)

        if value is None:
            value = candle.get(field.upper())

        try:
            number = float(value)

            if number != number:
                return None

            if number in (float("inf"), float("-inf")):
                return None

            return number
        except (TypeError, ValueError):
            return None

    def _normalise_candles(
        self,
        candles: Any,
    ) -> List[Dict[str, Any]]:
        if not isinstance(candles, list):
            return []

        result = []

        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                continue

            high = self._price(candle, "high")
            low = self._price(candle, "low")
            open_price = self._price(candle, "open")
            close = self._price(candle, "close")

            if None in (high, low, open_price, close):
                continue

            if high < low:
                continue

            if high < max(open_price, close):
                continue

            if low > min(open_price, close):
                continue

            result.append({
                "index": index,
                "high": high,
                "low": low,
                "open": open_price,
                "close": close,
            })

        return result

    def _find_swings(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        highs = []
        lows = []
        strength = self.swing_strength

        for index in range(
            strength,
            len(candles) - strength,
        ):
            current = candles[index]

            left = candles[index - strength:index]
            right = candles[index + 1:index + strength + 1]

            is_high = all(
                current["high"] > item["high"]
                for item in left + right
            )

            is_low = all(
                current["low"] < item["low"]
                for item in left + right
            )

            if is_high:
                highs.append({
                    "price": current["high"],
                    "index": current["index"],
                    "type": "SWING_HIGH",
                    "confirmed": True,
                })

            if is_low:
                lows.append({
                    "price": current["low"],
                    "index": current["index"],
                    "type": "SWING_LOW",
                    "confirmed": True,
                })

        return {
            "highs": highs,
            "lows": lows,
        }

    def _select_protected_levels(
        self,
        swings: Dict[str, List[Dict[str, Any]]],
        direction: str,
    ) -> Dict[str, Any]:
        highs = swings["highs"]
        lows = swings["lows"]

        if direction == "BULLISH":
            protected_low = (
                lows[-1] if lows else None
            )

            protected_high = (
                highs[-1] if highs else None
            )

        else:
            protected_high = (
                highs[-1] if highs else None
            )

            protected_low = (
                lows[-1] if lows else None
            )

        return {
            "protected_high": protected_high,
            "protected_low": protected_low,
        }

    def _check_break(
        self,
        candles: List[Dict[str, Any]],
        protected: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        if not candles:
            return {
                "broken": False,
                "confirmation": None,
            }

        latest = candles[-1]
        protected_level = (
            protected.get("protected_low")
            if direction == "BULLISH"
            else protected.get("protected_high")
        )

        if not isinstance(protected_level, dict):
            return {
                "broken": False,
                "confirmation": None,
                "reason": "PROTECTED_LEVEL_UNAVAILABLE",
            }

        level = self._number(
            protected_level.get("price")
        )

        if level is None:
            return {
                "broken": False,
                "confirmation": None,
                "reason": "INVALID_PROTECTED_LEVEL",
            }

        if direction == "BULLISH":
            wick_broken = latest["low"] < level
            body_broken = latest["close"] < level
        else:
            wick_broken = latest["high"] > level
            body_broken = latest["close"] > level

        return {
            "broken": body_broken,
            "wick_probe": wick_broken and not body_broken,
            "confirmation": (
                "BODY_CLOSE"
                if body_broken
                else (
                    "WICK_ONLY"
                    if wick_broken
                    else None
                )
            ),
            "level": level,
            "candle_index": latest["index"],
        }

    def analyze(
        self,
        candles: List[Dict[str, Any]],
        direction: str,
    ) -> Dict[str, Any]:
        direction = self._direction(direction)

        if direction is None:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_DIRECTION",
            }

        normalized = self._normalise_candles(candles)

        minimum = (self.swing_strength * 2) + 3

        if len(normalized) < minimum:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INSUFFICIENT_CANDLES",
                "required": minimum,
                "received": len(normalized),
            }

        swings = self._find_swings(normalized)

        protected = self._select_protected_levels(
            swings,
            direction,
        )

        break_result = self._check_break(
            normalized,
            protected,
            direction,
        )

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "valid": True,
            "direction": direction,
            "swing_highs": swings["highs"],
            "swing_lows": swings["lows"],
            "protected_high": protected["protected_high"],
            "protected_low": protected["protected_low"],
            "protected_level_broken": break_result["broken"],
            "wick_probe": break_result.get(
                "wick_probe",
                False,
            ),
            "break_evidence": break_result,
            "execution_authorized": False,
        }

        self.last_result = result

        return result

    def get_state(self) -> Dict[str, Any]:
        return dict(self.last_result)


smc_protected_range_engine = SMCProtectedRangeEngine()
