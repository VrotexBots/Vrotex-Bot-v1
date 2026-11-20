"""
Vrotex Bot V1
SMC Displacement Engine

Purpose:
- Detect bullish and bearish displacement candles.
- Measure candle body strength against recent candles.
- Check directional candle closes.
- Identify potential displacement sequences.
- Provide evidence for the M5 confirmation and M1 entry engines.

This module does not execute trades or change approved strategy rules.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class DisplacementResult:
    detected: bool
    direction: Optional[str]
    candle_index: Optional[int]
    open_price: Optional[float]
    close_price: Optional[float]
    body_size: float
    average_body_size: float
    body_strength: float
    candle_range: float
    body_ratio: float
    close_position: float
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SMCDisplacementEngine:
    """
    Detects displacement using candle body strength and closing position.

    Default thresholds are configurable technical parameters, not
    additional entry rules.
    """

    def __init__(
        self,
        lookback: int = 5,
        minimum_body_multiple: float = 1.5,
        minimum_body_ratio: float = 0.60,
        minimum_close_position: float = 0.75,
    ):
        if lookback < 2:
            raise ValueError("lookback must be at least 2")

        if minimum_body_multiple <= 0:
            raise ValueError("minimum_body_multiple must be positive")

        if not 0 < minimum_body_ratio <= 1:
            raise ValueError("minimum_body_ratio must be between 0 and 1")

        if not 0.5 <= minimum_close_position <= 1:
            raise ValueError("minimum_close_position must be between 0.5 and 1")

        self.lookback = lookback
        self.minimum_body_multiple = minimum_body_multiple
        self.minimum_body_ratio = minimum_body_ratio
        self.minimum_close_position = minimum_close_position

    @staticmethod
    def _number(value: Any, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid candle field: {field}")

        if result != result or result in (float("inf"), float("-inf")):
            raise ValueError(f"Non-finite candle field: {field}")

        return result

    def _validate_candle(self, candle: Dict[str, Any]) -> Dict[str, float]:
        if not isinstance(candle, dict):
            raise ValueError("Each candle must be a dictionary")

        required = ("open", "high", "low", "close")
        values = {
            field: self._number(candle.get(field), field)
            for field in required
        }

        if values["high"] < values["low"]:
            raise ValueError("Candle high cannot be below candle low")

        if not (
            values["low"] <= values["open"] <= values["high"]
            and values["low"] <= values["close"] <= values["high"]
        ):
            raise ValueError("Candle prices must be inside its high-low range")

        return values

    @staticmethod
    def _body(candle: Dict[str, float]) -> float:
        return abs(candle["close"] - candle["open"])

    def _direction(self, candle: Dict[str, float]) -> Optional[str]:
        if candle["close"] > candle["open"]:
            return "BULLISH"

        if candle["close"] < candle["open"]:
            return "BEARISH"

        return None

    def _close_position(
        self,
        candle: Dict[str, float],
    ) -> float:
        candle_range = candle["high"] - candle["low"]

        if candle_range == 0:
            return 0.5

        return (
            (candle["close"] - candle["low"])
            / candle_range
        )

    def detect_displacement(
        self,
        candles: List[Dict[str, Any]],
        index: Optional[int] = None,
    ) -> Dict[str, Any]:

        if not isinstance(candles, list):
            raise ValueError("candles must be a list")

        if len(candles) < self.lookback + 1:
            return DisplacementResult(
                detected=False,
                direction=None,
                candle_index=None,
                open_price=None,
                close_price=None,
                body_size=0.0,
                average_body_size=0.0,
                body_strength=0.0,
                candle_range=0.0,
                body_ratio=0.0,
                close_position=0.0,
                reasons=["INSUFFICIENT_CANDLE_HISTORY"],
            ).to_dict()

        if index is None:
            index = len(candles) - 1

        if index < self.lookback or index >= len(candles):
            raise IndexError("Invalid displacement candle index")

        validated = [
            self._validate_candle(candle)
            for candle in candles
        ]

        target = validated[index]
        direction = self._direction(target)

        body_size = self._body(target)
        candle_range = target["high"] - target["low"]

        previous = validated[index - self.lookback:index]

        previous_bodies = [
            self._body(candle)
            for candle in previous
        ]

        average_body = (
            sum(previous_bodies) / len(previous_bodies)
            if previous_bodies else 0.0
        )

        body_strength = (
            body_size / average_body
            if average_body > 0 else 0.0
        )

        body_ratio = (
            body_size / candle_range
            if candle_range > 0 else 0.0
        )

        close_position = self._close_position(target)

        reasons = []

        if direction is None:
            reasons.append("NO_DIRECTIONAL_CANDLE")

        if body_strength < self.minimum_body_multiple:
            reasons.append("BODY_STRENGTH_TOO_WEAK")

        if body_ratio < self.minimum_body_ratio:
            reasons.append("BODY_RATIO_TOO_LOW")

        if direction == "BULLISH":
            if close_position < self.minimum_close_position:
                reasons.append("BULLISH_CLOSE_NOT_STRONG")

        elif direction == "BEARISH":
            if close_position > (1.0 - self.minimum_close_position):
                reasons.append("BEARISH_CLOSE_NOT_STRONG")

        detected = (
            direction is not None
            and body_strength >= self.minimum_body_multiple
            and body_ratio >= self.minimum_body_ratio
            and (
                (
                    direction == "BULLISH"
                    and close_position >= self.minimum_close_position
                )
                or (
                    direction == "BEARISH"
                    and close_position <= (
                        1.0 - self.minimum_close_position
                    )
                )
            )
        )

        if detected:
            reasons.append("DISPLACEMENT_CONFIRMED")

        return DisplacementResult(
            detected=detected,
            direction=direction,
            candle_index=index,
            open_price=target["open"],
            close_price=target["close"],
            body_size=body_size,
            average_body_size=average_body,
            body_strength=body_strength,
            candle_range=candle_range,
            body_ratio=body_ratio,
            close_position=close_position,
            reasons=reasons,
        ).to_dict()

    def detect_sequence(
        self,
        candles: List[Dict[str, Any]],
        start_index: Optional[int] = None,
        end_index: Optional[int] = None,
    ) -> Dict[str, Any]:

        if not isinstance(candles, list):
            raise ValueError("candles must be a list")

        if not candles:
            return {
                "detected": False,
                "direction": None,
                "results": [],
                "reason": "NO_CANDLES",
            }

        if start_index is None:
            start_index = self.lookback

        if end_index is None:
            end_index = len(candles) - 1

        if start_index < self.lookback:
            raise ValueError("start_index does not contain enough history")

        if end_index >= len(candles) or start_index > end_index:
            raise ValueError("Invalid sequence index range")

        results = []

        for candle_index in range(start_index, end_index + 1):
            result = self.detect_displacement(
                candles,
                candle_index,
            )

            if result["detected"]:
                results.append(result)

        directions = {
            result["direction"]
            for result in results
        }

        direction = (
            next(iter(directions))
            if len(directions) == 1
            else None
        )

        return {
            "detected": bool(results),
            "direction": direction,
            "mixed_directions": len(directions) > 1,
            "displacement_count": len(results),
            "results": results,
        }

    def validate_direction(
        self,
        candles: List[Dict[str, Any]],
        expected_direction: str,
        index: Optional[int] = None,
    ) -> Dict[str, Any]:

        expected_direction = expected_direction.upper()

        if expected_direction not in ("BULLISH", "BEARISH"):
            raise ValueError(
                "expected_direction must be BULLISH or BEARISH"
            )

        result = self.detect_displacement(candles, index)

        direction_matches = (
            result["direction"] == expected_direction
        )

        return {
            "valid": result["detected"] and direction_matches,
            "expected_direction": expected_direction,
            "detected_direction": result["direction"],
            "direction_matches": direction_matches,
            "displacement": result,
        }


# Shared engine instance
smc_displacement_engine = SMCDisplacementEngine()


def detect_displacement(
    candles: List[Dict[str, Any]],
    index: Optional[int] = None,
) -> Dict[str, Any]:
    return smc_displacement_engine.detect_displacement(
        candles,
        index,
    )


def detect_displacement_sequence(
    candles: List[Dict[str, Any]],
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
) -> Dict[str, Any]:
    return smc_displacement_engine.detect_sequence(
        candles,
        start_index,
        end_index,
    )
