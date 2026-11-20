
"""
Vrotex Bot V1 - SMC Order Block Engine

Detects potential:
- Bullish order blocks
- Bearish order blocks
- Displacement after opposing candles
- Structural-break confirmation
- Partial mitigation
- Full mitigation
- Invalidated order blocks

An opposing candle alone is NOT a confirmed order block.

A valid candidate requires:
1. An opposing candle.
2. Subsequent directional displacement.
3. A confirmed structural break.
4. A zone that has not been invalidated.

This module identifies candidates only.
It does not authorize trades.
"""

from typing import Dict, List, Optional


class SMCOrderBlockEngine:

    VERSION = "1.0"

    def __init__(
        self,
        lookback=20,
        minimum_displacement_ratio=1.5,
    ):
        if lookback < 2:
            raise ValueError("lookback must be at least 2")

        if minimum_displacement_ratio <= 0:
            raise ValueError(
                "minimum_displacement_ratio must be positive"
            )

        self.lookback = lookback
        self.minimum_displacement_ratio = (
            float(minimum_displacement_ratio)
        )

        self.total_analyses = 0
        self.last_result = None

    @staticmethod
    def _validate_candles(candles):
        if not isinstance(candles, list):
            raise TypeError("Candles must be a list")

        result = []

        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                raise ValueError(
                    f"Candle {index} must be a dictionary"
                )

            item = {}

            for field in ("open", "high", "low", "close"):
                try:
                    item[field] = float(candle[field])
                except (KeyError, TypeError, ValueError):
                    raise ValueError(
                        f"Candle {index} has invalid {field}"
                    )

            if item["high"] < max(
                item["open"],
                item["close"],
                item["low"],
            ):
                raise ValueError(
                    f"Candle {index} has invalid high"
                )

            if item["low"] > min(
                item["open"],
                item["close"],
                item["high"],
            ):
                raise ValueError(
                    f"Candle {index} has invalid low"
                )

            result.append(item)

        return result

    @staticmethod
    def _body_size(candle):
        return abs(candle["close"] - candle["open"])

    @staticmethod
    def _average_body(candles):
        if not candles:
            return 0.0

        return sum(
            abs(candle["close"] - candle["open"])
            for candle in candles
        ) / len(candles)

    def _has_bullish_displacement(
        self,
        candles,
        index,
    ):
        current = candles[index]

        previous = candles[
            max(0, index - 5):index
        ]

        average = self._average_body(previous)

        if average <= 0:
            return False

        return (
            current["close"] > current["open"]
            and self._body_size(current)
            >= average * self.minimum_displacement_ratio
        )

    def _has_bearish_displacement(
        self,
        candles,
        index,
    ):
        current = candles[index]

        previous = candles[
            max(0, index - 5):index
        ]

        average = self._average_body(previous)

        if average <= 0:
            return False

        return (
            current["close"] < current["open"]
            and self._body_size(current)
            >= average * self.minimum_displacement_ratio
        )

    @staticmethod
    def _confirmed_bullish_break(
        candle,
        structural_high,
    ):
        return (
            structural_high is not None
            and candle["close"] > structural_high
        )

    @staticmethod
    def _confirmed_bearish_break(
        candle,
        structural_low,
    ):
        return (
            structural_low is not None
            and candle["close"] < structural_low
        )

    def detect_order_blocks(
        self,
        candles,
        structural_high=None,
        structural_low=None,
    ):
        candles = self._validate_candles(candles)

        blocks = []

        if len(candles) < 7:
            return blocks

        start = max(1, len(candles) - self.lookback)

        for index in range(start, len(candles)):

            candle = candles[index]

            previous_candle = candles[index - 1]

            # Bullish candidate:
            # Final bearish candle before bullish displacement.

            if (
                previous_candle["close"]
                < previous_candle["open"]
            ):

                if (
                    self._has_bullish_displacement(
                        candles,
                        index,
                    )
                    and self._confirmed_bullish_break(
                        candle,
                        structural_high,
                    )
                ):
                    blocks.append({
                        "type": "BULLISH_ORDER_BLOCK",
                        "lower": previous_candle["low"],
                        "upper": previous_candle["high"],
                        "formation_index": index,
                        "source_candle_index": index - 1,
                        "displacement_confirmed": True,
                        "structure_break_confirmed": True,
                        "mitigation": "UNMITIGATED",
                        "invalidation": "NOT_INVALIDATED",
                    })

            # Bearish candidate:
            # Final bullish candle before bearish displacement.

            if (
                previous_candle["close"]
                > previous_candle["open"]
            ):

                if (
                    self._has_bearish_displacement(
                        candles,
                        index,
                    )
                    and self._confirmed_bearish_break(
                        candle,
                        structural_low,
                    )
                ):
                    blocks.append({
                        "type": "BEARISH_ORDER_BLOCK",
                        "lower": previous_candle["low"],
                        "upper": previous_candle["high"],
                        "formation_index": index,
                        "source_candle_index": index - 1,
                        "displacement_confirmed": True,
                        "structure_break_confirmed": True,
                        "mitigation": "UNMITIGATED",
                        "invalidation": "NOT_INVALIDATED",
                    })

        return blocks

    def update_block_states(
        self,
        blocks,
        candles,
    ):
        candles = self._validate_candles(candles)

        updated = []

        for block in blocks:

            item = dict(block)

            lower = float(item["lower"])
            upper = float(item["upper"])

            if lower >= upper:
                item["invalidation"] = "INVALID_ZONE"
                updated.append(item)
                continue

            start_index = (
                item["formation_index"] + 1
            )

            invalidated = False
            touched = False

            for candle in candles[start_index:]:

                if item["type"] == "BULLISH_ORDER_BLOCK":

                    if candle["close"] < lower:
                        invalidated = True
                        break

                    if (
                        candle["low"] <= upper
                        and candle["high"] >= lower
                    ):
                        touched = True

                elif item["type"] == "BEARISH_ORDER_BLOCK":

                    if candle["close"] > upper:
                        invalidated = True
                        break

                    if (
                        candle["high"] >= lower
                        and candle["low"] <= upper
                    ):
                        touched = True

            if invalidated:
                item["invalidation"] = "INVALIDATED"
                item["mitigation"] = "INVALIDATED"

            elif touched:
                item["mitigation"] = "MITIGATED"

            else:
                item["mitigation"] = "UNMITIGATED"

            updated.append(item)

        return updated

    def get_valid_blocks(self, blocks):
        return [
            dict(block)
            for block in blocks
            if (
                block.get("invalidation")
                == "NOT_INVALIDATED"
                and block.get("mitigation")
                == "UNMITIGATED"
            )
        ]

    def analyze(
        self,
        candles,
        structural_high=None,
        structural_low=None,
    ):
        candles = self._validate_candles(candles)

        detected = self.detect_order_blocks(
            candles,
            structural_high=structural_high,
            structural_low=structural_low,
        )

        updated = self.update_block_states(
            detected,
            candles,
        )

        self.total_analyses += 1

        result = {
            "status": (
                "ANALYZED"
                if len(candles) >= 7
                else "INSUFFICIENT_DATA"
            ),
            "version": self.VERSION,
            "total_candidates": len(updated),
            "bullish_blocks": [
                block for block in updated
                if block["type"] == "BULLISH_ORDER_BLOCK"
            ],
            "bearish_blocks": [
                block for block in updated
                if block["type"] == "BEARISH_ORDER_BLOCK"
            ],
            "valid_unmitigated_blocks": (
                self.get_valid_blocks(updated)
            ),
            "trade_authorized": False,
        }

        self.last_result = result

        return result

    def get_status(self):
        return {
            "component": "SMC_ORDER_BLOCK_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "lookback": self.lookback,
            "minimum_displacement_ratio": (
                self.minimum_displacement_ratio
            ),
            "total_analyses": self.total_analyses,
        }


smc_order_block_engine = SMCOrderBlockEngine()
