"""
Vrotex Bot V1
SMC Timeframe Alignment Engine

Approved strategy:
H1 -> M5 -> M1

H1: External narrative and directional bias.
M5: Confirmation.
M1: Entry direction.

This module evaluates alignment only.
It does not execute or authorize trades.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


VALID_DIRECTIONS = {
    "BULLISH",
    "BEARISH",
    "NEUTRAL",
    "UNKNOWN",
}


class SMCTimeframeAlignmentEngine:

    def __init__(self):
        self.last_result: Optional[Dict[str, Any]] = None

    @staticmethod
    def _normalize_direction(value: Any) -> str:
        if not isinstance(value, str):
            return "UNKNOWN"

        direction = value.strip().upper()

        if direction in VALID_DIRECTIONS:
            return direction

        return "UNKNOWN"

    def evaluate(
        self,
        h1: Dict[str, Any],
        m5: Dict[str, Any],
        m1: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not all(
            isinstance(item, dict)
            for item in (h1, m5, m1)
        ):
            raise ValueError("All timeframe inputs must be dictionaries")

        h1_direction = self._normalize_direction(
            h1.get("direction", h1.get("bias"))
        )

        m5_direction = self._normalize_direction(
            m5.get("direction", m5.get("bias"))
        )

        m1_direction = self._normalize_direction(
            m1.get("direction", m1.get("bias"))
        )

        reasons = []

        if "UNKNOWN" in (
            h1_direction,
            m5_direction,
            m1_direction,
        ):
            reasons.append("MISSING_OR_INVALID_TIMEFRAME_DIRECTION")

        if "NEUTRAL" in (
            h1_direction,
            m5_direction,
            m1_direction,
        ):
            reasons.append("NEUTRAL_TIMEFRAME_DIRECTION")

        aligned = (
            h1_direction == m5_direction == m1_direction
            and h1_direction in ("BULLISH", "BEARISH")
        )

        if aligned:
            reasons.append("ALL_TIMEFRAMES_ALIGNED")

        elif not reasons:
            reasons.append("TIMEFRAME_DIRECTION_CONFLICT")

        confirmation = (
            h1_direction == m5_direction
            and h1_direction in ("BULLISH", "BEARISH")
        )

        entry_matches_confirmation = (
            m5_direction == m1_direction
            and m5_direction in ("BULLISH", "BEARISH")
        )

        if not confirmation:
            reasons.append("H1_M5_CONFIRMATION_MISSING")

        if not entry_matches_confirmation:
            reasons.append("M5_M1_ENTRY_ALIGNMENT_MISSING")

        result = {
            "strategy_timeframes": ["H1", "M5", "M1"],
            "directions": {
                "H1": h1_direction,
                "M5": m5_direction,
                "M1": m1_direction,
            },
            "h1_m5_confirmation": confirmation,
            "m5_m1_entry_alignment": entry_matches_confirmation,
            "fully_aligned": aligned,
            "trade_direction": (
                h1_direction if aligned else None
            ),
            "status": (
                "FULLY_ALIGNED"
                if aligned
                else "NOT_ALIGNED"
            ),
            "reasons": reasons,
        }

        self.last_result = result

        return result

    def get_status(self) -> Dict[str, Any]:

        return {
            "engine": "SMC_TIMEFRAME_ALIGNMENT_ENGINE",
            "strategy_timeframes": ["H1", "M5", "M1"],
            "last_result": self.last_result,
            "initialized": True,
        }


# Shared engine instance
smc_timeframe_alignment_engine = SMCTimeframeAlignmentEngine()


def evaluate_timeframe_alignment(
    h1: Dict[str, Any],
    m5: Dict[str, Any],
    m1: Dict[str, Any],
) -> Dict[str, Any]:

    return smc_timeframe_alignment_engine.evaluate(
        h1,
        m5,
        m1,
    )
