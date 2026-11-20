"""
Vrotex Bot V1
SMC Evidence Aggregator

Purpose:
- Standardize evidence from individual SMC engines.
- Collect H1, M5 and M1 directional information.
- Aggregate structure, POI, liquidity and entry evidence.
- Calculate category scores using approved weights.
- Prepare evidence for smc_setup_validator.py.

Missing evidence is never treated as confirmation.
This module does not execute trades.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


CATEGORY_WEIGHTS = {
    "structure": 20,
    "poi": 15,
    "liquidity": 15,
    "entry_model": 20,
    "timeframe_alignment": 15,
    "fundamentals": 5,
    "trade_quality_risk": 10,
}


class SMCEvidenceAggregator:

    def __init__(self):
        self.last_evidence: Optional[Dict[str, Any]] = None

    @staticmethod
    def _direction(value: Any) -> str:
        if not isinstance(value, str):
            return "UNKNOWN"

        value = value.strip().upper()

        if value in ("BULLISH", "BEARISH", "NEUTRAL"):
            return value

        return "UNKNOWN"

    @staticmethod
    def _confirmed(data: Dict[str, Any]) -> bool:
        """
        Accept only explicit positive confirmation.
        """
        if not isinstance(data, dict):
            return False

        return (
            data.get("detected") is True
            or data.get("confirmed") is True
            or data.get("valid") is True
            or data.get("approved") is True
        )

    @staticmethod
    def _score(value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0

        if score != score or score in (
            float("inf"),
            float("-inf"),
        ):
            return 0.0

        return max(0.0, min(100.0, score))

    @staticmethod
    def _weighted_category(
        checks: Dict[str, bool],
    ) -> float:
        if not checks:
            return 0.0

        passed = sum(
            1 for value in checks.values()
            if value is True
        )

        return round(
            passed / len(checks) * 100.0,
            2,
        )

    def aggregate(
        self,
        h1: Dict[str, Any],
        m5: Dict[str, Any],
        m1: Dict[str, Any],
        poi: Dict[str, Any],
        liquidity: Dict[str, Any],
        displacement: Dict[str, Any],
        fvg: Dict[str, Any],
        entry_model: Dict[str, Any],
        risk: Dict[str, Any],
        fundamentals: Optional[Dict[str, Any]] = None,
        spread: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        inputs = {
            "h1": h1,
            "m5": m5,
            "m1": m1,
            "poi": poi,
            "liquidity": liquidity,
            "displacement": displacement,
            "fvg": fvg,
            "entry_model": entry_model,
            "risk": risk,
        }

        for name, value in inputs.items():
            if not isinstance(value, dict):
                raise ValueError(
                    f"{name} evidence must be a dictionary"
                )

        fundamentals = fundamentals or {}
        spread = spread or {}

        if not isinstance(fundamentals, dict):
            raise ValueError("fundamentals must be a dictionary")

        if not isinstance(spread, dict):
            raise ValueError("spread must be a dictionary")

        h1_direction = self._direction(
            h1.get("direction", h1.get("bias"))
        )

        m5_direction = self._direction(
            m5.get("direction", m5.get("bias"))
        )

        m1_direction = self._direction(
            m1.get("direction", m1.get("bias"))
        )

        directions_aligned = (
            h1_direction == m5_direction == m1_direction
            and h1_direction in ("BULLISH", "BEARISH")
        )

        structure_checks = {
            "h1_structure": self._confirmed(
                h1.get("structure", {})
            ),
            "h1_body_close": (
                h1.get("body_close_confirmed") is True
            ),
            "m5_structure": self._confirmed(
                m5.get("structure", {})
            ),
            "m5_body_close": (
                m5.get("body_close_confirmed") is True
            ),
        }

        poi_checks = {
            "poi_detected": self._confirmed(poi),
            "poi_clean": poi.get("clean") is True,
            "poi_unmitigated": poi.get("unmitigated") is True,
        }

        liquidity_checks = {
            "liquidity_detected": self._confirmed(liquidity),
            "liquidity_sweep": (
                liquidity.get("swept") is True
                or liquidity.get("sweep_detected") is True
            ),
        }

        entry_checks = {
            "displacement": self._confirmed(displacement),
            "fvg": self._confirmed(fvg),
            "entry_model": self._confirmed(entry_model),
        }

        timeframe_checks = {
            "h1_m5_aligned": (
                h1_direction == m5_direction
                and h1_direction in ("BULLISH", "BEARISH")
            ),
            "m5_m1_aligned": (
                m5_direction == m1_direction
                and m5_direction in ("BULLISH", "BEARISH")
            ),
            "all_aligned": directions_aligned,
        }

        fundamental_score = self._score(
            fundamentals.get("score", 0)
        )

        fundamental_checked = (
            fundamentals.get("checked") is True
        )

        risk_checks = {
            "risk_acceptable": (
                risk.get("acceptable") is True
                or risk.get("approved") is True
            ),
            "spread_acceptable": (
                spread.get("acceptable") is True
            ),
        }

        category_scores = {
            "structure": self._weighted_category(
                structure_checks
            ),
            "poi": self._weighted_category(
                poi_checks
            ),
            "liquidity": self._weighted_category(
                liquidity_checks
            ),
            "entry_model": self._weighted_category(
                entry_checks
            ),
            "timeframe_alignment": self._weighted_category(
                timeframe_checks
            ),
            "fundamentals": (
                fundamental_score if fundamental_checked else 0.0
            ),
            "trade_quality_risk": self._weighted_category(
                risk_checks
            ),
        }

        weighted_total = round(
            sum(
                category_scores[name] * weight / 100.0
                for name, weight in CATEGORY_WEIGHTS.items()
            ),
            2,
        )

        evidence = {
            "h1_direction": h1_direction,
            "m5_direction": m5_direction,
            "m1_direction": m1_direction,

            "structure_confirmed": all(
                structure_checks.values()
            ),

            "body_close_confirmed": (
                structure_checks["h1_body_close"]
                and structure_checks["m5_body_close"]
            ),

            "clean_unmitigated_poi": all(
                poi_checks.values()
            ),

            "liquidity_confirmed": all(
                liquidity_checks.values()
            ),

            "displacement_confirmed": (
                entry_checks["displacement"]
            ),

            "fvg_confirmed": entry_checks["fvg"],

            "entry_model_confirmed": (
                entry_checks["entry_model"]
            ),

            "spread_acceptable": (
                risk_checks["spread_acceptable"]
            ),

            "risk_acceptable": (
                risk_checks["risk_acceptable"]
            ),

            "fundamentals_checked": fundamental_checked,

            "category_scores": category_scores,

            "calculated_score": weighted_total,

            "evidence_details": {
                "structure": structure_checks,
                "poi": poi_checks,
                "liquidity": liquidity_checks,
                "entry_model": entry_checks,
                "timeframe_alignment": timeframe_checks,
                "trade_quality_risk": risk_checks,
            },

            "strategy_timeframes": ["H1", "M5", "M1"],

            "execution_authorized": False,
        }

        self.last_evidence = evidence

        return evidence

    def get_last_evidence(self) -> Optional[Dict[str, Any]]:
        if self.last_evidence is None:
            return None

        return dict(self.last_evidence)

    def get_status(self) -> Dict[str, Any]:
        return {
            "engine": "SMC_EVIDENCE_AGGREGATOR",
            "initialized": True,
            "has_evidence": self.last_evidence is not None,
            "minimum_a_plus_score": 85,
            "category_weights": dict(CATEGORY_WEIGHTS),
        }


# Shared instance
smc_evidence_aggregator = SMCEvidenceAggregator()
