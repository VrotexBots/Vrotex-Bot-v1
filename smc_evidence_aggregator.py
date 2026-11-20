
"""
VROTEX BOT V1
SMC Evidence Aggregator

Version: 3.0

Purpose:
- Collect evidence from the individual SMC engines.
- Pass raw evidence through the integration adapter.
- Maintain consistent evidence structure.
- Reject incomplete or contradictory evidence.
- Preserve source evidence for auditing.

Strategy:
H1 = External narrative
M5 = External CHoCH confirmation
M1 = Entry-model confirmation

No order execution is performed here.
"""

from typing import Any, Dict, Optional

from logging_config import get_logger
from smc_integration_adapter import smc_integration_adapter


logger = get_logger("smc_evidence_aggregator")


class SMCEvidenceAggregator:

    VERSION = "3.0"

    def __init__(self, adapter=None):

        self.adapter = (
            adapter
            or smc_integration_adapter
        )

        self.last_result: Dict[str, Any] = {}

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:

        return (
            value
            if isinstance(value, dict)
            else {}
        )

    @staticmethod
    def _direction(value: Any) -> Optional[str]:

        return smc_integration_adapter.direction(
            value
        )

    @staticmethod
    def _get_h1_direction(
        timeframe_evidence: Dict[str, Any],
    ) -> Optional[str]:

        h1 = timeframe_evidence.get(
            "H1",
            timeframe_evidence.get("h1", {}),
        )

        h1 = (
            h1
            if isinstance(h1, dict)
            else {}
        )

        structure = h1.get("structure", {})

        structure = (
            structure
            if isinstance(structure, dict)
            else {}
        )

        return smc_integration_adapter.direction(
            h1.get("direction")
            or h1.get("bias")
            or structure.get("bias")
            or structure.get("direction")
        )

    # --------------------------------------------------
    # MAIN AGGREGATION
    # --------------------------------------------------

    def aggregate(
        self,
        timeframe_evidence: Dict[str, Any],
        liquidity_evidence: Any = None,
        poi_evidence: Any = None,
        fvg_evidence: Any = None,
        displacement_evidence: Any = None,
        entry_evidence: Any = None,
        risk_evidence: Any = None,
        expected_direction: Optional[str] = None,
        instrument: Optional[str] = None,
    ) -> Dict[str, Any]:

        timeframe_evidence = self._as_dict(
            timeframe_evidence
        )

        h1 = self._as_dict(
            timeframe_evidence.get(
                "H1",
                timeframe_evidence.get("h1"),
            )
        )

        m5 = self._as_dict(
            timeframe_evidence.get(
                "M5",
                timeframe_evidence.get("m5"),
            )
        )

        m1 = self._as_dict(
            timeframe_evidence.get(
                "M1",
                timeframe_evidence.get("m1"),
            )
        )

        direction = (
            self._direction(expected_direction)
            or self._get_h1_direction(
                timeframe_evidence
            )
        )

        if direction is None:

            result = {
                "status": "REJECTED",
                "version": self.VERSION,
                "valid": False,
                "confirmed": False,
                "direction": None,
                "instrument": instrument,
                "reason": "H1_DIRECTION_UNAVAILABLE",
                "failed_checks": [
                    "h1_external_narrative"
                ],
                "execution_authorized": False,
            }

            self.last_result = result

            logger.warning(
                "SMC evidence rejected: H1 direction unavailable"
            )

            return result

        # --------------------------------------------------
        # NORMALIZE ALL EVIDENCE
        # --------------------------------------------------

        evidence = self.adapter.build_evidence(
            trade_direction=direction,
            h1_structure=h1,
            m5_structure=m5,
            m1_structure=m1,
            liquidity=liquidity_evidence,
            fvg=fvg_evidence,
            poi=poi_evidence,
            displacement=displacement_evidence,
            entry_models=entry_evidence,
            risk_checks=risk_evidence,
        )

        evidence = self._as_dict(evidence)

        valid = evidence.get("valid") is True

        result = {
            "status": (
                "AGGREGATION_CONFIRMED"
                if valid
                else "AGGREGATION_REJECTED"
            ),

            "version": self.VERSION,

            "valid": valid,

            "confirmed": valid,

            "instrument": instrument,

            "direction": direction,

            "checks": evidence.get(
                "checks",
                {},
            ),

            "failed_checks": evidence.get(
                "failed_checks",
                [],
            ),

            "passed_count": evidence.get(
                "passed_count",
                0,
            ),

            "total_checks": evidence.get(
                "total_checks",
                0,
            ),

            "H1": evidence.get("H1", {}),

            "M5": evidence.get("M5", {}),

            "M1": evidence.get("M1", {}),

            "liquidity": evidence.get(
                "liquidity",
                {},
            ),

            "zones": {
                "poi": evidence.get("poi", {}),
                "fvg": evidence.get("fvg", {}),
            },

            "displacement": evidence.get(
                "displacement",
                {},
            ),

            "entry": evidence.get(
                "entry",
                {},
            ),

            "risk": evidence.get(
                "risk",
                {},
            ),

            "source_evidence": {
                "timeframes": timeframe_evidence,
                "liquidity": liquidity_evidence,
                "poi": poi_evidence,
                "fvg": fvg_evidence,
                "displacement": displacement_evidence,
                "entry": entry_evidence,
                "risk": risk_evidence,
            },

            "execution_authorized": False,
        }

        result["reason"] = (
            "ALL_REQUIRED_EVIDENCE_CONFIRMED"
            if valid
            else "REQUIRED_EVIDENCE_MISSING_OR_INVALID"
        )

        self.last_result = result

        if valid:

            logger.info(
                "SMC evidence confirmed: %s %s",
                instrument,
                direction,
            )

        else:

            logger.info(
                "SMC evidence rejected: %s | Failed: %s",
                instrument,
                result["failed_checks"],
            )

        return result

    # --------------------------------------------------
    # COMPATIBILITY ALIAS
    # --------------------------------------------------

    def analyze(self, *args, **kwargs):

        return self.aggregate(
            *args,
            **kwargs,
        )

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:

        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:

        return {
            "module": "SMCEvidenceAggregator",
            "version": self.VERSION,
            "status": "READY",
            "execution_authorized": False,
        }


smc_evidence_aggregator = SMCEvidenceAggregator()
