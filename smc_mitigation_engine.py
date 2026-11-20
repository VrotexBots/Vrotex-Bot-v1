"""
VROTEX BOT V1
SMC Mitigation Engine

Purpose:
- Track mitigation of bullish and bearish SMC zones.
- Detect first touch, partial mitigation, midpoint mitigation
  and full mitigation.
- Distinguish mitigation from zone invalidation.
- Preserve the original zone boundaries.
- Return structured evidence for the master SMC engine.

Important:
- Mitigation is not automatically invalidation.
- A wick entering a zone is a mitigation event.
- A full candle-body close beyond the invalidation boundary
  invalidates the zone.
- This module does not authorize or execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCMitigationEngine:
    VERSION = "2.0"

    VALID_DIRECTIONS = {"BULLISH", "BEARISH"}

    def __init__(
        self,
        midpoint_mitigation: bool = True,
    ):
        self.midpoint_mitigation = bool(midpoint_mitigation)

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)

            if result != result or abs(result) == float("inf"):
                return None

            return result

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalise_direction(value: Any) -> Optional[str]:
        direction = str(value or "").upper()

        if direction in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if direction in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    def _normalise_zone(
        self,
        zone: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(zone, dict):
            return None

        lower = self._number(
            zone.get("lower", zone.get("low"))
        )

        upper = self._number(
            zone.get("upper", zone.get("high"))
        )

        direction = self._normalise_direction(
            zone.get("direction")
        )

        if lower is None or upper is None:
            return None

        if lower >= upper or direction is None:
            return None

        return {
            "zone_id": zone.get("zone_id", zone.get("id")),
            "zone_type": str(
                zone.get("zone_type", zone.get("type", "UNKNOWN"))
            ).upper(),
            "direction": direction,
            "lower": lower,
            "upper": upper,
            "midpoint": (lower + upper) / 2,
            "original": zone,
        }

    def _normalise_candles(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        result = []

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

            result.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })

        return result

    @staticmethod
    def _overlaps_zone(
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> bool:
        return (
            candle["high"] >= zone["lower"]
            and candle["low"] <= zone["upper"]
        )

    def _invalidation_check(
        self,
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> bool:
        if zone["direction"] == "BULLISH":
            return candle["close"] < zone["lower"]

        return candle["close"] > zone["upper"]

    @staticmethod
    def _penetration(
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> float:
        zone_size = zone["upper"] - zone["lower"]

        if zone_size <= 0:
            return 0.0

        if zone["direction"] == "BULLISH":
            penetration = zone["upper"] - candle["low"]
        else:
            penetration = candle["high"] - zone["lower"]

        penetration = max(0.0, min(zone_size, penetration))

        return penetration / zone_size

    def analyse_zone(
        self,
        zone: Dict[str, Any],
        candles: List[Dict[str, Any]],
        formation_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalised_zone = self._normalise_zone(zone)

        if normalised_zone is None:
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "INVALID_ZONE",
            }

        if not isinstance(candles, list):
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "INVALID_CANDLE_INPUT",
            }

        normalised_candles = self._normalise_candles(candles)

        if not normalised_candles:
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "NO_VALID_CANDLES",
            }

        if formation_index is None:
            start_index = 0
        else:
            try:
                formation_index = int(formation_index)
            except (TypeError, ValueError):
                return {
                    "status": "ERROR",
                    "valid": False,
                    "reason": "INVALID_FORMATION_INDEX",
                }

            if formation_index < -1 or formation_index >= len(normalised_candles):
                return {
                    "status": "ERROR",
                    "valid": False,
                    "reason": "FORMATION_INDEX_OUT_OF_RANGE",
                }

            start_index = formation_index + 1

        events = []
        first_touch_index = None
        maximum_penetration = 0.0
        invalidated = False
        invalidation_index = None

        for index in range(start_index, len(normalised_candles)):
            candle = normalised_candles[index]

            if self._invalidation_check(candle, normalised_zone):
                invalidated = True
                invalidation_index = index

                events.append({
                    "index": index,
                    "event": "ZONE_INVALIDATED",
                    "close": candle["close"],
                })

                break

            if not self._overlaps_zone(candle, normalised_zone):
                continue

            penetration = self._penetration(
                candle,
                normalised_zone,
            )

            maximum_penetration = max(
                maximum_penetration,
                penetration,
            )

            if first_touch_index is None:
                first_touch_index = index

                events.append({
                    "index": index,
                    "event": "FIRST_TOUCH",
                    "penetration": round(penetration, 4),
                })

            if penetration >= 1.0:
                stage = "FULL_MITIGATION"

            elif penetration >= 0.5:
                stage = "MIDPOINT_MITIGATION"

            else:
                stage = "PARTIAL_MITIGATION"

            events.append({
                "index": index,
                "event": stage,
                "penetration": round(penetration, 4),
            })

        if invalidated:
            status = "INVALIDATED"
            mitigation_state = "INVALIDATED"

        elif first_touch_index is None:
            status = "UNMITIGATED"
            mitigation_state = "UNMITIGATED"

        elif maximum_penetration >= 1.0:
            status = "FULLY_MITIGATED"
            mitigation_state = "FULL"

        elif maximum_penetration >= 0.5:
            status = "MIDPOINT_MITIGATED"
            mitigation_state = "MIDPOINT"

        else:
            status = "PARTIALLY_MITIGATED"
            mitigation_state = "PARTIAL"

        clean = (
            first_touch_index is None
            and not invalidated
        )

        return {
            "status": status,
            "version": self.VERSION,
            "valid": True,
            "zone_id": normalised_zone["zone_id"],
            "zone_type": normalised_zone["zone_type"],
            "direction": normalised_zone["direction"],
            "lower": normalised_zone["lower"],
            "upper": normalised_zone["upper"],
            "midpoint": normalised_zone["midpoint"],
            "first_touch_index": first_touch_index,
            "invalidation_index": invalidation_index,
            "maximum_penetration": round(
                maximum_penetration,
                4,
            ),
            "mitigation_state": mitigation_state,
            "mitigated": first_touch_index is not None,
            "unmitigated": clean,
            "clean": clean,
            "invalidated": invalidated,
            "events": events,
            "confirmation": status,
        }

    def analyse(
        self,
        zones: List[Dict[str, Any]],
        candles: List[Dict[str, Any]],
        formation_indices: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(zones, list):
            return {
                "status": "ERROR",
                "reason": "INVALID_ZONES_INPUT",
                "zones": [],
            }

        if not isinstance(candles, list):
            return {
                "status": "ERROR",
                "reason": "INVALID_CANDLE_INPUT",
                "zones": [],
            }

        results = []

        for index, zone in enumerate(zones):
            formation_index = None

            if formation_indices is not None:
                if index < len(formation_indices):
                    formation_index = formation_indices[index]

            result = self.analyse_zone(
                zone=zone,
                candles=candles,
                formation_index=formation_index,
            )

            results.append(result)

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "zone_count": len(results),
            "unmitigated_zones": [
                item for item in results
                if item.get("unmitigated")
            ],
            "partially_mitigated_zones": [
                item for item in results
                if item.get("mitigation_state") == "PARTIAL"
            ],
            "midpoint_mitigated_zones": [
                item for item in results
                if item.get("mitigation_state") == "MIDPOINT"
            ],
            "fully_mitigated_zones": [
                item for item in results
                if item.get("mitigation_state") == "FULL"
            ],
            "invalidated_zones": [
                item for item in results
                if item.get("invalidated")
            ],
            "zones": results,
        }

    def analyze(
        self,
        zones: List[Dict[str, Any]],
        candles: List[Dict[str, Any]],
        formation_indices: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        return self.analyse(
            zones,
            candles,
            formation_indices,
        )


smc_mitigation_engine = SMCMitigationEngine()
