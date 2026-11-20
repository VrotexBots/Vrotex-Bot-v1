
"""
VROTEX BOT V1
SMC Range Engine

Purpose:
- Identify the current dealing range.
- Calculate range high, low and equilibrium.
- Calculate Fibonacci retracement levels.
- Classify premium, discount and equilibrium.
- Provide range evidence to the SMC master engine.

Strategy:
- Bullish: strong low to weak high.
- Bearish: strong high to weak low.
- Equilibrium: 50%.

This module does not authorize order execution.
"""

from typing import Any, Dict, List, Optional


class SMCRangeEngine:
    VERSION = "2.0"

    FIBONACCI_LEVELS = (
        0.0,
        0.236,
        0.382,
        0.5,
        0.618,
        0.705,
        0.786,
        1.0,
    )

    def __init__(self):
        pass

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result:
                return None
            if result in (float("inf"), float("-inf")):
                return None
            return result
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
    def _candle_price(
        candle: Dict[str, Any],
        field: str,
    ) -> Optional[float]:
        try:
            value = candle.get(field)
            if value is None:
                value = candle.get(field.upper())
            result = float(value)
            if result != result:
                return None
            if result in (float("inf"), float("-inf")):
                return None
            return result
        except (TypeError, ValueError):
            return None

    def _validate_candles(
        self,
        candles: Any,
    ) -> List[Dict[str, Any]]:
        if not isinstance(candles, list):
            return []

        valid = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            high = self._candle_price(candle, "high")
            low = self._candle_price(candle, "low")

            if high is None or low is None:
                continue

            if high < low:
                continue

            valid.append(candle)

        return valid

    def _calculate_fibonacci(
        self,
        low: float,
        high: float,
        direction: str,
    ) -> Dict[str, float]:
        distance = high - low
        levels = {}

        for ratio in self.FIBONACCI_LEVELS:
            if direction == "BULLISH":
                price = high - (distance * ratio)
            else:
                price = low + (distance * ratio)

            levels[f"{ratio:.3f}"] = round(price, 10)

        return levels

    def _classify_price(
        self,
        price: float,
        low: float,
        high: float,
    ) -> str:
        midpoint = (high + low) / 2

        if price < low or price > high:
            return "OUTSIDE_RANGE"

        if price < midpoint:
            return "DISCOUNT"

        if price > midpoint:
            return "PREMIUM"

        return "EQUILIBRIUM"

    def analyze(
        self,
        candles: List[Dict[str, Any]],
        current_price: float,
        direction: str,
        range_high: Optional[float] = None,
        range_low: Optional[float] = None,
        range_source: str = "ROLLING_CANDLES",
    ) -> Dict[str, Any]:

        direction = self._direction(direction)
        price = self._number(current_price)

        if direction is None:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_DIRECTION",
            }

        if price is None or price <= 0:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_CURRENT_PRICE",
            }

        valid_candles = self._validate_candles(candles)

        if range_high is None or range_low is None:
            if len(valid_candles) < 2:
                return {
                    "status": "REJECTED",
                    "valid": False,
                    "reason": "INSUFFICIENT_CANDLES",
                }

            highs = [
                self._candle_price(candle, "high")
                for candle in valid_candles
            ]

            lows = [
                self._candle_price(candle, "low")
                for candle in valid_candles
            ]

            high = max(value for value in highs if value is not None)
            low = min(value for value in lows if value is not None)

            range_source = "ROLLING_CANDLES"

        else:
            high = self._number(range_high)
            low = self._number(range_low)

            if high is None or low is None:
                return {
                    "status": "REJECTED",
                    "valid": False,
                    "reason": "INVALID_RANGE_ANCHORS",
                }

            range_source = "STRUCTURAL_ANCHORS"

        if high <= low:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_RANGE_WIDTH",
            }

        if price < low or price > high:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "PRICE_OUTSIDE_RANGE",
                "range_high": high,
                "range_low": low,
                "current_price": price,
            }

        midpoint = (high + low) / 2
        range_width = high - low

        location = self._classify_price(
            price,
            low,
            high,
        )

        fibonacci = self._calculate_fibonacci(
            low,
            high,
            direction,
        )

        directional_valid = (
            location == "DISCOUNT"
            if direction == "BULLISH"
            else location == "PREMIUM"
        )

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "valid": True,
            "direction": direction,
            "range_source": range_source,
            "range_high": round(high, 10),
            "range_low": round(low, 10),
            "range_width": round(range_width, 10),
            "equilibrium": round(midpoint, 10),
            "current_price": round(price, 10),
            "location": location,
            "fibonacci_levels": fibonacci,
            "directional_location_valid": directional_valid,
            "execution_authorized": False,
        }


smc_range_engine = SMCRangeEngine()
