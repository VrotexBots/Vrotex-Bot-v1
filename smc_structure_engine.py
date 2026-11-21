
"""
VROTEX BOT V1
SMC STRUCTURE ENGINE
Version 2.0

Responsibilities:
- Detect external and internal market structure independently.
- Identify HH, HL, LH and LL.
- Confirm BOS and CHoCH using candle BODY CLOSE.
- Track protected highs and lows.
- Identify liquidity sweeps without treating wicks as breaks.
- Identify equal highs and equal lows.
- Identify potential ranging conditions.
- Return structured evidence for the master SMC engine.

IMPORTANT:
- External and internal biases are independent.
- An internal reversal does not automatically reverse external bias.
- A wick through a structural level is never a confirmed break.
- A break is confirmed only by a candle close beyond the level.
- This module does not authorize trade execution.
"""

from typing import Any, Dict, List, Optional
from copy import deepcopy
import math


class SMCStructureEngine:

    VERSION = "2.0"

    def __init__(
        self,
        external_swing_strength: int = 3,
        internal_swing_strength: int = 1,
        equal_level_tolerance: float = 0.0001,
        range_minimum_swings: int = 2,
    ):
        if external_swing_strength < 1:
            raise ValueError(
                "external_swing_strength must be at least 1"
            )

        if internal_swing_strength < 1:
            raise ValueError(
                "internal_swing_strength must be at least 1"
            )

        if equal_level_tolerance < 0:
            raise ValueError(
                "equal_level_tolerance cannot be negative"
            )

        self.external_swing_strength = int(
            external_swing_strength
        )

        self.internal_swing_strength = int(
            internal_swing_strength
        )

        self.equal_level_tolerance = float(
            equal_level_tolerance
        )

        self.range_minimum_swings = max(
            2, int(range_minimum_swings)
        )

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # SAFE INPUT NORMALISATION
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:

        try:
            number = float(value)

            if not math.isfinite(number):
                return None

            return number

        except (TypeError, ValueError):
            return None

    def _validate_candles(
        self,
        candles: Any,
    ) -> List[Dict[str, Any]]:

        if not isinstance(candles, list):
            raise TypeError(
                "Candles must be a list"
            )

        validated = []

        for index, original in enumerate(candles):

            if not isinstance(original, dict):
                raise ValueError(
                    f"Candle {index} must be a dictionary"
                )

            candle = dict(original)

            open_price = self._number(
                candle.get("open", candle.get("OPEN"))
            )

            high = self._number(
                candle.get("high", candle.get("HIGH"))
            )

            low = self._number(
                candle.get("low", candle.get("LOW"))
            )

            close = self._number(
                candle.get("close", candle.get("CLOSE"))
            )

            if None in (
                open_price,
                high,
                low,
                close,
            ):
                raise ValueError(
                    f"Candle {index} contains invalid OHLC values"
                )

            if high < low:
                raise ValueError(
                    f"Candle {index} has high below low"
                )

            if high < max(open_price, close):
                raise ValueError(
                    f"Candle {index} has invalid high"
                )

            if low > min(open_price, close):
                raise ValueError(
                    f"Candle {index} has invalid low"
                )

            normalized = {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            }

            timestamp = (
                candle.get("timestamp")
                or candle.get("time")
                or candle.get("datetime")
            )

            if timestamp is not None:
                normalized["timestamp"] = timestamp

            normalized["_source_index"] = index

            validated.append(normalized)

        return validated

    # ---------------------------------------------------------
    # SWING DETECTION
    # ---------------------------------------------------------

    def detect_swings(
        self,
        candles: List[Dict[str, Any]],
        strength: Optional[int] = None,
    ) -> List[Dict[str, Any]]:

        strength = max(
            1,
            int(
                strength
                if strength is not None
                else self.external_swing_strength
            ),
        )

        swings = []

        if len(candles) < strength * 2 + 1:
            return swings

        for index in range(
            strength,
            len(candles) - strength,
        ):

            current = candles[index]

            left = candles[
                index - strength:index
            ]

            right = candles[
                index + 1:index + strength + 1
            ]

            swing_high = all(
                current["high"] > item["high"]
                for item in left + right
            )

            swing_low = all(
                current["low"] < item["low"]
                for item in left + right
            )

            if swing_high:

                event = {
                    "index": index,
                    "type": "HIGH",
                    "price": current["high"],
                }

                if "timestamp" in current:
                    event["timestamp"] = current["timestamp"]

                swings.append(event)

            if swing_low:

                event = {
                    "index": index,
                    "type": "LOW",
                    "price": current["low"],
                }

                if "timestamp" in current:
                    event["timestamp"] = current["timestamp"]

                swings.append(event)

        return sorted(
            swings,
            key=lambda item: item["index"],
        )

    # ---------------------------------------------------------
    # STRUCTURE CLASSIFICATION
    # ---------------------------------------------------------

    def classify_structure(
        self,
        swings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        highs = [
            item for item in swings
            if item["type"] == "HIGH"
        ]

        lows = [
            item for item in swings
            if item["type"] == "LOW"
        ]

        classified_highs = []
        classified_lows = []

        for previous, current in zip(
            highs,
            highs[1:],
        ):

            if current["price"] > previous["price"]:
                label = "HH"

            elif current["price"] < previous["price"]:
                label = "LH"

            else:
                label = "EQH"

            classified_highs.append({
                **current,
                "classification": label,
            })

        for previous, current in zip(
            lows,
            lows[1:],
        ):

            if current["price"] > previous["price"]:
                label = "HL"

            elif current["price"] < previous["price"]:
                label = "LL"

            else:
                label = "EQL"

            classified_lows.append({
                **current,
                "classification": label,
            })

        recent_highs = [
            item["classification"]
            for item in classified_highs[-2:]
        ]

        recent_lows = [
            item["classification"]
            for item in classified_lows[-2:]
        ]

        if (
            len(recent_highs) == 2
            and len(recent_lows) == 2
            and all(item == "HH" for item in recent_highs)
            and all(item == "HL" for item in recent_lows)
        ):

            bias = "BULLISH"

        elif (
            len(recent_highs) == 2
            and len(recent_lows) == 2
            and all(item == "LH" for item in recent_highs)
            and all(item == "LL" for item in recent_lows)
        ):

            bias = "BEARISH"

        else:
            bias = "NEUTRAL"

        return {
            "bias": bias,
            "highs": classified_highs,
            "lows": classified_lows,
            "swing_highs": highs,
            "swing_lows": lows,
        }

    # ---------------------------------------------------------
    # CHRONOLOGICAL BOS / CHOCH DETECTION
    # ---------------------------------------------------------

    def detect_structure_breaks(
        self,
        candles: List[Dict[str, Any]],
        swings: List[Dict[str, Any]],
        previous_bias: str = "NEUTRAL",
    ) -> List[Dict[str, Any]]:

        previous_bias = str(
            previous_bias or "NEUTRAL"
        ).upper()

        if previous_bias not in (
            "BULLISH",
            "BEARISH",
            "NEUTRAL",
        ):
            previous_bias = "NEUTRAL"

        breaks = []

        for candle_index, candle in enumerate(candles):

            previous_highs = [
                swing for swing in swings
                if (
                    swing["type"] == "HIGH"
                    and swing["index"] < candle_index
                )
            ]

            previous_lows = [
                swing for swing in swings
                if (
                    swing["type"] == "LOW"
                    and swing["index"] < candle_index
                )
            ]

            if previous_highs:

                level = previous_highs[-1]

                if candle["close"] > level["price"]:

                    event_type = (
                        "BOS"
                        if previous_bias == "BULLISH"
                        else "CHOCH"
                        if previous_bias == "BEARISH"
                        else "BULLISH_BREAK"
                    )

                    event = {
                        "type": event_type,
                        "direction": "BULLISH",
                        "level": level["price"],
                        "swing_index": level["index"],
                        "candle_index": candle_index,
                        "confirmation": "BODY_CLOSE",
                        "body_close_confirmed": True,
                    }

                    if "timestamp" in candle:
                        event["timestamp"] = candle["timestamp"]

                    breaks.append(event)

                    previous_bias = "BULLISH"

            if previous_lows:

                level = previous_lows[-1]

                if candle["close"] < level["price"]:

                    event_type = (
                        "BOS"
                        if previous_bias == "BEARISH"
                        else "CHOCH"
                        if previous_bias == "BULLISH"
                        else "BEARISH_BREAK"
                    )

                    event = {
                        "type": event_type,
                        "direction": "BEARISH",
                        "level": level["price"],
                        "swing_index": level["index"],
                        "candle_index": candle_index,
                        "confirmation": "BODY_CLOSE",
                        "body_close_confirmed": True,
                    }

                    if "timestamp" in candle:
                        event["timestamp"] = candle["timestamp"]

                    breaks.append(event)

                    previous_bias = "BEARISH"

        return breaks

    # ---------------------------------------------------------
    # PROTECTED STRUCTURAL LEVELS
    # ---------------------------------------------------------

    @staticmethod
    def identify_protected_levels(
        structure: Dict[str, Any],
        breaks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        bias = structure.get(
            "bias",
            "NEUTRAL",
        )

        bullish_breaks = [
            event for event in breaks
            if event.get("direction") == "BULLISH"
        ]

        bearish_breaks = [
            event for event in breaks
            if event.get("direction") == "BEARISH"
        ]

        protected_high = None
        protected_low = None

        if bias == "BULLISH" and bullish_breaks:

            event = bullish_breaks[-1]

            candidates = [
                item for item in structure.get(
                    "swing_lows", []
                )
                if item["index"] < event["candle_index"]
            ]

            if candidates:
                protected_low = candidates[-1]

        elif bias == "BEARISH" and bearish_breaks:

            event = bearish_breaks[-1]

            candidates = [
                item for item in structure.get(
                    "swing_highs", []
                )
                if item["index"] < event["candle_index"]
            ]

            if candidates:
                protected_high = candidates[-1]

        return {
            "protected_high": protected_high,
            "protected_low": protected_low,
        }

    # ---------------------------------------------------------
    # LIQUIDITY SWEEP DETECTION
    # ---------------------------------------------------------

    def detect_liquidity_sweeps(
        self,
        candles: List[Dict[str, Any]],
        swings: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        sweeps = []

        for index, candle in enumerate(candles):

            for swing in swings:

                if swing["index"] >= index:
                    continue

                level = swing["price"]

                if swing["type"] == "HIGH":

                    if (
                        candle["high"] > level
                        and candle["close"] < level
                    ):

                        event = {
                            "type": "BUY_SIDE_SWEEP",
                            "level": level,
                            "candle_index": index,
                            "confirmation":
                                "WICK_THROUGH_CLOSE_BACK_INSIDE",
                        }

                        if "timestamp" in candle:
                            event["timestamp"] = candle["timestamp"]

                        sweeps.append(event)

                elif swing["type"] == "LOW":

                    if (
                        candle["low"] < level
                        and candle["close"] > level
                    ):

                        event = {
                            "type": "SELL_SIDE_SWEEP",
                            "level": level,
                            "candle_index": index,
                            "confirmation":
                                "WICK_THROUGH_CLOSE_BACK_INSIDE",
                        }

                        if "timestamp" in candle:
                            event["timestamp"] = candle["timestamp"]

                        sweeps.append(event)

        return sweeps

    # ---------------------------------------------------------
    # EQUAL HIGH / LOW DETECTION
    # ---------------------------------------------------------

    def detect_equal_levels(
        self,
        swings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

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

                if abs(
                    first["price"] - second["price"]
                ) <= self.equal_level_tolerance:

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

                if abs(
                    first["price"] - second["price"]
                ) <= self.equal_level_tolerance:

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

    # ---------------------------------------------------------
    # RANGE IDENTIFICATION
    # ---------------------------------------------------------

    def identify_range(
        self,
        candles: List[Dict[str, Any]],
        structure: Dict[str, Any],
    ) -> Dict[str, Any]:

        highs = structure.get("swing_highs", [])
        lows = structure.get("swing_lows", [])

        if (
            len(highs) < self.range_minimum_swings
            or len(lows) < self.range_minimum_swings
        ):

            return {
                "detected": False,
                "confirmed": False,
                "reason": "INSUFFICIENT_RANGE_SWINGS",
            }

        recent_highs = highs[-self.range_minimum_swings:]
        recent_lows = lows[-self.range_minimum_swings:]

        range_high = max(
            item["price"] for item in recent_highs
        )

        range_low = min(
            item["price"] for item in recent_lows
        )

        if range_high <= range_low:

            return {
                "detected": False,
                "confirmed": False,
                "reason": "INVALID_RANGE_BOUNDARIES",
            }

        latest_close = candles[-1]["close"]

        equilibrium = (
            range_high + range_low
        ) / 2

        inside_range = (
            range_low <= latest_close <= range_high
        )

        # This is a candidate range, not a definitive
        # market-regime decision. The master SMC engine
        # must validate reactions and liquidity context.
        return {
            "detected": True,
            "confirmed": False,
            "status": "RANGE_CANDIDATE",
            "range_high": range_high,
            "range_low": range_low,
            "equilibrium": equilibrium,
            "premium": latest_close > equilibrium,
            "discount": latest_close < equilibrium,
            "inside_range": inside_range,
            "current_price": latest_close,
        }

    # ---------------------------------------------------------
    # INDEPENDENT EXTERNAL / INTERNAL ANALYSIS
    # ---------------------------------------------------------

    def _analyse_layer(
        self,
        candles: List[Dict[str, Any]],
        strength: int,
        previous_bias: str,
        layer_name: str,
    ) -> Dict[str, Any]:

        swings = self.detect_swings(
            candles,
            strength,
        )

        structure = self.classify_structure(swings)

        breaks = self.detect_structure_breaks(
            candles,
            swings,
            previous_bias,
        )

        sweeps = self.detect_liquidity_sweeps(
            candles,
            swings,
        )

        equal_levels = self.detect_equal_levels(
            swings
        )

        protected = self.identify_protected_levels(
            structure,
            breaks,
        )

        return {
            "layer": layer_name,
            "bias": structure["bias"],
            "structure": structure,
            "swings": swings,
            "breaks": breaks,
            "liquidity_sweeps": sweeps,
            "equal_levels": equal_levels,
            "protected_levels": protected,
            "latest_break": (
                breaks[-1] if breaks else None
            ),
        }

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Any,
        previous_bias: str = "NEUTRAL",
        previous_external_bias: Optional[str] = None,
        previous_internal_bias: Optional[str] = None,
    ) -> Dict[str, Any]:

        validated = self._validate_candles(candles)

        if previous_external_bias is None:
            previous_external_bias = previous_bias

        if previous_internal_bias is None:
            previous_internal_bias = "NEUTRAL"

        if len(validated) < 7:

            result = {
                "status": "INSUFFICIENT_DATA",
                "version": self.VERSION,
                "external": {},
                "internal": {},
                "execution_authorized": False,
            }

            self.last_result = result
            return result

        external = self._analyse_layer(
            validated,
            self.external_swing_strength,
            previous_external_bias,
            "EXTERNAL",
        )

        internal = self._analyse_layer(
            validated,
            self.internal_swing_strength,
            previous_internal_bias,
            "INTERNAL",
        )

        range_evidence = self.identify_range(
            validated,
            external["structure"],
        )

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "candle_count": len(validated),

            # Backwards-compatible fields.
            "bias": external["bias"],
            "structure": external["structure"],
            "swings": external["swings"],
            "breaks": external["breaks"],
            "liquidity_sweeps": external["liquidity_sweeps"],
            "equal_levels": external["equal_levels"],

            # Independent structure layers.
            "external": external,
            "internal": internal,

            # Range candidate evidence.
            "range": range_evidence,

            "previous_bias": previous_external_bias,
            "previous_external_bias": previous_external_bias,
            "previous_internal_bias": previous_internal_bias,

            "execution_authorized": False,
        }

        self.last_result = result

        return result

    # British spelling compatibility.
    def analyse(
        self,
        candles: Any,
        previous_bias: str = "NEUTRAL",
        previous_external_bias: Optional[str] = None,
        previous_internal_bias: Optional[str] = None,
    ) -> Dict[str, Any]:

        return self.analyze(
            candles=candles,
            previous_bias=previous_bias,
            previous_external_bias=previous_external_bias,
            previous_internal_bias=previous_internal_bias,
        )

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return deepcopy(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "SMC_STRUCTURE_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "external_swing_strength":
                self.external_swing_strength,
            "internal_swing_strength":
                self.internal_swing_strength,
            "equal_level_tolerance":
                self.equal_level_tolerance,
        }


smc_structure_engine = SMCStructureEngine()
