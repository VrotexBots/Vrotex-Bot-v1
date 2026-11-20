"""
VROTEX BOT V1
SMC Timeframe Alignment Engine

Purpose:
- Validate H1, M5 and M1 directional alignment.
- Keep external narrative separate from entry confirmation.
- Require confirmed M5 structure evidence.
- Check M1 entry context without demanding a fresh M1 BOS/CHoCH.
- Reject missing or contradictory evidence.

Approved V1 strategy:
H1 = External narrative
M5 = Confirmation
M1 = Entry

This module does not authorize or execute orders.
"""

from typing import Any, Dict, Optional


class SMCTimeframeAlignmentEngine:
    VERSION = "2.0"

    TIMEFRAMES = ("H1", "M5", "M1")

    def __init__(self):
        pass

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    def _extract_direction(
        self,
        evidence: Dict[str, Any],
    ) -> Optional[str]:
        if not isinstance(evidence, dict):
            return None

        direction = self._direction(
            evidence.get("direction")
        )

        if direction:
            return direction

        structure = evidence.get("structure")

        if isinstance(structure, dict):
            direction = self._direction(
                structure.get("bias")
                or structure.get("direction")
            )

            if direction:
                return direction

        return self._direction(evidence.get("bias"))

    @staticmethod
    def _extract_breaks(
        evidence: Dict[str, Any],
    ) -> list:
        if not isinstance(evidence, dict):
            return []

        breaks = evidence.get("breaks", [])

        return breaks if isinstance(breaks, list) else []

    def _m5_confirmation(
        self,
        evidence: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:
        breaks = self._extract_breaks(evidence)

        confirmed_breaks = []

        for item in breaks:
            if not isinstance(item, dict):
                continue

            direction = self._direction(item.get("direction"))

            confirmation = str(
                item.get("confirmation", "")
            ).upper()

            break_type = str(
                item.get("type", "")
            ).upper()

            body_close = (
                item.get("body_close_confirmed") is True
                or confirmation == "BODY_CLOSE"
            )

            if (
                direction == expected_direction
                and body_close
                and break_type in (
                    "CHOCH",
                    "BOS",
                    "BULLISH_BREAK",
                    "BEARISH_BREAK",
                )
            ):
                confirmed_breaks.append(item)

        explicit_confirmation = (
            evidence.get("confirmed") is True
            and self._direction(evidence.get("direction"))
            == expected_direction
            and evidence.get("body_close_confirmed") is True
        )

        confirmed = bool(confirmed_breaks) or explicit_confirmation

        return {
            "confirmed": confirmed,
            "expected_direction": expected_direction,
            "matching_breaks": confirmed_breaks,
            "confirmation": (
                "BODY_CLOSE_CONFIRMED"
                if confirmed
                else "M5_CONFIRMATION_MISSING"
            ),
        }

    def _m1_context(
        self,
        evidence: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:
        """
        M1 provides entry context.

        A fresh M1 structure break is not mandatory.
        Entry-model confirmation is evaluated separately.
        """
        direction = self._extract_direction(evidence)

        aligned = (
            direction is None
            or direction == expected_direction
        )

        return {
            "available": bool(evidence),
            "direction": direction or "NEUTRAL",
            "aligned": aligned,
            "fresh_structure_break_required": False,
            "confirmation": (
                "M1_CONTEXT_ALIGNED"
                if aligned and evidence
                else (
                    "M1_CONTEXT_NEUTRAL"
                    if aligned
                    else "M1_DIRECTION_CONFLICT"
                )
            ),
        }

    def analyse(
        self,
        timeframe_evidence: Dict[str, Any],
        expected_direction: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(timeframe_evidence, dict):
            return self._error("INVALID_TIMEFRAME_EVIDENCE")

        h1 = timeframe_evidence.get("H1")
        m5 = timeframe_evidence.get("M5")
        m1 = timeframe_evidence.get("M1")

        if not isinstance(h1, dict):
            return self._error("H1_EVIDENCE_MISSING")

        if not isinstance(m5, dict):
            return self._error("M5_EVIDENCE_MISSING")

        if not isinstance(m1, dict):
            return self._error("M1_EVIDENCE_MISSING")

        h1_direction = self._extract_direction(h1)

        requested_direction = self._direction(
            expected_direction
        )

        if requested_direction is None:
            requested_direction = h1_direction

        if requested_direction is None:
            return self._error("H1_DIRECTION_UNCONFIRMED")

        if (
            h1_direction is not None
            and h1_direction != requested_direction
        ):
            return self._error("H1_DIRECTION_CONFLICT")

        m5_result = self._m5_confirmation(
            m5,
            requested_direction,
        )

        m5_direction = self._extract_direction(m5)

        m5_aligned = (
            m5_direction is None
            or m5_direction == requested_direction
        )

        m1_result = self._m1_context(
            m1,
            requested_direction,
        )

        h1_confirmed = (
            h1.get("confirmed") is not False
            and h1_direction == requested_direction
        )

        aligned = (
            h1_confirmed
            and m5_result["confirmed"]
            and m5_aligned
            and m1_result["aligned"]
        )

        if not h1_confirmed:
            status = "H1_NOT_CONFIRMED"
        elif not m5_result["confirmed"]:
            status = "M5_CONFIRMATION_MISSING"
        elif not m5_aligned:
            status = "M5_DIRECTION_CONFLICT"
        elif not m1_result["aligned"]:
            status = "M1_DIRECTION_CONFLICT"
        else:
            status = "TIMEFRAMES_ALIGNED"

        return {
            "status": status,
            "version": self.VERSION,
            "valid": aligned,
            "confirmed": aligned,
            "direction": requested_direction,
            "timeframes": {
                "H1": {
                    "role": "EXTERNAL_NARRATIVE",
                    "direction": h1_direction,
                    "confirmed": h1_confirmed,
                },
                "M5": {
                    "role": "CONFIRMATION",
                    "direction": m5_direction,
                    **m5_result,
                },
                "M1": {
                    "role": "ENTRY_CONTEXT",
                    **m1_result,
                },
            },
            "checks": {
                "h1_direction_confirmed": h1_confirmed,
                "m5_body_close_confirmation": m5_result["confirmed"],
                "m5_direction_aligned": m5_aligned,
                "m1_context_aligned": m1_result["aligned"],
            },
            "execution_authorized": False,
        }

    def analyze(
        self,
        timeframe_evidence: Dict[str, Any],
        expected_direction: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.analyse(
            timeframe_evidence,
            expected_direction,
        )

    @staticmethod
    def _error(reason: str) -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "version": "2.0",
            "valid": False,
            "confirmed": False,
            "reason": reason,
            "execution_authorized": False,
        }


smc_timeframe_alignment_engine = SMCTimeframeAlignmentEngine()
