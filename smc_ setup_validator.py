"""
Vrotex Bot V1
SMC Setup Validator

Purpose:
- Validate H1, M5 and M1 SMC evidence.
- Check structure, POI, liquidity and displacement.
- Check entry model and timeframe alignment.
- Reject incomplete or contradictory setups.
- Enforce the minimum A+ score of 85.

This module validates setups only.
It does not execute trades or change strategy rules.
"""

from __future__ import annotations

from typing import Any, Dict, List


MINIMUM_A_PLUS_SCORE = 85

CATEGORY_WEIGHTS = {
    "structure": 20,
    "poi": 15,
    "liquidity": 15,
    "entry_model": 20,
    "timeframe_alignment": 15,
    "fundamentals": 5,
    "trade_quality_risk": 10,
}


class SMCSetupValidator:

    def __init__(
        self,
        minimum_score: int = MINIMUM_A_PLUS_SCORE,
    ):
        if not 0 <= minimum_score <= 100:
            raise ValueError("minimum_score must be between 0 and 100")

        self.minimum_score = minimum_score

    @staticmethod
    def _valid_score(value: Any, field: str) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid score: {field}")

        if score != score or score in (
            float("inf"),
            float("-inf"),
        ):
            raise ValueError(f"Non-finite score: {field}")

        if not 0 <= score <= 100:
            raise ValueError(f"{field} must be between 0 and 100")

        return score

    @staticmethod
    def _direction(value: Any) -> str:
        if not isinstance(value, str):
            return "UNKNOWN"

        value = value.strip().upper()

        if value in ("BULLISH", "BEARISH"):
            return value

        return "UNKNOWN"

    @staticmethod
    def _boolean(value: Any) -> bool:
        return value is True

    def validate(
        self,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(evidence, dict):
            raise ValueError("evidence must be a dictionary")

        reasons: List[str] = []
        category_scores: Dict[str, float] = {}

        scores = evidence.get("category_scores", {})

        if not isinstance(scores, dict):
            raise ValueError("category_scores must be a dictionary")

        for category, weight in CATEGORY_WEIGHTS.items():

            if category not in scores:
                reasons.append(f"MISSING_SCORE_{category.upper()}")
                category_scores[category] = 0.0
                continue

            raw_score = self._valid_score(
                scores[category],
                category,
            )

            category_scores[category] = (
                raw_score * weight / 100.0
            )

        total_score = round(
            sum(category_scores.values()),
            2,
        )

        h1_direction = self._direction(
            evidence.get("h1_direction")
        )

        m5_direction = self._direction(
            evidence.get("m5_direction")
        )

        m1_direction = self._direction(
            evidence.get("m1_direction")
        )

        if h1_direction == "UNKNOWN":
            reasons.append("INVALID_H1_DIRECTION")

        if m5_direction == "UNKNOWN":
            reasons.append("INVALID_M5_DIRECTION")

        if m1_direction == "UNKNOWN":
            reasons.append("INVALID_M1_DIRECTION")

        directions_aligned = (
            h1_direction == m5_direction == m1_direction
            and h1_direction in ("BULLISH", "BEARISH")
        )

        if not directions_aligned:
            reasons.append("H1_M5_M1_NOT_ALIGNED")

        structure_confirmed = self._boolean(
            evidence.get("structure_confirmed")
        )

        body_close_confirmed = self._boolean(
            evidence.get("body_close_confirmed")
        )

        clean_poi = self._boolean(
            evidence.get("clean_unmitigated_poi")
        )

        liquidity_confirmed = self._boolean(
            evidence.get("liquidity_confirmed")
        )

        displacement_confirmed = self._boolean(
            evidence.get("displacement_confirmed")
        )

        fvg_confirmed = self._boolean(
            evidence.get("fvg_confirmed")
        )

        entry_model_confirmed = self._boolean(
            evidence.get("entry_model_confirmed")
        )

        spread_acceptable = self._boolean(
            evidence.get("spread_acceptable")
        )

        risk_acceptable = self._boolean(
            evidence.get("risk_acceptable")
        )

        fundamentals_checked = self._boolean(
            evidence.get("fundamentals_checked")
        )

        checks = {
            "structure_confirmed": structure_confirmed,
            "body_close_confirmed": body_close_confirmed,
            "clean_unmitigated_poi": clean_poi,
            "liquidity_confirmed": liquidity_confirmed,
            "displacement_confirmed": displacement_confirmed,
            "fvg_confirmed": fvg_confirmed,
            "entry_model_confirmed": entry_model_confirmed,
            "spread_acceptable": spread_acceptable,
            "risk_acceptable": risk_acceptable,
            "fundamentals_checked": fundamentals_checked,
            "directions_aligned": directions_aligned,
        }

        mandatory_checks = (
            "structure_confirmed",
            "body_close_confirmed",
            "clean_unmitigated_poi",
            "liquidity_confirmed",
            "displacement_confirmed",
            "entry_model_confirmed",
            "spread_acceptable",
            "risk_acceptable",
            "directions_aligned",
        )

        for check in mandatory_checks:
            if not checks[check]:
                reasons.append(f"FAILED_{check.upper()}")

        if total_score < self.minimum_score:
            reasons.append("A_PLUS_SCORE_BELOW_THRESHOLD")

        approved = (
            total_score >= self.minimum_score
            and all(checks[item] for item in mandatory_checks)
        )

        if approved:
            reasons.append("A_PLUS_SETUP_VALIDATED")

        return {
            "approved": approved,
            "status": (
                "A_PLUS_VALIDATED"
                if approved
                else "REJECTED"
            ),
            "score": total_score,
            "minimum_score": self.minimum_score,
            "direction": (
                h1_direction if approved else None
            ),
            "category_scores": category_scores,
            "checks": checks,
            "reasons": reasons,
            "strategy_timeframes": ["H1", "M5", "M1"],
            "execution_authorized": False,
        }


# Shared validator instance
smc_setup_validator = SMCSetupValidator()


def validate_smc_setup(
    evidence: Dict[str, Any],
) -> Dict[str, Any]:

    return smc_setup_validator.validate(evidence)
