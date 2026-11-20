
"""
Vrotex Bot V1 - SMC Structure Engine

Detects:
- Swing highs and lows
- Higher highs and higher lows
- Lower highs and lower lows
- BOS and CHoCH
- Liquidity sweeps
- Equal highs and equal lows

BOS and CHoCH require a candle BODY CLOSE
beyond the relevant structural level.

A wick alone is never treated as a confirmed break.

Input candles must be chronological OHLC dictionaries:
{
    "open": 1.1000,
    "high": 1.1020,
    "low": 1.0990,
    "close": 1.1010
}
"""

from typing import Any, Dict, List, Optional


class SMCStructureEngine:

    VERSION = "1.0"

    def __init__(
        self,
        swing_strength: int = 3,
        equal_level_tolerance: float = 0.0001,
    ):
        if swing_strength < 1:
            raise ValueError("swing_strength must be at least 1")

        if equal_level_tolerance < 0:
            raise ValueError(
                "equal_level_tolerance cannot be negative"
            )

        self.swing_strength = swing_strength
        self.equal_level_tolerance = equal_level_tolerance

    def _validate_candles(self, candles):
        if not isinstance(candles, list):
            raise TypeError("Candles must be a list")

        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                raise ValueError(
                    f"Candle {index} must be a dictionary"
                )

            for field in ("open", "high", "low", "close"):
                if field not in candle:
                    raise ValueError(
                        f"Candle {index} is missing {field}"
                    )

                try:
                    candle[field] = float(candle[field])
                except (TypeError, ValueError):
                    raise ValueError(
                        f"Candle {index} has invalid {field}"
                    )

            if candle["high"] < max(
                candle["open"], candle["close"], candle["low"]
            ):
                raise ValueError(
                    f"Candle {index} has an invalid high"
                )

            if candle["low"] > min(
                candle["open"], candle["close"], candle["high"]
            ):
                raise ValueError(
                    f"Candle {index} has an invalid low"
                )

    def detect_swings(self, candles):
        self._validate_candles(candles)

        strength = self.swing_strength
        swings = []

        if len(candles) < (strength * 2 + 1):
            return swings

        for index in range(
            strength,
            len(candles) - strength
        ):
            current = candles[index]

            left = candles[index - strength:index]
            right = candles[index + 1:index + strength + 1]

            swing_high = all(
                current["high"] > candle["high"]
                for candle in left + right
            )

            swing_low = all(
                current["low"] < candle["low"]
                for candle in left + right
            )

            if swing_high:
                swings.append({
                    "index": index,
                    "type": "HIGH",
                    "price": current["high"],
                })

            if swing_low:
                swings.append({
                    "index": index,
                    "type": "LOW",
                    "price": current["low"],
                })

        return sorted(
            swings,
            key=lambda item: item["index"]
        )

    def classify_structure(self, swings):
        highs = [
            item for item in swings
            if item["type"] == "HIGH"
        ]

        lows = [
            item for item in swings
            if item["type"] == "LOW"
        ]

        high_classification = []
        low_classification = []

        for previous, current in zip(highs, highs[1:]):
            label = (
                "HH"
                if current["price"] > previous["price"]
                else "LH"
                if current["price"] < previous["price"]
                else "EQH"
            )

            high_classification.append({
                "index": current["index"],
                "price": current["price"],
                "classification": label,
            })

        for previous, current in zip(lows, lows[1:]):
            label = (
                "HL"
                if current["price"] > previous["price"]
                else "LL"
                if current["price"] < previous["price"]
                else "EQL"
            )

            low_classification.append({
                "index": current["index"],
                "price": current["price"],
                "classification": label,
            })

        recent_highs = [
            item["classification"]
            for item in high_classification[-2:]
        ]

        recent_lows = [
            item["classification"]
            for item in low_classification[-2:]
        ]

        if (
            len(recent_highs) == 2
            and len(recent_lows) == 2
            and all(label == "HH" for label in recent_highs)
            and all(label == "HL" for label in recent_lows)
        ):
            bias = "BULLISH"

        elif (
            len(recent_highs) == 2
            and len(recent_lows) == 2
            and all(label == "LH" for label in recent_highs)
            and all(label == "LL" for label in recent_lows)
        ):
            bias = "BEARISH"

        else:
            bias = "NEUTRAL"

        return {
            "bias": bias,
            "highs": high_classification,
            "lows": low_classification,
        }

    def detect_structure_breaks(
        self,
        candles,
        swings,
        previous_bias="NEUTRAL",
    ):
        self._validate_candles(candles)

        if not candles:
            return []

        last_index = len(candles) - 1
        last_candle = candles[last_index]

        previous_highs = [
            swing for swing in swings
            if swing["type"] == "HIGH"
            and swing["index"] < last_index
        ]

        previous_lows = [
            swing for swing in swings
            if swing["type"] == "LOW"
            and swing["index"] < last_index
        ]

        breaks = []

        if previous_highs:
            level = previous_highs[-1]

            if last_candle["close"] > level["price"]:
                event = (
                    "BOS"
                    if previous_bias == "BULLISH"
                    else "CHOCH"
                    if previous_bias == "BEARISH"
                    else "BULLISH_BREAK"
                )

                breaks.append({
                    "type": event,
                    "direction": "BULLISH",
                    "level": level["price"],
                    "candle_index": last_index,
                    "confirmation": "BODY_CLOSE",
                })

        if previous_lows:
            level = previous_lows[-1]

            if last_candle["close"] < level["price"]:
                event = (
                    "BOS"
                    if previous_bias == "BEARISH"
                    else "CHOCH"
                    if previous_bias == "BULLISH"
                    else "BEARISH_BREAK"
                )

                breaks.append({
                    "type": event,
                    "direction": "BEARISH",
                    "level": level["price"],
                    "candle_index": last_index,
                    "confirmation": "BODY_CLOSE",
                })

        return breaks

    def detect_liquidity_sweeps(self, candles, swings):
        self._validate_candles(candles)

        if not candles:
            return []

        index = len(candles) - 1
        candle = candles[index]
        sweeps = []

        for swing in swings:
            if swing["index"] >= index:
                continue

            level = swing["price"]

            if swing["type"] == "HIGH":
                if (
                    candle["high"] > level
                    and candle["close"] < level
                ):
                    sweeps.append({
                        "type": "BUY_SIDE_SWEEP",
                        "level": level,
                        "candle_index": index,
                        "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
                    })

            elif swing["type"] == "LOW":
                if (
                    candle["low"] < level
                    and candle["close"] > level
                ):
                    sweeps.append({
                        "type": "SELL_SIDE_SWEEP",
                        "level": level,
                        "candle_index": index,
                        "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
                    })

        return sweeps

    def detect_equal_levels(self, swings):
        highs = [
            item for item in swings
            if item["type"] == "HIGH"
        ]

        lows = [
            item for item in swings
            if item["type"] == "LOW"
        ]

        equal_highs = []
        equal_lows = []

        for index, first in enumerate(highs):
            for second in highs[index + 1:]:
                difference = abs(
                    first["price"] - second["price"]
                )

                if difference <= self.equal_level_tolerance:
                    equal_highs.append({
                        "type": "EQUAL_HIGHS",
                        "first_index": first["index"],
                        "second_index": second["index"],
                        "level": (
                            first["price"] + second["price"]
                        ) / 2,
                    })

        for index, first in enumerate(lows):
            for second in lows[index + 1:]:
                difference = abs(
                    first["price"] - second["price"]
                )

                if difference <= self.equal_level_tolerance:
                    equal_lows.append({
                        "type": "EQUAL_LOWS",
                        "first_index": first["index"],
                        "second_index": second["index"],
                        "level": (
                            first["price"] + second["price"]
                        ) / 2,
                    })

        return {
            "equal_highs": equal_highs,
            "equal_lows": equal_lows,
        }

    def analyze(self, candles, previous_bias="NEUTRAL"):
        self._validate_candles(candles)

        swings = self.detect_swings(candles)

        structure = self.classify_structure(swings)

        breaks = self.detect_structure_breaks(
            candles,
            swings,
            previous_bias=previous_bias,
        )

        sweeps = self.detect_liquidity_sweeps(
            candles,
            swings,
        )

        equal_levels = self.detect_equal_levels(swings)

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "swing_count": len(swings),
            "swings": swings,
            "structure": structure,
            "breaks": breaks,
            "liquidity_sweeps": sweeps,
            "equal_levels": equal_levels,
            "previous_bias": previous_bias,
        }

    def get_status(self):
        return {
            "component": "SMC_STRUCTURE_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "swing_strength": self.swing_strength,
            "equal_level_tolerance": self.equal_level_tolerance,
        }


smc_structure_engine = SMCStructureEngine()
