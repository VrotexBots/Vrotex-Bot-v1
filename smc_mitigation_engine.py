"""
Vrotex Bot V1
SMC Mitigation Engine

Tracks mitigation and invalidation of:
- Bullish and bearish Order Blocks
- Bullish and bearish Fair Value Gaps

States:
- UNMITIGATED
- PARTIALLY_MITIGATED
- FULLY_MITIGATED
- INVALIDATED
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


VALID_TYPES = {"ORDER_BLOCK", "FVG"}
VALID_DIRECTIONS = {"BULLISH", "BEARISH"}


@dataclass
class MitigationResult:
    zone_id: str
    zone_type: str
    direction: str
    status: str
    mitigation_percent: float
    first_touch_index: Optional[int]
    last_touch_index: Optional[int]
    invalidation_index: Optional[int]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SMCMitigationEngine:

    def __init__(self):
        self.zones: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _price(value: Any, field: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid {field}")

        if number != number or number in (
            float("inf"),
            float("-inf"),
        ):
            raise ValueError(f"Non-finite {field}")

        return number

    def register_zone(
        self,
        zone_id: str,
        zone_type: str,
        direction: str,
        lower: float,
        upper: float,
        formation_index: int,
    ) -> Dict[str, Any]:

        if not zone_id or not isinstance(zone_id, str):
            raise ValueError("zone_id must be a non-empty string")

        zone_type = zone_type.upper()
        direction = direction.upper()

        if zone_type not in VALID_TYPES:
            raise ValueError("zone_type must be ORDER_BLOCK or FVG")

        if direction not in VALID_DIRECTIONS:
            raise ValueError("direction must be BULLISH or BEARISH")

        lower = self._price(lower, "lower")
        upper = self._price(upper, "upper")

        if lower >= upper:
            raise ValueError("lower must be below upper")

        if not isinstance(formation_index, int) or formation_index < 0:
            raise ValueError("formation_index must be a non-negative integer")

        if zone_id in self.zones:
            raise ValueError(f"Zone already registered: {zone_id}")

        self.zones[zone_id] = {
            "zone_id": zone_id,
            "zone_type": zone_type,
            "direction": direction,
            "lower": lower,
            "upper": upper,
            "formation_index": formation_index,
            "status": "UNMITIGATED",
            "mitigation_percent": 0.0,
            "first_touch_index": None,
            "last_touch_index": None,
            "invalidation_index": None,
        }

        return self.get_zone(zone_id)

    def get_zone(self, zone_id: str) -> Dict[str, Any]:
        if zone_id not in self.zones:
            raise KeyError(f"Unknown zone: {zone_id}")

        return dict(self.zones[zone_id])

    def remove_zone(self, zone_id: str) -> bool:
        return self.zones.pop(zone_id, None) is not None

    @staticmethod
    def _overlaps_zone(
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> bool:
        return (
            candle["high"] >= zone["lower"]
            and candle["low"] <= zone["upper"]
        )

    def _calculate_penetration(
        self,
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> float:

        lower = zone["lower"]
        upper = zone["upper"]
        size = upper - lower

        if size <= 0:
            return 0.0

        if zone["direction"] == "BULLISH":
            penetration = upper - max(candle["low"], lower)
        else:
            penetration = min(candle["high"], upper) - lower

        return max(0.0, min(100.0, (penetration / size) * 100.0))

    def _is_invalidated(
        self,
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> bool:

        if zone["direction"] == "BULLISH":
            return candle["close"] < zone["lower"]

        return candle["close"] > zone["upper"]

    def update_zone(
        self,
        zone_id: str,
        candles: List[Dict[str, Any]],
        start_index: Optional[int] = None,
    ) -> Dict[str, Any]:

        if zone_id not in self.zones:
            raise KeyError(f"Unknown zone: {zone_id}")

        if not isinstance(candles, list):
            raise ValueError("candles must be a list")

        zone = self.zones[zone_id]

        if start_index is None:
            start_index = zone["formation_index"] + 1

        if not isinstance(start_index, int) or start_index < 0:
            raise ValueError("start_index must be non-negative")

        if start_index <= zone["formation_index"]:
            raise ValueError(
                "Mitigation checks must start after zone formation"
            )

        if zone["status"] == "INVALIDATED":
            return self._result(zone, "ZONE_ALREADY_INVALIDATED")

        if zone["status"] == "FULLY_MITIGATED":
            return self._result(zone, "ZONE_ALREADY_FULLY_MITIGATED")

        for index in range(start_index, len(candles)):

            raw = candles[index]

            if not isinstance(raw, dict):
                raise ValueError("Invalid candle")

            candle = {
                field: self._price(raw.get(field), field)
                for field in ("open", "high", "low", "close")
            }

            if candle["high"] < candle["low"]:
                raise ValueError("Candle high cannot be below low")

            if not (
                candle["low"] <= candle["open"] <= candle["high"]
                and candle["low"] <= candle["close"] <= candle["high"]
            ):
                raise ValueError("Invalid candle price range")

            if self._is_invalidated(candle, zone):
                zone["status"] = "INVALIDATED"
                zone["invalidation_index"] = index
                return self._result(
                    zone,
                    "CANDLE_CLOSED_BEYOND_ZONE_BOUNDARY",
                )

            if self._overlaps_zone(candle, zone):

                penetration = self._calculate_penetration(
                    candle,
                    zone,
                )

                zone["mitigation_percent"] = max(
                    zone["mitigation_percent"],
                    penetration,
                )

                if zone["first_touch_index"] is None:
                    zone["first_touch_index"] = index

                zone["last_touch_index"] = index

                if zone["mitigation_percent"] >= 100.0:
                    zone["status"] = "FULLY_MITIGATED"
                    return self._result(
                        zone,
                        "ZONE_FULLY_FILLED",
                    )

                zone["status"] = "PARTIALLY_MITIGATED"

        return self._result(zone, "UPDATE_COMPLETE")

    def _result(
        self,
        zone: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:

        return MitigationResult(
            zone_id=zone["zone_id"],
            zone_type=zone["zone_type"],
            direction=zone["direction"],
            status=zone["status"],
            mitigation_percent=round(
                zone["mitigation_percent"],
                2,
            ),
            first_touch_index=zone["first_touch_index"],
            last_touch_index=zone["last_touch_index"],
            invalidation_index=zone["invalidation_index"],
            reason=reason,
        ).to_dict()

    def update_all(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:

        results = {}

        for zone_id, zone in list(self.zones.items()):
            if zone["status"] in (
                "INVALIDATED",
                "FULLY_MITIGATED",
            ):
                continue

            results[zone_id] = self.update_zone(
                zone_id,
                candles,
            )

        return results

    def get_active_zones(self) -> List[Dict[str, Any]]:
        return [
            dict(zone)
            for zone in self.zones.values()
            if zone["status"] in (
                "UNMITIGATED",
                "PARTIALLY_MITIGATED",
            )
        ]

    def get_status(self) -> Dict[str, Any]:
        counts = {
            "UNMITIGATED": 0,
            "PARTIALLY_MITIGATED": 0,
            "FULLY_MITIGATED": 0,
            "INVALIDATED": 0,
        }

        for zone in self.zones.values():
            counts[zone["status"]] += 1

        return {
            "total_zones": len(self.zones),
            "states": counts,
        }


# Shared engine instance
smc_mitigation_engine = SMCMitigationEngine()
