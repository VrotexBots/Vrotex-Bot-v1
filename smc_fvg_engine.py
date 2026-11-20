
"""
Vrotex Bot V1 - SMC Fair Value Gap Engine

Detects:
- Bullish FVG
- Bearish FVG
- FVG size
- Partial mitigation
- Full mitigation
- Unmitigated FVG zones
- FVG midpoint

Candles must be chronological OHLC dictionaries.

Bullish FVG:
First candle high < third candle low.

Bearish FVG:
First candle low > third candle high.

This module identifies zones only.
It does not authorize trades.
"""

from typing import Dict, List, Optional


class SMCFVGEngine:

    VERSION = "1.0"

    def __init__(self, minimum_gap_size=0.0):
        self.minimum_gap_size = float(minimum_gap_size)

        if self.minimum_gap_size < 0:
            raise ValueError(
                "minimum_gap_size cannot be negative"
            )

        self.total_analyses = 0
        self.last_result = None

    @staticmethod
    def _validate_candles(candles):
        if not isinstance(candles, list):
            raise TypeError("Candles must be a list")

        validated = []

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

            validated.append(item)

        return validated

    def detect_fvgs(self, candles):
        candles = self._validate_candles(candles)

        fvgs = []

        if len(candles) < 3:
            return fvgs

        for index in range(2, len(candles)):

            first = candles[index - 2]
            middle = candles[index - 1]
            third = candles[index]

            bullish_gap = (
                third["low"] - first["high"]
            )

            bearish_gap = (
                first["low"] - third["high"]
            )

            if bullish_gap > self.minimum_gap_size:
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "lower": first["high"],
                    "upper": third["low"],
                    "midpoint": (
                        first["high"] + third["low"]
                    ) / 2,
                    "gap_size": bullish_gap,
                    "formation_index": index,
                    "displacement_candle_index": index - 1,
                    "mitigation": "UNMITIGATED",
                    "filled_percentage": 0.0,
                })

            elif bearish_gap > self.minimum_gap_size:
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "lower": third["high"],
                    "upper": first["low"],
                    "midpoint": (
                        third["high"] + first["low"]
                    ) / 2,
                    "gap_size": bearish_gap,
                    "formation_index": index,
                    "displacement_candle_index": index - 1,
                    "mitigation": "UNMITIGATED",
                    "filled_percentage": 0.0,
                })

        return fvgs

    def update_mitigation(self, fvgs, candles):
        candles = self._validate_candles(candles)

        updated = []

        for fvg in fvgs:
            zone = dict(fvg)

            formation_index = zone["formation_index"]

            lower = float(zone["lower"])
            upper = float(zone["upper"])
            total_size = upper - lower

            if total_size <= 0:
                zone["mitigation"] = "INVALID_ZONE"
                updated.append(zone)
                continue

            touched_depth = 0.0
            fully_filled = False

            for candle in candles[formation_index + 1:]:

                if zone["type"] == "BULLISH_FVG":

                    if candle["low"] <= lower:
                        fully_filled = True
                        touched_depth = total_size
                        break

                    if candle["low"] < upper:
                        touched_depth = max(
                            touched_depth,
                            upper - candle["low"],
                        )

                elif zone["type"] == "BEARISH_FVG":

                    if candle["high"] >= upper:
                        fully_filled = True
                        touched_depth = total_size
                        break

                    if candle["high"] > lower:
                        touched_depth = max(
                            touched_depth,
                            candle["high"] - lower,
                        )

            percentage = min(
                100.0,
                max(
                    0.0,
                    (touched_depth / total_size) * 100,
                ),
            )

            if fully_filled:
                status = "FULLY_MITIGATED"
            elif percentage > 0:
                status = "PARTIALLY_MITIGATED"
            else:
                status = "UNMITIGATED"

            zone["mitigation"] = status
            zone["filled_percentage"] = round(
                percentage,
                2,
            )

            updated.append(zone)

        return updated

    def get_active_fvgs(self, fvgs):
        return [
            dict(fvg)
            for fvg in fvgs
            if fvg.get("mitigation") != "FULLY_MITIGATED"
        ]

    def get_unmitigated_fvgs(self, fvgs):
        return [
            dict(fvg)
            for fvg in fvgs
            if fvg.get("mitigation") == "UNMITIGATED"
        ]

    def find_price_inside_fvg(self, price, fvgs):
        price = float(price)

        matches = []

        for fvg in fvgs:
            if (
                fvg["lower"] <= price <= fvg["upper"]
                and fvg.get("mitigation") != "FULLY_MITIGATED"
            ):
                matches.append(dict(fvg))

        return matches

    def analyze(self, candles):
        candles = self._validate_candles(candles)

        detected = self.detect_fvgs(candles)

        updated = self.update_mitigation(
            detected,
            candles,
        )

        self.total_analyses += 1

        result = {
            "status": (
                "ANALYZED"
                if len(candles) >= 3
                else "INSUFFICIENT_DATA"
            ),
            "version": self.VERSION,
            "total_fvgs": len(updated),
            "bullish_fvgs": [
                fvg for fvg in updated
                if fvg["type"] == "BULLISH_FVG"
            ],
            "bearish_fvgs": [
                fvg for fvg in updated
                if fvg["type"] == "BEARISH_FVG"
            ],
            "unmitigated_fvgs": (
                self.get_unmitigated_fvgs(updated)
            ),
            "active_fvgs": (
                self.get_active_fvgs(updated)
            ),
            "trade_authorized": False,
        }

        self.last_result = result

        return result

    def get_status(self):
        return {
            "component": "SMC_FVG_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "total_analyses": self.total_analyses,
            "minimum_gap_size": self.minimum_gap_size,
        }


smc_fvg_engine = SMCFVGEngine()
