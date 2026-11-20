
"""
VROTEX BOT V1
SMC Fair Value Gap Engine
Version 2.0

Detects:
- Bullish Fair Value Gaps
- Bearish Fair Value Gaps
- FVG boundaries and midpoint
- Mitigation status
- Full and partial mitigation
- Directional FVG validation

Three-candle FVG:
Bullish: candle 3 low > candle 1 high
Bearish: candle 3 high < candle 1 low

This module does not execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCFVGEngine:

    VERSION = "2.0"

    def __init__(
        self,
        minimum_gap: float = 0.0,
        mitigation_tolerance: float = 0.0
    ):
        self.minimum_gap = max(0.0, float(minimum_gap))
        self.mitigation_tolerance = max(
            0.0, float(mitigation_tolerance)
        )

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result:
                return None
            return result
        except (TypeError, ValueError):
            return None

    def _validate_candles(
        self,
        candles: Any
    ) -> List[Dict[str, float]]:

        if not isinstance(candles, list):
            return []

        validated = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            open_price = self._number(candle.get("open"))
            high = self._number(candle.get("high"))
            low = self._number(candle.get("low"))
            close = self._number(candle.get("close"))

            if None in (
                open_price, high, low, close
            ):
                continue

            if high < low:
                continue

            if not (
                low <= open_price <= high
                and low <= close <= high
            ):
                continue

            validated.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close
            })

        return validated

    # ---------------------------------------------------------
    # FVG DETECTION
    # ---------------------------------------------------------

    def _detect_fvgs(
        self,
        candles: List[Dict[str, float]]
    ) -> List[Dict[str, Any]]:

        fvgs = []

        for index in range(2, len(candles)):

            first = candles[index - 2]
            middle = candles[index - 1]
            third = candles[index]

            # Bullish FVG:
            # The third candle's low is above the first
            # candle's high.
            bullish_lower = first["high"]
            bullish_upper = third["low"]

            bullish_gap = bullish_upper - bullish_lower

            if bullish_gap > self.minimum_gap:

                fvgs.append({
                    "id": f"BULLISH_FVG_{index}",
                    "type": "BULLISH_FVG",
                    "direction": "BUY",
                    "lower": bullish_lower,
                    "upper": bullish_upper,
                    "midpoint": (
                        bullish_lower + bullish_upper
                    ) / 2.0,
                    "gap_size": bullish_gap,
                    "formation_index": index,
                    "first_candle_index": index - 2,
                    "middle_candle_index": index - 1,
                    "third_candle_index": index,
                    "formation_confirmed": True
                })

            # Bearish FVG:
            # The third candle's high is below the first
            # candle's low.
            bearish_lower = third["high"]
            bearish_upper = first["low"]

            bearish_gap = bearish_upper - bearish_lower

            if bearish_gap > self.minimum_gap:

                fvgs.append({
                    "id": f"BEARISH_FVG_{index}",
                    "type": "BEARISH_FVG",
                    "direction": "SELL",
                    "lower": bearish_lower,
                    "upper": bearish_upper,
                    "midpoint": (
                        bearish_lower + bearish_upper
                    ) / 2.0,
                    "gap_size": bearish_gap,
                    "formation_index": index,
                    "first_candle_index": index - 2,
                    "middle_candle_index": index - 1,
                    "third_candle_index": index,
                    "formation_confirmed": True
                })

        return fvgs

    # ---------------------------------------------------------
    # MITIGATION ANALYSIS
    # ---------------------------------------------------------

    def _check_mitigation(
        self,
        fvg: Dict[str, Any],
        candles: List[Dict[str, float]]
    ) -> Dict[str, Any]:

        formation_index = fvg["formation_index"]

        lower = fvg["lower"]
        upper = fvg["upper"]
        midpoint = fvg["midpoint"]

        direction = fvg["direction"]

        touched = False
        midpoint_reached = False
        fully_mitigated = False

        mitigation_index = None
        deepest_price = None

        for index in range(
            formation_index + 1,
            len(candles)
        ):

            candle = candles[index]

            if direction == "BUY":

                # Bullish FVG mitigation occurs when price
                # retraces down into the gap.
                if candle["low"] < upper:
                    touched = True
                    mitigation_index = index

                    deepest_price = candle["low"]

                    if candle["low"] <= midpoint:
                        midpoint_reached = True

                    if (
                        candle["low"]
                        <= lower + self.mitigation_tolerance
                    ):
                        fully_mitigated = True
                        break

            else:

                # Bearish FVG mitigation occurs when price
                # retraces up into the gap.
                if candle["high"] > lower:
                    touched = True
                    mitigation_index = index

                    deepest_price = candle["high"]

                    if candle["high"] >= midpoint:
                        midpoint_reached = True

                    if (
                        candle["high"]
                        >= upper - self.mitigation_tolerance
                    ):
                        fully_mitigated = True
                        break

        if fully_mitigated:
            status = "FULLY_MITIGATED"

        elif midpoint_reached:
            status = "MIDPOINT_MITIGATED"

        elif touched:
            status = "PARTIALLY_MITIGATED"

        else:
            status = "UNMITIGATED"

        return {
            "mitigated": touched,
            "partially_mitigated": (
                touched and not fully_mitigated
            ),
            "midpoint_reached": midpoint_reached,
            "fully_mitigated": fully_mitigated,
            "status": status,
            "mitigation_index": mitigation_index,
            "deepest_price": deepest_price
        }

    # ---------------------------------------------------------
    # APPLY MITIGATION STATUS
    # ---------------------------------------------------------

    def _enrich_fvgs(
        self,
        fvgs: List[Dict[str, Any]],
        candles: List[Dict[str, float]]
    ) -> List[Dict[str, Any]]:

        enriched = []

        for original in fvgs:

            fvg = dict(original)

            mitigation = self._check_mitigation(
                fvg, candles
            )

            fvg.update(mitigation)

            fvg["clean"] = (
                not fvg["mitigated"]
                and not fvg["fully_mitigated"]
            )

            fvg["unmitigated"] = (
                not fvg["mitigated"]
            )

            enriched.append(fvg)

        return enriched

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Any,
        current_price: Optional[float] = None
    ) -> Dict[str, Any]:

        validated = self._validate_candles(candles)

        if len(validated) < 3:
            result = {
                "status": "INSUFFICIENT_DATA",
                "version": self.VERSION,
                "fvg_count": 0,
                "fvgs": [],
                "clean_fvgs": [],
                "bullish_fvgs": [],
                "bearish_fvgs": []
            }

            self.last_result = result
            return result

        if current_price is None:
            current_price = validated[-1]["close"]

        current_price = self._number(current_price)

        if current_price is None or current_price <= 0:
            result = {
                "status": "INVALID_CURRENT_PRICE",
                "version": self.VERSION,
                "fvg_count": 0,
                "fvgs": []
            }

            self.last_result = result
            return result

        detected = self._detect_fvgs(validated)

        enriched = self._enrich_fvgs(
            detected,
            validated
        )

        clean_fvgs = [
            fvg for fvg in enriched
            if fvg["clean"]
        ]

        bullish = [
            fvg for fvg in enriched
            if fvg["direction"] == "BUY"
        ]

        bearish = [
            fvg for fvg in enriched
            if fvg["direction"] == "SELL"
        ]

        clean_bullish = [
            fvg for fvg in clean_fvgs
            if fvg["direction"] == "BUY"
        ]

        clean_bearish = [
            fvg for fvg in clean_fvgs
            if fvg["direction"] == "SELL"
        ]

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "candle_count": len(validated),
            "current_price": current_price,

            "fvg_count": len(enriched),
            "clean_fvg_count": len(clean_fvgs),

            "fvgs": enriched,
            "clean_fvgs": clean_fvgs,

            "bullish_fvgs": bullish,
            "bearish_fvgs": bearish,

            "clean_bullish_fvgs": clean_bullish,
            "clean_bearish_fvgs": clean_bearish
        }

        self.last_result = result
        return result

    # British spelling compatibility
    def analyse(
        self,
        candles: Any,
        current_price: Optional[float] = None
    ) -> Dict[str, Any]:

        return self.analyze(candles, current_price)

    # ---------------------------------------------------------
    # DIRECTIONAL FVG VALIDATION
    # ---------------------------------------------------------

    def validate_directional_fvg(
        self,
        analysis: Dict[str, Any],
        trade_direction: str
    ) -> Dict[str, Any]:

        direction = str(
            trade_direction
        ).strip().upper()

        if direction in {"BUY", "BULLISH", "LONG"}:
            expected = "BUY"

        elif direction in {"SELL", "BEARISH", "SHORT"}:
            expected = "SELL"

        else:
            return {
                "valid": False,
                "reason": "INVALID_TRADE_DIRECTION",
                "matching_fvgs": []
            }

        clean_fvgs = analysis.get(
            "clean_fvgs", []
        )

        matching = [
            fvg for fvg in clean_fvgs
            if (
                isinstance(fvg, dict)
                and fvg.get("direction") == expected
                and fvg.get("clean") is True
                and fvg.get("unmitigated") is True
            )
        ]

        return {
            "valid": bool(matching),
            "trade_direction": direction,
            "matching_fvgs": matching,
            "count": len(matching)
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "SMC_FVG_ENGINE",
            "version": self.VERSION,
            "status": "ACTIVE"
        }


smc_fvg_engine = SMCFVGEngine()
