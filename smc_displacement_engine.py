"""
VROTEX BOT V1
SMC Displacement Engine

Purpose:
- Detect bullish and bearish displacement candles.
- Measure candle-body strength and range expansion.
- Compare displacement against preceding ATR.
- Identify consecutive directional displacement.
- Return structured evidence for the master SMC engine.

Strategy:
- Displacement must be supported by a strong candle body.
- Candle direction must agree with the detected displacement.
- Wick-only movement is not displacement confirmation.
- This module does not authorize trade execution.
"""

from typing import Any, Dict, List, Optional


class SMCDisplacementEngine:
    VERSION = "2.0"

    DEFAULT_ATR_PERIOD = 14
    DEFAULT_MIN_BODY_RATIO = 0.60
    DEFAULT_MIN_RANGE_ATR = 1.20
    DEFAULT_MIN_BODY_ATR = 0.70

    def __init__(
        self,
        atr_period: int = DEFAULT_ATR_PERIOD,
        min_body_ratio: float = DEFAULT_MIN_BODY_RATIO,
        min_range_atr: float = DEFAULT_MIN_RANGE_ATR,
        min_body_atr: float = DEFAULT_MIN_BODY_ATR,
    ):
        self.atr_period = max(2, int(atr_period))
        self.min_body_ratio = float(min_body_ratio)
        self.min_range_atr = float(min_range_atr)
        self.min_body_atr = float(min_body_atr)

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result or abs(result) == float("inf"):
                return None
            return result
        except (TypeError, ValueError):
            return None

    def _normalise_candles(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        normalised = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            open_price = self._number(candle.get("open"))
            high = self._number(candle.get("high"))
            low = self._number(candle.get("low"))
            close = self._number(candle.get("close"))

            if None in (open_price, high, low, close):
                continue

            if high < low:
                continue

            if high < max(open_price, close):
                continue

            if low > min(open_price, close):
                continue

            normalised.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })

        return normalised

    @staticmethod
    def _true_range(
        current: Dict[str, float],
        previous_close: Optional[float],
    ) -> float:
        high = current["high"]
        low = current["low"]

        if previous_close is None:
            return high - low

        return max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

    def _calculate_atr(
        self,
        candles: List[Dict[str, float]],
        end_index: int,
    ) -> Optional[float]:
        """
        Calculate ATR using candles BEFORE the candidate candle.

        Excluding the candidate prevents its own expansion from
        inflating the baseline used to validate displacement.
        """
        start_index = max(0, end_index - self.atr_period)

        if end_index - start_index < self.atr_period:
            return None

        true_ranges = []

        for index in range(start_index, end_index):
            previous_close = (
                candles[index - 1]["close"]
                if index > 0
                else None
            )

            true_ranges.append(
                self._true_range(
                    candles[index],
                    previous_close,
                )
            )

        if not true_ranges:
            return None

        return sum(true_ranges) / len(true_ranges)

    def _evaluate_candle(
        self,
        candles: List[Dict[str, float]],
        index: int,
    ) -> Dict[str, Any]:
        candle = candles[index]

        open_price = candle["open"]
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]

        candle_range = high - low
        body = abs(close - open_price)

        if candle_range <= 0:
            return {
                "detected": False,
                "reason": "ZERO_CANDLE_RANGE",
                "index": index,
            }

        body_ratio = body / candle_range

        if close > open_price:
            direction = "BULLISH"
        elif close < open_price:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        atr = self._calculate_atr(candles, index)

        if atr is None or atr <= 0:
            return {
                "detected": False,
                "reason": "INSUFFICIENT_ATR_HISTORY",
                "index": index,
                "direction": direction,
                "body_ratio": round(body_ratio, 4),
                "range": candle_range,
                "body": body,
            }

        range_atr = candle_range / atr
        body_atr = body / atr

        checks = {
            "directional_candle": direction != "NEUTRAL",
            "strong_body": body_ratio >= self.min_body_ratio,
            "range_expansion": range_atr >= self.min_range_atr,
            "body_expansion": body_atr >= self.min_body_atr,
        }

        detected = all(checks.values())

        return {
            "detected": detected,
            "confirmed": detected,
            "direction": direction,
            "index": index,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "range": round(candle_range, 8),
            "body": round(body, 8),
            "body_ratio": round(body_ratio, 4),
            "atr": round(atr, 8),
            "range_atr": round(range_atr, 4),
            "body_atr": round(body_atr, 4),
            "checks": checks,
            "confirmation": (
                "BODY_DISPLACEMENT"
                if detected
                else "DISPLACEMENT_NOT_CONFIRMED"
            ),
        }

    def analyse(
        self,
        candles: List[Dict[str, Any]],
        lookback: int = 10,
    ) -> Dict[str, Any]:
        if not isinstance(candles, list):
            return self._error("INVALID_CANDLE_INPUT")

        normalised = self._normalise_candles(candles)

        minimum_required = self.atr_period + 1

        if len(normalised) < minimum_required:
            return self._error(
                "INSUFFICIENT_CANDLES",
                candle_count=len(normalised),
                minimum_required=minimum_required,
            )

        lookback = max(1, int(lookback))
        start_index = max(0, len(normalised) - lookback)

        events = []

        for index in range(start_index, len(normalised)):
            result = self._evaluate_candle(normalised, index)

            if result.get("detected"):
                events.append(result)

        bullish = [
            event for event in events
            if event["direction"] == "BULLISH"
        ]

        bearish = [
            event for event in events
            if event["direction"] == "BEARISH"
        ]

        latest = (
            events[-1]
            if events
            else None
        )

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "candle_count": len(normalised),
            "lookback": lookback,
            "detected": bool(events),
            "confirmed": bool(latest),
            "direction": (
                latest["direction"]
                if latest
                else "NEUTRAL"
            ),
            "latest_displacement": latest,
            "displacements": events,
            "bullish_displacements": bullish,
            "bearish_displacements": bearish,
            "count": len(events),
            "confirmation": (
                "BODY_DISPLACEMENT"
                if latest
                else "NO_CONFIRMED_DISPLACEMENT"
            ),
        }

    def analyze(
        self,
        candles: List[Dict[str, Any]],
        lookback: int = 10,
    ) -> Dict[str, Any]:
        return self.analyse(candles, lookback)

    def validate_displacement(
        self,
        candles: List[Dict[str, Any]],
        direction: str,
        lookback: int = 10,
    ) -> Dict[str, Any]:
        result = self.analyse(candles, lookback)

        expected = str(direction).upper()

        if expected not in ("BULLISH", "BEARISH"):
            return {
                "valid": False,
                "reason": "INVALID_DIRECTION",
                "expected_direction": expected,
            }

        matching = [
            event for event in result.get("displacements", [])
            if event["direction"] == expected
        ]

        return {
            "valid": bool(matching),
            "detected": bool(matching),
            "direction": expected,
            "matching_displacements": matching,
            "latest": matching[-1] if matching else None,
            "reason": (
                "DIRECTIONAL_DISPLACEMENT_CONFIRMED"
                if matching
                else "NO_MATCHING_DISPLACEMENT"
            ),
        }

    @staticmethod
    def _error(
        reason: str,
        **extra: Any,
    ) -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "detected": False,
            "confirmed": False,
            "direction": "NEUTRAL",
            "displacements": [],
            "confirmation": reason,
            **extra,
        }


smc_displacement_engine = SMCDisplacementEngine()
