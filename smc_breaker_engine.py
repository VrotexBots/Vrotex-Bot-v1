"""
Vrotex Bot V1
SMC Breaker Engine

Detects potential breaker blocks from previously identified
Order Blocks.

Bullish breaker:
- Original bearish Order Block.
- Price closes above its upper boundary.
- Price subsequently retests the broken zone.

Bearish breaker:
- Original bullish Order Block.
- Price closes below its lower boundary.
- Price subsequently retests the broken zone.

A breaker candidate is evidence only. Additional SMC confirmation
is required before any trading decision.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class BreakerResult:
    zone_id: str
    breaker_direction: Optional[str]
    status: str
    lower: float
    upper: float
    formation_index: int
    break_index: Optional[int]
    retest_index: Optional[int]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SMCBreakerEngine:

    def __init__(self):
        self.blocks: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _number(value: Any, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid {field}")

        if result != result or result in (
            float("inf"),
            float("-inf"),
        ):
            raise ValueError(f"Non-finite {field}")

        return result

    @staticmethod
    def _validate_direction(direction: str) -> str:
        direction = direction.upper()

        if direction not in ("BULLISH", "BEARISH"):
            raise ValueError("Direction must be BULLISH or BEARISH")

        return direction

    def register_order_block(
        self,
        zone_id: str,
        original_direction: str,
        lower: float,
        upper: float,
        formation_index: int,
    ) -> Dict[str, Any]:

        if not isinstance(zone_id, str) or not zone_id.strip():
            raise ValueError("zone_id must be a non-empty string")

        if zone_id in self.blocks:
            raise ValueError(f"Order Block already registered: {zone_id}")

        original_direction = self._validate_direction(
            original_direction
        )

        lower = self._number(lower, "lower")
        upper = self._number(upper, "upper")

        if lower >= upper:
            raise ValueError("lower must be below upper")

        if not isinstance(formation_index, int) or formation_index < 0:
            raise ValueError("formation_index must be non-negative")

        self.blocks[zone_id] = {
            "zone_id": zone_id,
            "original_direction": original_direction,
            "breaker_direction": (
                "BULLISH"
                if original_direction == "BEARISH"
                else "BEARISH"
            ),
            "lower": lower,
            "upper": upper,
            "formation_index": formation_index,
            "status": "WAITING_FOR_BREAK",
            "break_index": None,
            "retest_index": None,
        }

        return self.get_block(zone_id)

    def get_block(self, zone_id: str) -> Dict[str, Any]:
        if zone_id not in self.blocks:
            raise KeyError(f"Unknown Order Block: {zone_id}")

        return dict(self.blocks[zone_id])

    def _result(
        self,
        block: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:

        return BreakerResult(
            zone_id=block["zone_id"],
            breaker_direction=block["breaker_direction"],
            status=block["status"],
            lower=block["lower"],
            upper=block["upper"],
            formation_index=block["formation_index"],
            break_index=block["break_index"],
            retest_index=block["retest_index"],
            reason=reason,
        ).to_dict()

    def update_block(
        self,
        zone_id: str,
        candles: List[Dict[str, Any]],
        start_index: Optional[int] = None,
    ) -> Dict[str, Any]:

        if zone_id not in self.blocks:
            raise KeyError(f"Unknown Order Block: {zone_id}")

        if not isinstance(candles, list):
            raise ValueError("candles must be a list")

        block = self.blocks[zone_id]

        if start_index is None:
            start_index = block["formation_index"] + 1

        if not isinstance(start_index, int) or start_index < 0:
            raise ValueError("start_index must be non-negative")

        if start_index <= block["formation_index"]:
            raise ValueError("Start index must follow formation")

        if block["status"] == "BREAKER_RETEST_CONFIRMED":
            return self._result(block, "BREAKER_ALREADY_CONFIRMED")

        if block["status"] == "WAITING_FOR_RETEST":
            scan_start = max(
                start_index,
                block["break_index"] + 1,
            )
        else:
            scan_start = start_index

        for index in range(scan_start, len(candles)):

            raw = candles[index]

            if not isinstance(raw, dict):
                raise ValueError("Invalid candle")

            candle = {
                field: self._number(raw.get(field), field)
                for field in ("open", "high", "low", "close")
            }

            if candle["high"] < candle["low"]:
                raise ValueError("Candle high cannot be below low")

            if not (
                candle["low"] <= candle["open"] <= candle["high"]
                and candle["low"] <= candle["close"] <= candle["high"]
            ):
                raise ValueError("Invalid candle price range")

            if block["status"] == "WAITING_FOR_BREAK":

                if block["breaker_direction"] == "BULLISH":
                    broken = candle["close"] > block["upper"]
                else:
                    broken = candle["close"] < block["lower"]

                if broken:
                    block["status"] = "WAITING_FOR_RETEST"
                    block["break_index"] = index

            elif block["status"] == "WAITING_FOR_RETEST":

                overlaps = (
                    candle["high"] >= block["lower"]
                    and candle["low"] <= block["upper"]
                )

                if overlaps:
                    block["status"] = "BREAKER_RETEST_CONFIRMED"
                    block["retest_index"] = index

                    return self._result(
                        block,
                        "BROKEN_ORDER_BLOCK_RETESTED",
                    )

        return self._result(block, "UPDATE_COMPLETE")

    def update_all(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:

        results = {}

        for zone_id, block in list(self.blocks.items()):

            if block["status"] == "BREAKER_RETEST_CONFIRMED":
                continue

            results[zone_id] = self.update_block(
                zone_id,
                candles,
            )

        return results

    def get_confirmed_breakers(self) -> List[Dict[str, Any]]:
        return [
            dict(block)
            for block in self.blocks.values()
            if block["status"] == "BREAKER_RETEST_CONFIRMED"
        ]

    def get_status(self) -> Dict[str, Any]:

        counts = {
            "WAITING_FOR_BREAK": 0,
            "WAITING_FOR_RETEST": 0,
            "BREAKER_RETEST_CONFIRMED": 0,
        }

        for block in self.blocks.values():
            counts[block["status"]] += 1

        return {
            "total_order_blocks": len(self.blocks),
            "states": counts,
        }


# Shared engine instance
smc_breaker_engine = SMCBreakerEngine()
