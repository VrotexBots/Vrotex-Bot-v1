"""
Vrotex Bot V1
TECHNICAL ANALYSIS - PRO-TREND STRATEGY
Filename: technical_analysis_pro_trend.py
Version: 1.0.1

This is the separate Pro-Trend strategy module. It preserves the user's
sixteen Pro-Trend notes in their H1 -> M5 -> M1 sequence.

SCOPE
-----
1. H1: macro bias, external Strong/Weak swings, BOS lifecycle, IDM, POI,
   premium/discount, POI invalidation and the four-condition M5 handover.
2. M5: external pullback structure, dynamic External CHoCH line, body-close
   reversal, post-CHoCH dealing range, IDM, POI and the four-condition M1 handover.
3. M1: final liquidity sweep, body-close CHoCH, displacement + FVG, OB/FVG
   selection, entry/stop references, SAST session, spread, red-folder news,
   and the Two-Strike Rule.
4. Note 16: complete three-timeframe alignment summary.

IMPORTANT DESIGN BOUNDARIES
---------------------------
- This file is a strategy analysis/evidence module. Broker order placement is
  part of the later execution build.
- It does not authorize execution.
- It does not use ATR, EMA, RSI, support/resistance, momentum indicators, or
  other unapproved indicators/filters.
- BOS and CHoCH require a candle BODY CLOSE beyond the relevant swing level.
  A wick-only excursion is a sweep/probe, not a structural break.
- The user's notes do not define a numeric swing strength, displacement size,
  exact SAST session clock windows, tight-spread threshold, or news provider.
  These are not fabricated here. Swing strength is configurable; the other
  live facts are accepted as explicit inputs from the integrated components.
- The user's explicit H1 bearish counterpart is Strong High -> Weak Low.
- The M5 and M1 methods preserve the user's buy/sell mirror rules where the
  notes explicitly describe both directions. They do not add new strategy
  filters.

Input candle format:
    {"open": float, "high": float, "low": float, "close": float,
     "timestamp": optional value}

Public interface:
    pro_trend_strategy.analyze(...)
    pro_trend_strategy.analyze_h1(...)
    pro_trend_strategy.analyze_m5(...)
    pro_trend_strategy.analyze_m1(...)

The module returns structured evidence, gates, chart markings, and next-stage
status. It never sends an order to a broker.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


class ProTrendStrategy:
    """Rule-based implementation of Pro-Trend Notes 1-16."""

    VERSION = "1.0.1"
    STRATEGY_NAME = "PRO_TREND"
    TIMEZONE = "Africa/Johannesburg"
    SAST_LABEL = "SAST"

    NOTE_MAP = {
        1: "Defining True 1H Swing Points (Strong vs. Weak)",
        2: "The 1H Structural Lifecycle (Step-by-Step)",
        3: "Strictly Enforcing 1H Rules (Avoiding Traps)",
        4: "1H Chart Markings",
        5: "Selecting the Right 1H POI",
        6: "When a 1H POI Is Dead (Invalidation)",
        7: "H1 Pre-Flight Checklist",
        8: "5-Minute External Structure (Inside the 1H POI)",
        9: "The 3 Rules of 5M External Structure",
        10: "Finding Your 5M Entry Zone (Inside New 5M Range)",
        11: "Finding Your 5M POI",
        12: "Select 5M POI and Wait for Tap",
        13: "How 5M External vs. Internal Guides Your 1M Drop",
        14: "1M Precision Sniper Entry (Pro-Trend)",
        15: "Strict 1M Execution Filters (Avoiding 1M Noise)",
        16: "Complete 3-Timeframe Alignment Recap (Pro-Trend)",
    }

    def __init__(
        self,
        swing_strength: int = 2,
        equal_level_tolerance: float = 0.0002,
    ) -> None:
        # Swing strength is a pivot-identification setting, not an indicator.
        self.swing_strength = max(1, int(swing_strength))
        self.equal_level_tolerance = max(0.0, float(equal_level_tolerance))
        self.last_result: Dict[str, Any] = {}

    # ==================================================================
    # 1. COMMON DATA NORMALIZATION
    # ==================================================================

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)
            if number != number:
                return None
            return number
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def normalize_candles(
        cls,
        candles: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Validate OHLC candles while preserving their original index."""
        normalized: List[Dict[str, Any]] = []

        if not isinstance(candles, (list, tuple)):
            return normalized

        for original_index, source in enumerate(candles):
            if not isinstance(source, dict):
                continue

            open_price = cls._number(source.get("open"))
            high = cls._number(source.get("high"))
            low = cls._number(source.get("low"))
            close = cls._number(source.get("close"))

            if None in (open_price, high, low, close):
                continue
            if high < low:
                continue
            if high < max(open_price, close):
                continue
            if low > min(open_price, close):
                continue

            normalized.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "timestamp": (
                    source.get("timestamp")
                    or source.get("time")
                    or source.get("datetime")
                ),
                "original_index": original_index,
            })

        return normalized

    @staticmethod
    def _direction_opposite(direction: str) -> str:
        return "BEARISH" if direction == "BULLISH" else "BULLISH"

    @staticmethod
    def _body_direction(candle: Dict[str, Any]) -> str:
        if candle["close"] > candle["open"]:
            return "BULLISH"
        if candle["close"] < candle["open"]:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _body_size(candle: Dict[str, Any]) -> float:
        return abs(candle["close"] - candle["open"])

    @staticmethod
    def _candle_range(candle: Dict[str, Any]) -> float:
        return candle["high"] - candle["low"]

    @staticmethod
    def _valid_direction(direction: Optional[str]) -> bool:
        return str(direction or "").upper() in ("BULLISH", "BEARISH")

    @staticmethod
    def _condition(name: str, passed: bool, detail: Optional[str] = None) -> Dict[str, Any]:
        item = {
            "name": name,
            "passed": bool(passed),
            "status": "YES" if passed else "NO",
        }
        if detail is not None:
            item["detail"] = detail
        return item

    @staticmethod
    def _all_passed(conditions: Sequence[Dict[str, Any]]) -> bool:
        return bool(conditions) and all(item.get("passed") is True for item in conditions)

    @staticmethod
    def _swing_ref(swing: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return deepcopy(swing) if swing is not None else None

    # ==================================================================
    # 2. SWINGS, EXTERNAL STRUCTURE, AND BODY-CLOSE EVENTS
    # ==================================================================

    def detect_swings(
        self,
        candles: Sequence[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Detect confirmed local pivot highs/lows.

        A pivot is only confirmed after `swing_strength` candles exist to its
        right. A swing is a candidate pivot; Strong/Weak classification is
        performed separately by the structural lifecycle methods below.
        """
        highs: List[Dict[str, Any]] = []
        lows: List[Dict[str, Any]] = []
        strength = self.swing_strength

        for index in range(strength, len(candles) - strength):
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
                    "index": index,
                    "timestamp": current.get("timestamp"),
                    "type": "SWING_HIGH",
                    "confirmed": True,
                })

            if is_low:
                lows.append({
                    "price": current["low"],
                    "index": index,
                    "timestamp": current.get("timestamp"),
                    "type": "SWING_LOW",
                    "confirmed": True,
                })

        return {"highs": highs, "lows": lows}

    @staticmethod
    def label_swing_sequence(
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Label successive highs HH/LH and lows HL/LL."""
        high_labels: List[Dict[str, Any]] = []
        low_labels: List[Dict[str, Any]] = []

        highs = swings.get("highs", [])
        lows = swings.get("lows", [])

        for index in range(1, len(highs)):
            current = highs[index]
            previous = highs[index - 1]
            label = "HH" if current["price"] > previous["price"] else "LH"
            high_labels.append({**current, "label": label})

        for index in range(1, len(lows)):
            current = lows[index]
            previous = lows[index - 1]
            label = "HL" if current["price"] > previous["price"] else "LL"
            low_labels.append({**current, "label": label})

        return {"highs": high_labels, "lows": low_labels}

    @staticmethod
    def _first_body_close_break(
        candles: Sequence[Dict[str, Any]],
        start_index: int,
        end_index: int,
        level: float,
        direction: str,
    ) -> Optional[int]:
        """Return first candle index whose CLOSE breaks the level."""
        start = max(0, start_index)
        end = min(len(candles) - 1, end_index)

        for index in range(start, end + 1):
            close = candles[index]["close"]
            if direction == "BULLISH" and close > level:
                return index
            if direction == "BEARISH" and close < level:
                return index
        return None

    def find_bos_legs(
        self,
        candles: Sequence[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find BOS legs used to identify Strong anchors and Weak targets.

        Bullish leg:
          swing low -> later full candle-body close above a previous swing high.
        Bearish leg:
          swing high -> later full candle-body close below a previous swing low.

        Wick-only breaks are deliberately excluded.
        """
        bullish_legs: List[Dict[str, Any]] = []
        bearish_legs: List[Dict[str, Any]] = []
        highs = swings.get("highs", [])
        lows = swings.get("lows", [])

        for origin_low in lows:
            previous_external_highs = [
                high for high in highs if high["index"] < origin_low["index"]
            ]
            if not previous_external_highs:
                continue

            previous_external_high = previous_external_highs[-1]
            break_index = self._first_body_close_break(
                candles,
                origin_low["index"] + 1,
                len(candles) - 1,
                previous_external_high["price"],
                "BULLISH",
            )
            if break_index is None:
                continue

            later_highs = [
                high for high in highs if high["index"] > break_index
            ]
            weak_high = later_highs[0] if later_highs else None
            bullish_legs.append({
                "direction": "BULLISH",
                "strong_low": deepcopy(origin_low),
                "broken_external_high": deepcopy(previous_external_high),
                "bos_index": break_index,
                "bos_timestamp": candles[break_index].get("timestamp"),
                "weak_high": deepcopy(weak_high),
                "confirmation": "FULL_BODY_CLOSE",
            })

        for origin_high in highs:
            previous_external_lows = [
                low for low in lows if low["index"] < origin_high["index"]
            ]
            if not previous_external_lows:
                continue

            previous_external_low = previous_external_lows[-1]
            break_index = self._first_body_close_break(
                candles,
                origin_high["index"] + 1,
                len(candles) - 1,
                previous_external_low["price"],
                "BEARISH",
            )
            if break_index is None:
                continue

            later_lows = [
                low for low in lows if low["index"] > break_index
            ]
            weak_low = later_lows[0] if later_lows else None
            bearish_legs.append({
                "direction": "BEARISH",
                "strong_high": deepcopy(origin_high),
                "broken_external_low": deepcopy(previous_external_low),
                "bos_index": break_index,
                "bos_timestamp": candles[break_index].get("timestamp"),
                "weak_low": deepcopy(weak_low),
                "confirmation": "FULL_BODY_CLOSE",
            })

        return {
            "bullish": bullish_legs,
            "bearish": bearish_legs,
        }

    def classify_external_structure(
        self,
        candles: Sequence[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
        previous_bias: str = "UNKNOWN",
    ) -> Dict[str, Any]:
        """Classify current macro direction and its protected/target swings."""
        legs = self.find_bos_legs(candles, swings)
        bullish = legs["bullish"][-1] if legs["bullish"] else None
        bearish = legs["bearish"][-1] if legs["bearish"] else None

        bias = str(previous_bias or "UNKNOWN").upper()
        if bullish and (not bearish or bullish["bos_index"] > bearish["bos_index"]):
            bias = "BULLISH"
        elif bearish:
            bias = "BEARISH"
        elif bias not in ("BULLISH", "BEARISH"):
            bias = "UNKNOWN"

        strong_low = bullish.get("strong_low") if bullish else None
        weak_high = bullish.get("weak_high") if bullish else None
        strong_high = bearish.get("strong_high") if bearish else None
        weak_low = bearish.get("weak_low") if bearish else None

        if bias == "BULLISH":
            active_leg = bullish
            protected = strong_low
            target = weak_high
        elif bias == "BEARISH":
            active_leg = bearish
            protected = strong_high
            target = weak_low
        else:
            active_leg = None
            protected = None
            target = None

        return {
            "bias": bias,
            "strong_low": deepcopy(strong_low),
            "weak_high": deepcopy(weak_high),
            "strong_high": deepcopy(strong_high),
            "weak_low": deepcopy(weak_low),
            "protected_swing": deepcopy(protected),
            "weak_target": deepcopy(target),
            "active_bos_leg": deepcopy(active_leg),
            "bos_legs": legs,
            "swing_labels": self.label_swing_sequence(swings),
        }

    def detect_latest_body_close_break(
        self,
        candles: Sequence[Dict[str, Any]],
        level: Optional[float],
        direction: str,
        previous_bias: str = "UNKNOWN",
    ) -> Optional[Dict[str, Any]]:
        """Detect a latest-candle body-close break of a supplied external level."""
        if not candles or level is None:
            return None

        candle = candles[-1]
        close = candle["close"]
        broken = close > level if direction == "BULLISH" else close < level
        if not broken:
            return None

        previous_bias = str(previous_bias or "UNKNOWN").upper()
        event_type = (
            "CHoCH"
            if previous_bias in ("BULLISH", "BEARISH") and previous_bias != direction
            else "BOS"
        )
        return {
            "type": event_type,
            "direction": direction,
            "level": level,
            "index": len(candles) - 1,
            "timestamp": candle.get("timestamp"),
            "open": candle["open"],
            "close": close,
            "confirmation": "BODY_CLOSE",
            "body_close_confirmed": True,
            "wick_only_is_break": False,
        }

    # ==================================================================
    # 3. LIQUIDITY, IDM AND SWEEP DETECTION
    # ==================================================================

    @staticmethod
    def detect_sweep_of_level(
        candles: Sequence[Dict[str, Any]],
        level: Optional[float],
        direction: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Bullish liquidity sweep: wick below a low, candle closes back above.
        Bearish liquidity sweep: wick above a high, candle closes back below.
        """
        if not candles or level is None:
            return None

        candle = candles[-1]
        if direction == "BULLISH":
            swept = candle["low"] < level and candle["close"] > level
            event_type = "LOW_SWEEP"
        else:
            swept = candle["high"] > level and candle["close"] < level
            event_type = "HIGH_SWEEP"

        if not swept:
            return None

        return {
            "type": event_type,
            "direction": direction,
            "level": level,
            "index": len(candles) - 1,
            "timestamp": candle.get("timestamp"),
            "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
            "confirmed": True,
        }

    def detect_liquidity_sweeps(
        self,
        candles: Sequence[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        if not candles:
            return events

        current = candles[-1]
        for swing in swings.get("highs", []):
            if current["high"] > swing["price"] and current["close"] < swing["price"]:
                events.append({
                    "type": "HIGH_SWEEP",
                    "direction": "BEARISH",
                    "level": swing["price"],
                    "swing_index": swing["index"],
                    "index": len(candles) - 1,
                    "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
                })

        for swing in swings.get("lows", []):
            if current["low"] < swing["price"] and current["close"] > swing["price"]:
                events.append({
                    "type": "LOW_SWEEP",
                    "direction": "BULLISH",
                    "level": swing["price"],
                    "swing_index": swing["index"],
                    "index": len(candles) - 1,
                    "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
                })

        return events

    @staticmethod
    def identify_internal_inducement(
        swings: Dict[str, List[Dict[str, Any]]],
        direction: str,
        range_start_index: int,
        range_end_index: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Select the first major internal pullback swing within the supplied
        range. The strategy caller may supply an exact IDM level where its
        structure engine has already identified it.
        """
        end = range_end_index if range_end_index is not None else 10**12
        if direction == "BULLISH":
            candidates = [
                item for item in swings.get("lows", [])
                if range_start_index <= item["index"] <= end
            ]
        else:
            candidates = [
                item for item in swings.get("highs", [])
                if range_start_index <= item["index"] <= end
            ]
        return deepcopy(candidates[0]) if candidates else None

    # ==================================================================
    # 4. FVG, ORDER BLOCK, MITIGATION AND POI SELECTION
    # ==================================================================

    def detect_fvgs(
        self,
        candles: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Three-candle fair value gap detection with subsequent mitigation."""
        fvgs: List[Dict[str, Any]] = []

        for index in range(2, len(candles)):
            first = candles[index - 2]
            middle = candles[index - 1]
            third = candles[index]

            if third["low"] > first["high"]:
                lower, upper = first["high"], third["low"]
                fvgs.append({
                    "type": "BULLISH_FVG",
                    "direction": "BULLISH",
                    "lower": lower,
                    "upper": upper,
                    "midpoint": (lower + upper) / 2.0,
                    "gap_size": upper - lower,
                    "formation_index": index,
                    "index": index,
                    "timestamp": third.get("timestamp"),
                    "clean": True,
                    "unmitigated": True,
                    "mitigation": "NONE",
                })

            if third["high"] < first["low"]:
                lower, upper = third["high"], first["low"]
                fvgs.append({
                    "type": "BEARISH_FVG",
                    "direction": "BEARISH",
                    "lower": lower,
                    "upper": upper,
                    "midpoint": (lower + upper) / 2.0,
                    "gap_size": upper - lower,
                    "formation_index": index,
                    "index": index,
                    "timestamp": third.get("timestamp"),
                    "clean": True,
                    "unmitigated": True,
                    "mitigation": "NONE",
                })

        self._track_zone_mitigation(fvgs, candles)
        return fvgs

    def detect_order_blocks(
        self,
        candles: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Identify opposite-colour origin candles immediately before a
        directional displacement candle. No ATR or other indicator is used.
        Displacement confirmation is based on the user's full-body/FVG rule
        where the caller supplies it; otherwise candidates remain candidates.
        """
        blocks: List[Dict[str, Any]] = []

        for index in range(1, len(candles)):
            origin = candles[index - 1]
            impulse = candles[index]
            origin_direction = self._body_direction(origin)
            impulse_direction = self._body_direction(impulse)

            if impulse_direction == "BULLISH" and origin_direction == "BEARISH":
                direction = "BULLISH"
            elif impulse_direction == "BEARISH" and origin_direction == "BULLISH":
                direction = "BEARISH"
            else:
                continue

            blocks.append({
                "type": direction + "_ORDER_BLOCK",
                "direction": direction,
                "lower": origin["low"],
                "upper": origin["high"],
                "midpoint": (origin["low"] + origin["high"]) / 2.0,
                "formation_index": index - 1,
                "displacement_index": index,
                "timestamp": origin.get("timestamp"),
                "displacement_timestamp": impulse.get("timestamp"),
                "origin_open": origin["open"],
                "origin_close": origin["close"],
                "displacement_open": impulse["open"],
                "displacement_close": impulse["close"],
                "displacement_body": self._body_size(impulse),
                "clean": True,
                "unmitigated": True,
                "mitigation": "NONE",
                "candidate_requires_displacement_confirmation": True,
            })

        self._track_zone_mitigation(blocks, candles)
        return blocks

    @staticmethod
    def _track_zone_mitigation(
        zones: List[Dict[str, Any]],
        candles: Sequence[Dict[str, Any]],
    ) -> None:
        """A later candle touching the zone marks it mitigated/used."""
        for zone in zones:
            lower = zone["lower"]
            upper = zone["upper"]

            for index in range(zone["formation_index"] + 1, len(candles)):
                candle = candles[index]
                overlaps = candle["low"] <= upper and candle["high"] >= lower
                if not overlaps:
                    continue

                zone["clean"] = False
                zone["unmitigated"] = False
                if candle["low"] <= lower and candle["high"] >= upper:
                    zone["mitigation"] = "FULL"
                elif candle["low"] <= zone["midpoint"] <= candle["high"]:
                    zone["mitigation"] = "MIDPOINT"
                else:
                    zone["mitigation"] = "PARTIAL"
                zone["mitigated_at_index"] = index
                zone["mitigated_at_timestamp"] = candle.get("timestamp")
                break

    def collect_poi_candidates(
        self,
        candles: Sequence[Dict[str, Any]],
        direction: str,
    ) -> List[Dict[str, Any]]:
        zones = self.detect_fvgs(candles) + self.detect_order_blocks(candles)
        return [
            zone for zone in zones
            if zone.get("direction") == direction
            and zone.get("clean") is True
            and zone.get("unmitigated") is True
        ]

    @staticmethod
    def _zone_is_in_correct_half(
        zone: Dict[str, Any],
        direction: str,
        equilibrium: Optional[float],
    ) -> bool:
        if equilibrium is None:
            return False
        if direction == "BULLISH":
            return zone["midpoint"] < equilibrium
        return zone["midpoint"] > equilibrium

    def select_poi(
        self,
        candles: Sequence[Dict[str, Any]],
        direction: str,
        equilibrium: Optional[float],
        inducement_price: Optional[float],
        strong_anchor: Optional[float],
        bos_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        POI hierarchy from Note 5:
          1. Extreme: unmitigated OB/FVG at the origin, closest to Strong anchor.
          2. Decisional: last unmitigated OB/FVG before the BOS.
          3. IDM filter: reject zones without a clear inducement in front.
        """
        candidates = self.collect_poi_candidates(candles, direction)
        eligible: List[Dict[str, Any]] = []

        for zone in candidates:
            if not self._zone_is_in_correct_half(zone, direction, equilibrium):
                continue

            if inducement_price is None:
                continue

            if direction == "BULLISH":
                inducement_in_front = inducement_price > zone["upper"]
            else:
                inducement_in_front = inducement_price < zone["lower"]

            if not inducement_in_front:
                continue

            eligible.append(deepcopy(zone))

        if not eligible:
            return {
                "selected": None,
                "selection": None,
                "candidates": [],
                "reason": "NO_UNMITIGATED_POI_WITH_CLEAR_IDM_IN_FRONT",
                "inducement_filter_passed": False,
            }

        extreme_candidates = eligible
        if bos_index is not None:
            before_bos = [
                zone for zone in eligible
                if zone["formation_index"] <= bos_index
            ]
            if before_bos:
                extreme_candidates = before_bos

        extreme = None
        if strong_anchor is not None and extreme_candidates:
            extreme = min(
                extreme_candidates,
                key=lambda zone: abs(zone["midpoint"] - strong_anchor),
            )

        decisional_candidates = eligible
        if bos_index is not None:
            before_bos = [
                zone for zone in eligible
                if zone["formation_index"] <= bos_index
            ]
            if before_bos:
                decisional_candidates = before_bos

        decisional = max(
            decisional_candidates,
            key=lambda zone: zone["formation_index"],
        )

        # Apply the stated hierarchy: choose the extreme POI when present.
        selected = extreme if extreme is not None else decisional
        selection = "EXTREME" if extreme is not None else "DECISIONAL"

        return {
            "selected": deepcopy(selected),
            "selection": selection,
            "extreme_poi": deepcopy(extreme),
            "decisional_poi": deepcopy(decisional),
            "candidates": deepcopy(eligible),
            "inducement_filter_passed": True,
            "location_filter": "DISCOUNT" if direction == "BULLISH" else "PREMIUM",
        }

    @staticmethod
    def is_price_inside_zone(
        price: Optional[float],
        zone: Optional[Dict[str, Any]],
    ) -> bool:
        if price is None or zone is None:
            return False
        return zone["lower"] <= price <= zone["upper"]

    @staticmethod
    def candle_taps_zone(
        candle: Optional[Dict[str, Any]],
        zone: Optional[Dict[str, Any]],
    ) -> bool:
        if candle is None or zone is None:
            return False
        return candle["low"] <= zone["upper"] and candle["high"] >= zone["lower"]

    @staticmethod
    def zone_invalidated_by_body_close(
        candle: Optional[Dict[str, Any]],
        zone: Optional[Dict[str, Any]],
        direction: str,
    ) -> bool:
        """
        Note 6: only a full candle-body close beyond the far extreme invalidates.
        A wick through the zone does not invalidate it.
        """
        if candle is None or zone is None:
            return False
        if direction == "BULLISH":
            return candle["close"] < zone["lower"]
        return candle["close"] > zone["upper"]

    # ==================================================================
    # 5. DEALING RANGE AND FIBONACCI EQUILIBRIUM
    # ==================================================================

    @staticmethod
    def calculate_dealing_range(
        strong_price: Optional[float],
        weak_price: Optional[float],
        current_price: Optional[float],
    ) -> Dict[str, Any]:
        if strong_price is None or weak_price is None:
            return {
                "valid": False,
                "range_low": None,
                "range_high": None,
                "equilibrium": None,
                "zone": "UNKNOWN",
            }

        low = min(strong_price, weak_price)
        high = max(strong_price, weak_price)
        if high <= low:
            return {
                "valid": False,
                "range_low": low,
                "range_high": high,
                "equilibrium": None,
                "zone": "UNKNOWN",
            }

        equilibrium = (low + high) / 2.0
        if current_price is None:
            zone = "UNKNOWN"
        elif current_price < equilibrium:
            zone = "DISCOUNT"
        elif current_price > equilibrium:
            zone = "PREMIUM"
        else:
            zone = "EQUILIBRIUM"

        return {
            "valid": True,
            "range_low": low,
            "range_high": high,
            "equilibrium": equilibrium,
            "zone": zone,
            "current_price": current_price,
            "range_size": high - low,
            "fib_50_percent": equilibrium,
        }

    # ==================================================================
    # 6. H1 STRATEGY - NOTES 1 THROUGH 7
    # ==================================================================

    def analyze_h1(
        self,
        candles: Sequence[Dict[str, Any]],
        previous_bias: str = "UNKNOWN",
        current_price: Optional[float] = None,
        inducement_price: Optional[float] = None,
        live_price_inside_poi: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Notes 1-7:
        identify external Strong/Weak swings, lifecycle, body-close rules,
        chart markings, POI hierarchy/invalidation, and four-point pre-flight.
        """
        data = self.normalize_candles(candles)
        minimum = self.swing_strength * 2 + 5
        if len(data) < minimum:
            return self._stage_error("H1", "INSUFFICIENT_VALID_CANDLES", len(data))

        price = self._number(current_price)
        if price is None:
            price = data[-1]["close"]

        swings = self.detect_swings(data)
        structure = self.classify_external_structure(data, swings, previous_bias)
        bias = structure["bias"]

        strong_low = structure["strong_low"]
        weak_high = structure["weak_high"]
        strong_high = structure["strong_high"]
        weak_low = structure["weak_low"]
        active_leg = structure["active_bos_leg"]

        # Note 3: protected swing invalidation requires body close beyond it.
        choch = None
        if bias == "BULLISH" and strong_low:
            if data[-1]["close"] < strong_low["price"]:
                choch = {
                    "type": "CHoCH",
                    "direction": "BEARISH",
                    "level": strong_low["price"],
                    "confirmation": "FULL_BODY_CLOSE",
                }
                bias = "BEARISH"
        elif bias == "BEARISH" and strong_high:
            if data[-1]["close"] > strong_high["price"]:
                choch = {
                    "type": "CHoCH",
                    "direction": "BULLISH",
                    "level": strong_high["price"],
                    "confirmation": "FULL_BODY_CLOSE",
                }
                bias = "BULLISH"

        if bias == "BULLISH":
            range_start = strong_low
            range_end = weak_high
            strong_anchor = strong_low["price"] if strong_low else None
            weak_target = weak_high["price"] if weak_high else None
            direction = "BULLISH"
        elif bias == "BEARISH":
            range_start = strong_high
            range_end = weak_low
            strong_anchor = strong_high["price"] if strong_high else None
            weak_target = weak_low["price"] if weak_low else None
            direction = "BEARISH"
        else:
            range_start = range_end = None
            strong_anchor = weak_target = None
            direction = None

        dealing_range = self.calculate_dealing_range(
            strong_anchor, weak_target, price
        )

        # Note 2: first major internal pullback swing acts as IDM.
        # Caller-supplied IDM takes precedence because it may be identified
        # by the central structure engine using its full context.
        idm_swing = None
        if direction and active_leg:
            start_index = active_leg.get("bos_index", 0)
            idm_swing = self.identify_internal_inducement(
                swings, direction, start_index
            )
        idm_level = self._number(inducement_price)
        if idm_level is None and idm_swing:
            idm_level = idm_swing["price"]

        liquidity_sweep = self.detect_sweep_of_level(data, idm_level, direction) if direction else None

        # Note 5: POI is chosen only if it is unmitigated, in the correct half,
        # and has a clear IDM in front of it.
        poi = (
            self.select_poi(
                data,
                direction,
                dealing_range.get("equilibrium"),
                idm_level,
                strong_anchor,
                active_leg.get("bos_index") if active_leg else None,
            )
            if direction else {
                "selected": None,
                "selection": None,
                "reason": "DIRECTION_NOT_ESTABLISHED",
            }
        )
        selected_poi = poi.get("selected")

        # Live price can be supplied by the tick feed; otherwise use latest
        # candle overlap as the available evidence.
        poi_tapped = self.candle_taps_zone(data[-1], selected_poi)
        if live_price_inside_poi is not None:
            poi_tapped = bool(live_price_inside_poi)

        poi_invalidated = self.zone_invalidated_by_body_close(
            data[-1], selected_poi, direction
        ) if direction else False
        if poi_invalidated:
            poi_tapped = False

        required_location = "DISCOUNT" if bias == "BULLISH" else "PREMIUM"
        location_passed = dealing_range.get("zone") == required_location
        trend_range_passed = bool(direction and strong_anchor is not None and weak_target is not None)
        liquidity_passed = liquidity_sweep is not None
        arrival_passed = bool(
            selected_poi
            and selected_poi.get("unmitigated") is True
            and poi_tapped
            and not poi_invalidated
        )

        # Note 7: all four conditions are required for the M5 handover.
        preflight = [
            self._condition(
                "H1 Trend & Range",
                trend_range_passed,
                "Strong and Weak external range anchors identified.",
            ),
            self._condition(
                "H1 Location",
                location_passed,
                "Price must be in Discount for buys or Premium for sells.",
            ),
            self._condition(
                "H1 Liquidity",
                liquidity_passed,
                "H1 Inducement must be swept.",
            ),
            self._condition(
                "H1 Arrival",
                arrival_passed,
                "Live price must tap the unmitigated Extreme or Decisional H1 POI.",
            ),
        ]

        # Note 4: chart markings for all external anchors, 50% equilibrium,
        # and the selected POI.
        chart_markings = {
            "strong_low": self._swing_ref(strong_low),
            "weak_high": self._swing_ref(weak_high),
            "strong_high": self._swing_ref(strong_high),
            "weak_low": self._swing_ref(weak_low),
            "equilibrium_50_percent": dealing_range.get("equilibrium"),
            "selected_h1_poi": deepcopy(selected_poi),
            "poi_selection": poi.get("selection"),
        }

        result = {
            "success": True,
            "strategy": self.STRATEGY_NAME,
            "timeframe": "H1",
            "notes_implemented": list(range(1, 8)),
            "bias": bias,
            "structure": structure,
            "swings": swings,
            "bos_lifecycle": {
                "active_bos_leg": deepcopy(active_leg),
                "expansion_confirmed_by_body_close": bool(active_leg),
                "range_locked": dealing_range.get("valid", False),
                "pullback_inducement": deepcopy(idm_swing),
                "inducement_price": idm_level,
                "inducement_sweep": liquidity_sweep,
                "mitigation_poi": deepcopy(selected_poi),
            },
            "dealing_range": dealing_range,
            "equilibrium": dealing_range.get("equilibrium"),
            "location": dealing_range.get("zone"),
            "inducement": {
                "swing": deepcopy(idm_swing),
                "price": idm_level,
                "swept": liquidity_passed,
                "sweep_evidence": liquidity_sweep,
            },
            "poi": poi,
            "poi_tapped": poi_tapped,
            "poi_invalidated": poi_invalidated,
            "choch": choch,
            "chart_markings": chart_markings,
            "preflight": preflight,
            "preflight_passed": self._all_passed(preflight),
            "handover_to_m5": self._all_passed(preflight),
            "evidence_only": True,
        }
        return result

    # ==================================================================
    # 7. M5 STRATEGY - NOTES 8 THROUGH 13
    # ==================================================================

    def _find_m5_external_choch_line(
        self,
        candles: Sequence[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
        h1_bias: str,
    ) -> Dict[str, Any]:
        """
        Note 8:
        If H1 bullish, M5 is bearish during the pullback; track the most
        recent M5 swing high that drove a fresh lower low.
        If H1 bearish, M5 is bullish during the pullback; track the most
        recent M5 swing low that drove a fresh higher high.
        """
        highs = swings.get("highs", [])
        lows = swings.get("lows", [])

        if h1_bias == "BULLISH":
            pairs = []
            for high in highs:
                subsequent_lows = [low for low in lows if low["index"] > high["index"]]
                if subsequent_lows:
                    low = subsequent_lows[-1]
                    pairs.append((high, low))
            if not pairs:
                return {"line": None, "swing": None, "direction": "BULLISH"}
            swing, caused_low = pairs[-1]
            return {
                "line": swing["price"],
                "swing": deepcopy(swing),
                "caused_pullback_extreme": deepcopy(caused_low),
                "direction": "BULLISH",
                "line_type": "M5_EXTERNAL_CHOCH_LINE",
            }

        pairs = []
        for low in lows:
            subsequent_highs = [high for high in highs if high["index"] > low["index"]]
            if subsequent_highs:
                high = subsequent_highs[-1]
                pairs.append((low, high))
        if not pairs:
            return {"line": None, "swing": None, "direction": "BEARISH"}
        swing, caused_high = pairs[-1]
        return {
            "line": swing["price"],
            "swing": deepcopy(swing),
            "caused_pullback_extreme": deepcopy(caused_high),
            "direction": "BEARISH",
            "line_type": "M5_EXTERNAL_CHOCH_LINE",
        }

    def _m5_post_choch_range(
        self,
        candles: Sequence[Dict[str, Any]],
        h1_poi: Optional[Dict[str, Any]],
        h1_bias: str,
        choch_index: Optional[int],
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Note 9 post-CHoCH range:
        Bullish: Strong Low is the lowest wick inside H1 POI; Weak High is
        where the CHoCH impulse stalls and begins pulling back.
        Bearish: mirror the stated Strong High -> Weak Low structure.
        """
        if not candles or not h1_poi or choch_index is None:
            return {"valid": False, "strong": None, "weak": None}

        in_zone = [
            (index, candle) for index, candle in enumerate(candles)
            if candle["low"] <= h1_poi["upper"] and candle["high"] >= h1_poi["lower"]
        ]
        if not in_zone:
            return {"valid": False, "strong": None, "weak": None}

        post_break = [
            (index, candle) for index, candle in enumerate(candles)
            if index >= choch_index
        ]
        if not post_break:
            return {"valid": False, "strong": None, "weak": None}

        if h1_bias == "BULLISH":
            lowest_index, lowest_candle = min(in_zone, key=lambda pair: pair[1]["low"])
            # The highest high after the CHoCH is the current impulse extreme;
            # pivot confirmation is preferred where available.
            post_highs = [s for s in swings["highs"] if s["index"] >= choch_index]
            if post_highs:
                weak = post_highs[-1]
            else:
                weak_index, weak_candle = max(post_break, key=lambda pair: pair[1]["high"])
                weak = {"price": weak_candle["high"], "index": weak_index,
                        "timestamp": weak_candle.get("timestamp"), "type": "WEAK_HIGH"}
            strong = {"price": lowest_candle["low"], "index": lowest_index,
                      "timestamp": lowest_candle.get("timestamp"), "type": "STRONG_LOW"}
            return {"valid": weak["price"] > strong["price"], "strong": strong, "weak": weak}

        highest_index, highest_candle = max(in_zone, key=lambda pair: pair[1]["high"])
        post_lows = [s for s in swings["lows"] if s["index"] >= choch_index]
        if post_lows:
            weak = post_lows[-1]
        else:
            weak_index, weak_candle = min(post_break, key=lambda pair: pair[1]["low"])
            weak = {"price": weak_candle["low"], "index": weak_index,
                    "timestamp": weak_candle.get("timestamp"), "type": "WEAK_LOW"}
        strong = {"price": highest_candle["high"], "index": highest_index,
                  "timestamp": highest_candle.get("timestamp"), "type": "STRONG_HIGH"}
        return {"valid": strong["price"] > weak["price"], "strong": strong, "weak": weak}

    def analyze_m5(
        self,
        candles: Sequence[Dict[str, Any]],
        h1_result: Dict[str, Any],
        current_price: Optional[float] = None,
        inducement_price: Optional[float] = None,
        live_price_inside_poi: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Notes 8-13:
        M5 external CHoCH inside the H1 POI, dynamic line, body-close
        confirmation, post-CHoCH range, M5 IDM/POI, tap and handover gate.
        """
        if not h1_result or not h1_result.get("handover_to_m5"):
            return self._stage_error("M5", "H1_PREFLIGHT_NOT_SATISFIED", 0)

        data = self.normalize_candles(candles)
        if len(data) < self.swing_strength * 2 + 5:
            return self._stage_error("M5", "INSUFFICIENT_VALID_CANDLES", len(data))

        h1_bias = str(h1_result.get("bias", "UNKNOWN")).upper()
        h1_poi = h1_result.get("poi", {}).get("selected")
        if not h1_poi:
            return self._stage_error("M5", "H1_POI_NOT_AVAILABLE", len(data))

        h1_zone_tap = self.candle_taps_zone(data[-1], h1_poi)
        if live_price_inside_poi is not None:
            h1_zone_tap = bool(live_price_inside_poi)

        if not h1_zone_tap:
            return {
                "success": True,
                "strategy": self.STRATEGY_NAME,
                "timeframe": "M5",
                "bias": h1_bias,
                "waiting_for": "PHYSICAL_TAP_OF_H1_POI",
                "h1_poi_tapped": False,
                "handover_to_m1": False,
                "reason": "M5_EXTERNAL_CONFIRMATION_WAITS_FOR_H1_POI_TAP",
                "notes_implemented": list(range(8, 14)),
            }

        swings = self.detect_swings(data)

        # Note 9.1: dynamic line is recalculated from the latest swing that
        # drove the freshest pullback extreme. This updates if price creates
        # a deeper low (bullish H1) or higher high (bearish H1).
        external = self._find_m5_external_choch_line(data, swings, h1_bias)
        external_line = external.get("line")
        if h1_bias == "BULLISH":
            external_choch = bool(external_line is not None and data[-1]["close"] > external_line)
            choch_direction = "BULLISH"
        else:
            external_choch = bool(external_line is not None and data[-1]["close"] < external_line)
            choch_direction = "BEARISH"

        choch_event = None
        if external_choch:
            choch_event = {
                "type": "CHoCH",
                "direction": choch_direction,
                "level": external_line,
                "index": len(data) - 1,
                "timestamp": data[-1].get("timestamp"),
                "confirmation": "FULL_BODY_CLOSE",
            }

        # The M5 post-CHoCH range is not locked until the body-close event.
        post_range = self._m5_post_choch_range(
            data, h1_poi, h1_bias,
            len(data) - 1 if external_choch else None,
            swings,
        ) if external_choch else {"valid": False, "strong": None, "weak": None}

        if h1_bias == "BULLISH":
            strong = post_range.get("strong")
            weak = post_range.get("weak")
            strong_anchor = strong.get("price") if strong else None
            weak_target = weak.get("price") if weak else None
        else:
            strong = post_range.get("strong")
            weak = post_range.get("weak")
            strong_anchor = strong.get("price") if strong else None
            weak_target = weak.get("price") if weak else None

        price = self._number(current_price)
        if price is None:
            price = data[-1]["close"]

        dealing_range = self.calculate_dealing_range(
            strong_anchor, weak_target, price
        ) if external_choch and post_range.get("valid") else {
            "valid": False,
            "range_low": None,
            "range_high": None,
            "equilibrium": None,
            "zone": "UNKNOWN",
        }

        # Note 10/11: first major internal pullback swing in the new range.
        inferred_idm = None
        if external_choch and weak:
            start_index = weak.get("index", 0)
            inferred_idm = self.identify_internal_inducement(
                swings, h1_bias, start_index
            )
        idm_level = self._number(inducement_price)
        if idm_level is None and inferred_idm:
            idm_level = inferred_idm["price"]

        sweep = self.detect_sweep_of_level(data, idm_level, h1_bias) if external_choch else None

        # Note 10-12: choose unmitigated OB/FVG in the correct half, behind
        # the IDM. Do not enter merely because a zone exists.
        poi = (
            self.select_poi(
                data,
                h1_bias,
                dealing_range.get("equilibrium"),
                idm_level,
                strong_anchor,
                len(data) - 1,
            )
            if external_choch and dealing_range.get("valid")
            else {
                "selected": None,
                "selection": None,
                "reason": "WAITING_FOR_CONFIRMED_M5_EXTERNAL_CHOCH_AND_RANGE",
            }
        )
        selected_poi = poi.get("selected")
        poi_tapped = self.candle_taps_zone(data[-1], selected_poi)
        if live_price_inside_poi is not None and selected_poi:
            poi_tapped = bool(live_price_inside_poi)

        required_location = "DISCOUNT" if h1_bias == "BULLISH" else "PREMIUM"
        location_passed = dealing_range.get("zone") == required_location
        external_passed = external_choch and bool(post_range.get("valid"))
        inducement_passed = sweep is not None
        arrival_passed = bool(
            selected_poi
            and selected_poi.get("unmitigated") is True
            and poi_tapped
        )

        # Note 13: all four conditions are required before dropping to M1.
        preflight = [
            self._condition(
                "5M External Trend",
                external_passed,
                "External CHoCH must close beyond the tracked M5 external line.",
            ),
            self._condition(
                "5M Internal Pullback",
                location_passed,
                "Price must retrace past 50% into Discount/Premium.",
            ),
            self._condition(
                "5M Inducement",
                inducement_passed,
                "The clear internal low/high must be swept.",
            ),
            self._condition(
                "5M Arrival",
                arrival_passed,
                "Live price must be inside the unmitigated Extreme/Decisional 5M POI.",
            ),
        ]

        result = {
            "success": True,
            "strategy": self.STRATEGY_NAME,
            "timeframe": "M5",
            "notes_implemented": list(range(8, 14)),
            "bias": h1_bias,
            "h1_poi": deepcopy(h1_poi),
            "h1_poi_tapped": h1_zone_tap,
            "external_structure": {
                "tracked_swing": deepcopy(external.get("swing")),
                "caused_pullback_extreme": deepcopy(external.get("caused_pullback_extreme")),
                "external_choch_line": external_line,
                "line_type": "M5_EXTERNAL_CHOCH_LINE",
                "dynamic_update_rule": True,
                "choch_confirmed": external_choch,
                "choch_event": choch_event,
                "confirmation": "BODY_CLOSE" if external_choch else "NOT_CONFIRMED",
                "wick_only_is_break": False,
            },
            "dealing_range": dealing_range,
            "strong_swing": deepcopy(strong),
            "weak_swing": deepcopy(weak),
            "equilibrium_50_percent": dealing_range.get("equilibrium"),
            "inducement": {
                "swing": deepcopy(inferred_idm),
                "price": idm_level,
                "sweep": sweep,
                "swept": inducement_passed,
            },
            "poi": poi,
            "poi_tapped": poi_tapped,
            "preflight": preflight,
            "preflight_passed": self._all_passed(preflight),
            "handover_to_m1": self._all_passed(preflight),
            "entry_instruction": (
                "WAIT_FOR_M5_POI_TAP; DO_NOT_PLACE_BLIND_LIMIT_ORDER"
            ),
            "alert_at_poi_edge": deepcopy(selected_poi),
            "evidence_only": True,
        }
        return result

    # ==================================================================
    # 8. M1 STRATEGY - NOTES 14 AND 15
    # ==================================================================

    def detect_m1_displacement(
        self,
        candles: Sequence[Dict[str, Any]],
        direction: str,
        displacement_confirmed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Note 15: a valid M1 CHoCH must show displacement: large full-bodied
        directional candle(s) leaving an FVG. The user's notes do not set a
        numeric 'large candle' threshold. The integrated evidence producer
        may pass displacement_confirmed=True/False; this method independently
        checks body direction and a newly formed directional FVG.
        """
        fvgs = self.detect_fvgs(candles)
        directional_fvgs = [
            gap for gap in fvgs
            if gap["direction"] == direction and gap["unmitigated"]
        ]
        if not candles:
            return {
                "confirmed": False,
                "reason": "NO_M1_CANDLES",
                "directional_fvgs": [],
            }

        latest = candles[-1]
        full_body_direction = self._body_direction(latest) == direction
        fvg_present = bool(directional_fvgs)

        if displacement_confirmed is False:
            confirmed = False
        elif displacement_confirmed is True:
            confirmed = full_body_direction and fvg_present
        else:
            # No fabricated candle-size threshold: evidence requires
            # directional full body plus a directional FVG.
            confirmed = full_body_direction and fvg_present

        return {
            "confirmed": confirmed,
            "direction": direction,
            "full_body_directional_candle": full_body_direction,
            "fvg_left_behind": fvg_present,
            "directional_fvgs": deepcopy(directional_fvgs),
            "external_displacement_confirmation": displacement_confirmed,
            "numeric_size_threshold_invented": False,
        }

    def _find_m1_choch_level(
        self,
        candles: Sequence[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
        direction: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find the last M1 swing against the trade direction that drove price
        into the M5 POI. For buys this is the swing high; for sells the swing
        low. The latest such confirmed swing is the CHoCH line candidate.
        """
        if direction == "BULLISH":
            candidates = swings.get("highs", [])
        else:
            candidates = swings.get("lows", [])

        if not candidates:
            return None

        return deepcopy(candidates[-1])

    def analyze_m1(
        self,
        candles: Sequence[Dict[str, Any]],
        h1_result: Dict[str, Any],
        m5_result: Dict[str, Any],
        current_price: Optional[float] = None,
        final_internal_sweep_level: Optional[float] = None,
        spread_is_tight: Optional[bool] = None,
        session_status: Optional[str] = None,
        red_folder_news_nearby: Optional[bool] = None,
        stopped_out_attempts_in_same_m5_zone: int = 0,
        order_triggered: bool = False,
        previous_attempt_stopped_out: bool = False,
        displacement_confirmed: Optional[bool] = None,
        live_price_inside_m5_poi: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Notes 14-15:
        M1 tap/sweep -> M1 body-close CHoCH -> displacement/FVG -> OB/FVG
        selection -> entry and SL references -> session/spread/news filters
        -> Two-Strike Rule.
        """
        if not h1_result or not h1_result.get("handover_to_m5"):
            return self._stage_error("M1", "H1_HANDOVER_NOT_SATISFIED", 0)
        if not m5_result or not m5_result.get("handover_to_m1"):
            return self._stage_error("M1", "M5_HANDOVER_NOT_SATISFIED", 0)

        data = self.normalize_candles(candles)
        if len(data) < self.swing_strength * 2 + 5:
            return self._stage_error("M1", "INSUFFICIENT_VALID_CANDLES", len(data))

        direction = str(h1_result.get("bias", "UNKNOWN")).upper()
        if not self._valid_direction(direction):
            return self._stage_error("M1", "UNKNOWN_PRO_TREND_DIRECTION", len(data))

        m5_poi = m5_result.get("poi", {}).get("selected")
        price = self._number(current_price)
        if price is None:
            price = data[-1]["close"]

        m5_tap = self.is_price_inside_zone(price, m5_poi)
        if live_price_inside_m5_poi is not None:
            m5_tap = bool(live_price_inside_m5_poi)
        if live_price_inside_m5_poi is None and not m5_tap:
            m5_tap = self.candle_taps_zone(data[-1], m5_poi)

        swings = self.detect_swings(data)
        choch_swing = self._find_m1_choch_level(data, swings, direction)
        choch_level = choch_swing.get("price") if choch_swing else None

        # Note 14: a full body close beyond the last counter-direction swing.
        choch_confirmed = False
        if choch_level is not None:
            if direction == "BULLISH":
                choch_confirmed = data[-1]["close"] > choch_level
            else:
                choch_confirmed = data[-1]["close"] < choch_level

        # Note 14 Step 1: sweep final internal low/high within the 5M zone.
        sweep_level = self._number(final_internal_sweep_level)
        sweep = self.detect_sweep_of_level(data, sweep_level, direction) if sweep_level is not None else None

        # Note 15: displacement + FVG required; slow crawl/chop is not valid.
        displacement = self.detect_m1_displacement(
            data, direction, displacement_confirmed
        )

        # Note 14 Step 3: locate unmitigated M1 OB/FVG from the CHoCH impulse,
        # ideally in the 1M leg's discount/premium half.
        zones = self.collect_poi_candidates(data, direction)
        if choch_confirmed and choch_swing:
            impulse_start = choch_swing.get("index", 0)
            zones = [
                zone for zone in zones
                if zone.get("formation_index", -1) >= impulse_start
            ]

        m1_high = max(candle["high"] for candle in data)
        m1_low = min(candle["low"] for candle in data)
        m1_equilibrium = (m1_high + m1_low) / 2.0

        if direction == "BULLISH":
            preferred_zones = [
                zone for zone in zones
                if zone["midpoint"] < m1_equilibrium
            ]
        else:
            preferred_zones = [
                zone for zone in zones
                if zone["midpoint"] > m1_equilibrium
            ]

        # Use the most recent qualifying zone from the CHoCH impulse.
        entry_zone = (
            max(preferred_zones, key=lambda zone: zone["formation_index"])
            if preferred_zones else None
        )

        # Entry at proximal edge: upper edge for a bullish demand zone,
        # lower edge for a bearish supply zone.
        if entry_zone and direction == "BULLISH":
            entry_price_reference = entry_zone["upper"]
        elif entry_zone:
            entry_price_reference = entry_zone["lower"]
        else:
            entry_price_reference = None

        # SL beyond the M1 structural swing formed inside the 5M POI.
        if direction == "BULLISH":
            lows_inside_poi = [
                swing for swing in swings["lows"]
                if m5_poi
                and swing["price"] >= m5_poi["lower"]
                and swing["price"] <= m5_poi["upper"]
            ]
            structural_stop_swing = (
                min(lows_inside_poi, key=lambda swing: swing["price"])
                if lows_inside_poi else None
            )
        else:
            highs_inside_poi = [
                swing for swing in swings["highs"]
                if m5_poi
                and swing["price"] >= m5_poi["lower"]
                and swing["price"] <= m5_poi["upper"]
            ]
            structural_stop_swing = (
                max(highs_inside_poi, key=lambda swing: swing["price"])
                if highs_inside_poi else None
            )

        stop_reference = (
            structural_stop_swing["price"] if structural_stop_swing else None
        )

        # Session values are expected in SAST from the session component.
        allowed_sessions = {"LONDON_OPEN", "NEW_YORK_OPEN"}
        normalized_session = str(session_status or "").strip().upper()
        session_passed = normalized_session in allowed_sessions

        # The market-data component supplies the tight-spread boolean.
        spread_passed = spread_is_tight is True

        # The news component supplies whether major red-folder news is nearby.
        news_passed = red_folder_news_nearby is False

        # Note 15 Two-Strike Rule, scoped to the same 5M POI.
        strikes = max(0, int(stopped_out_attempts_in_same_m5_zone))
        if strikes >= 2:
            two_strike_passed = False
            reentry_allowed = False
            step_away = True
        elif strikes == 1:
            reentry_allowed = bool(
                previous_attempt_stopped_out
                and order_triggered
                and m5_tap
                and choch_confirmed
                and displacement["confirmed"]
            )
            two_strike_passed = reentry_allowed
            step_away = not reentry_allowed
        else:
            reentry_allowed = False
            two_strike_passed = True
            step_away = False

        # The first attempt is only eligible after the complete entry model.
        entry_model_passed = bool(
            m5_tap
            and sweep
            and choch_confirmed
            and displacement["confirmed"]
            and entry_zone
            and stop_reference is not None
        )

        filters = [
            self._condition("M5 POI Tap", m5_tap,
                            "Price must physically reach the 5M POI."),
            self._condition("M1 Final Liquidity Sweep", sweep is not None,
                            "Sweep the final internal low for buys or high for sells."),
            self._condition("M1 CHoCH Body Close", choch_confirmed,
                            "Close beyond the last counter-direction M1 swing."),
            self._condition("M1 Displacement + FVG", displacement["confirmed"],
                            "Large full-bodied displacement must leave an FVG."),
            self._condition("M1 Unmitigated OB/FVG", entry_zone is not None,
                            "Select an unmitigated M1 OB/FVG from the CHoCH impulse."),
            self._condition("London/New York Open SAST", session_passed,
                            "Avoid Asian session; session status is interpreted in SAST."),
            self._condition("Tight Spread", spread_passed,
                            "1M execution requires tight spread."),
            self._condition("No Nearby Major Red-Folder News", news_passed,
                            "Avoid entries around major red-folder releases."),
            self._condition("Two-Strike Rule", two_strike_passed,
                            "At most one re-entry in the same 5M POI."),
        ]

        result = {
            "success": True,
            "strategy": self.STRATEGY_NAME,
            "timeframe": "M1",
            "notes_implemented": [14, 15],
            "bias": direction,
            "m5_poi": deepcopy(m5_poi),
            "m5_poi_tapped": m5_tap,
            "step_1_tap_and_sweep": {
                "tap_5m_poi": m5_tap,
                "final_internal_sweep_level": sweep_level,
                "sweep_evidence": sweep,
                "passed": bool(m5_tap and sweep),
            },
            "step_2_choch": {
                "last_counter_direction_swing": deepcopy(choch_swing),
                "level": choch_level,
                "body_close_confirmed": choch_confirmed,
                "confirmation": "BODY_CLOSE" if choch_confirmed else "NOT_CONFIRMED",
                "wick_only_is_valid": False,
            },
            "step_3_entry_zone": {
                "selected": deepcopy(entry_zone),
                "entry_price_reference": entry_price_reference,
                "equilibrium_50_percent": m1_equilibrium,
                "preferred_half": "DISCOUNT" if direction == "BULLISH" else "PREMIUM",
                "unmitigated": bool(entry_zone and entry_zone.get("unmitigated")),
            },
            "step_4_execution_references": {
                "entry_method": "LIMIT_AT_PROXIMAL_EDGE",
                "market_entry_allowed_if": "PRICE_TAPS_ZONE_WITH_IMMEDIATE_REJECTION",
                "stop_loss_swing": deepcopy(structural_stop_swing),
                "stop_loss_reference": stop_reference,
                "spread_buffer": "1-2 pips/points",
            },
            "displacement": displacement,
            "session_filter": {
                "session_status": normalized_session or None,
                "timezone": self.SAST_LABEL,
                "timezone_name": self.TIMEZONE,
                "allowed_sessions": ["LONDON_OPEN", "NEW_YORK_OPEN"],
                "asian_session_allowed": False,
                "passed": session_passed,
            },
            "spread_filter": {
                "spread_is_tight": spread_is_tight,
                "passed": spread_passed,
            },
            "red_folder_news_filter": {
                "red_folder_news_nearby": red_folder_news_nearby,
                "passed": news_passed,
            },
            "two_strike_rule": {
                "stopped_out_attempts_in_same_5m_poi": strikes,
                "order_triggered": bool(order_triggered),
                "previous_attempt_stopped_out": bool(previous_attempt_stopped_out),
                "reentry_allowed": reentry_allowed,
                "step_away_from_zone": step_away,
                "zone_likely_failing_after_two_stops": strikes >= 2,
            },
            "filters": filters,
            "entry_model_passed": entry_model_passed,
            "m1_entry_setup_ready": entry_model_passed and self._all_passed(filters),
            "evidence_only": True,
        }
        return result

    # ==================================================================
    # 9. NOTE 16 - THREE-TIMEFRAME ALIGNMENT RECAP
    # ==================================================================

    @staticmethod
    def alignment_recap(
        h1_result: Dict[str, Any],
        m5_result: Optional[Dict[str, Any]],
        m1_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return the exact three-timeframe roles and handover status."""
        h1_ready = bool(h1_result and h1_result.get("handover_to_m5"))
        m5_ready = bool(m5_result and m5_result.get("handover_to_m1"))
        m1_ready = bool(m1_result and m1_result.get("m1_entry_setup_ready"))

        return {
            "note": 16,
            "strategy": "PRO_TREND",
            "timeframes": [
                {
                    "timeframe": "H1",
                    "role": "MACRO_BIAS_AND_LOCATION",
                    "sequence": [
                        "H1 BOS",
                        "Pullback into H1 Discount/Premium",
                        "Sweep H1 IDM",
                        "Tap H1 POI",
                    ],
                    "handover_to_next": h1_ready,
                },
                {
                    "timeframe": "M5",
                    "role": "INTERMEDIATE_CONFIRMATION",
                    "sequence": [
                        "5M External CHoCH",
                        "Pullback into 5M Discount/Premium",
                        "Sweep 5M IDM",
                        "Tap 5M POI",
                    ],
                    "handover_to_next": m5_ready,
                },
                {
                    "timeframe": "M1",
                    "role": "SNIPER_ENTRY_TRIGGER",
                    "sequence": [
                        "1M CHoCH with displacement",
                        "Limit Entry on 1M OB/FVG",
                        "SL beyond 1M swing",
                    ],
                    "entry_setup_ready": m1_ready,
                },
            ],
            "all_timeframes_aligned": h1_ready and m5_ready and m1_ready,
            "rule": "M1 is not an independent setup; H1 and M5 handovers must be satisfied first.",
        }

    # ==================================================================
    # 10. COMPLETE STRATEGY ORCHESTRATION
    # ==================================================================

    def analyze(
        self,
        h1_candles: Sequence[Dict[str, Any]],
        m5_candles: Sequence[Dict[str, Any]],
        m1_candles: Sequence[Dict[str, Any]],
        previous_h1_bias: str = "UNKNOWN",
        current_price_h1: Optional[float] = None,
        current_price_m5: Optional[float] = None,
        current_price_m1: Optional[float] = None,
        h1_inducement_price: Optional[float] = None,
        m5_inducement_price: Optional[float] = None,
        m1_final_sweep_level: Optional[float] = None,
        h1_live_price_inside_poi: Optional[bool] = None,
        m5_live_price_inside_poi: Optional[bool] = None,
        m1_live_price_inside_m5_poi: Optional[bool] = None,
        spread_is_tight: Optional[bool] = None,
        session_status: Optional[str] = None,
        red_folder_news_nearby: Optional[bool] = None,
        stopped_out_attempts_in_same_m5_zone: int = 0,
        order_triggered: bool = False,
        previous_attempt_stopped_out: bool = False,
        m1_displacement_confirmed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Run Pro-Trend in strict sequence:
          H1 complete -> M5 allowed.
          M5 complete -> M1 allowed.
          M1 complete -> report setup evidence.
        """
        h1 = self.analyze_h1(
            h1_candles,
            previous_bias=previous_h1_bias,
            current_price=current_price_h1,
            inducement_price=h1_inducement_price,
            live_price_inside_poi=h1_live_price_inside_poi,
        )

        if not h1.get("handover_to_m5"):
            result = {
                "success": True,
                "strategy": self.STRATEGY_NAME,
                "version": self.VERSION,
                "stage": "H1",
                "next_action": "REMAIN_ON_H1_AND_MONITOR",
                "h1": h1,
                "m5": None,
                "m1": None,
                "alignment": self.alignment_recap(h1, None, None),
                "pro_trend_setup_ready": False,
                "execution_authorized": False,
                "notes_included": list(range(1, 17)),
            }
            self.last_result = deepcopy(result)
            return result

        m5 = self.analyze_m5(
            m5_candles,
            h1,
            current_price=current_price_m5,
            inducement_price=m5_inducement_price,
            live_price_inside_poi=m5_live_price_inside_poi,
        )

        if not m5.get("handover_to_m1"):
            result = {
                "success": True,
                "strategy": self.STRATEGY_NAME,
                "version": self.VERSION,
                "stage": "M5",
                "next_action": "REMAIN_ON_M5_AND_MONITOR",
                "h1": h1,
                "m5": m5,
                "m1": None,
                "alignment": self.alignment_recap(h1, m5, None),
                "pro_trend_setup_ready": False,
                "execution_authorized": False,
                "notes_included": list(range(1, 17)),
            }
            self.last_result = deepcopy(result)
            return result

        m1 = self.analyze_m1(
            m1_candles,
            h1,
            m5,
            current_price=current_price_m1,
            final_internal_sweep_level=m1_final_sweep_level,
            spread_is_tight=spread_is_tight,
            session_status=session_status,
            red_folder_news_nearby=red_folder_news_nearby,
            stopped_out_attempts_in_same_m5_zone=stopped_out_attempts_in_same_m5_zone,
            order_triggered=order_triggered,
            previous_attempt_stopped_out=previous_attempt_stopped_out,
            displacement_confirmed=m1_displacement_confirmed,
            live_price_inside_m5_poi=m1_live_price_inside_m5_poi,
        )

        alignment = self.alignment_recap(h1, m5, m1)
        setup_ready = bool(m1.get("m1_entry_setup_ready"))

        result = {
            "success": True,
            "strategy": self.STRATEGY_NAME,
            "version": self.VERSION,
            "stage": "M1",
            "next_action": "M1_SETUP_READY" if setup_ready else "WAIT_FOR_M1_CONFIRMATION",
            "h1": h1,
            "m5": m5,
            "m1": m1,
            "alignment": alignment,
            "pro_trend_setup_ready": setup_ready,
            "execution_authorized": False,
            "evidence_only": True,
            "notes_included": list(range(1, 17)),
        }
        self.last_result = deepcopy(result)
        return result

    # British spelling compatibility for existing project conventions.
    def analyse(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.analyze(*args, **kwargs)

    # ==================================================================
    # 11. COMMON ERROR RESPONSE AND INTROSPECTION
    # ==================================================================

    def _stage_error(
        self,
        timeframe: str,
        reason: str,
        candle_count: int,
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "strategy": self.STRATEGY_NAME,
            "version": self.VERSION,
            "timeframe": timeframe,
            "reason": reason,
            "candles_analyzed": candle_count,
            "handover_to_m5": False,
            "handover_to_m1": False,
            "m1_entry_setup_ready": False,
            "evidence_only": True,
        }

    @classmethod
    def get_strategy_notes(cls) -> Dict[int, str]:
        """Expose the complete sixteen-note strategy index."""
        return deepcopy(cls.NOTE_MAP)

    @classmethod
    def get_strategy_metadata(cls) -> Dict[str, Any]:
        return {
            "name": cls.STRATEGY_NAME,
            "version": cls.VERSION,
            "timeframes": ["H1", "M5", "M1"],
            "note_count": 16,
            "notes": deepcopy(cls.NOTE_MAP),
            "sequence": ["H1", "M5", "M1"],
            "broker_order_placement_included": False,
            "execution_authorization_included": False,
        }


# ======================================================================
# SHARED INSTANCE - MATCHES EXISTING VROTEX MODULE CONVENTION
# ======================================================================

pro_trend_strategy = ProTrendStrategy()
technical_analysis_pro_trend = pro_trend_strategy


def analyze_pro_trend(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Module-level convenience function."""
    return pro_trend_strategy.analyze(*args, **kwargs)


def analyse_pro_trend(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """British-spelling compatibility alias."""
    return pro_trend_strategy.analyze(*args, **kwargs)


__all__ = [
    "ProTrendStrategy",
    "pro_trend_strategy",
    "technical_analysis_pro_trend",
    "analyze_pro_trend",
    "analyse_pro_trend",
]
