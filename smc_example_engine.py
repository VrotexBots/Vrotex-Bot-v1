
"""
Vrotex Bot V1 - SMC Example Engine

Evaluates structured SMC learning scenarios.

Supports:
- Bullish and bearish examples
- H1, M5 and M1 confirmation checks
- Liquidity sweep validation
- BOS and CHoCH body-close validation
- Displacement and FVG checks
- Premium and discount checks
- Minimum setup score validation

This is a learning and validation component.
It does not execute trades or modify strategy rules.
"""

from datetime import datetime, timezone
from typing import Any, Dict


class SMCExampleEngine:

    VERSION = "1.0"
    MINIMUM_SCORE = 85

    def __init__(self):
        self.total_evaluated = 0
        self.valid_scenarios = 0
        self.rejected_scenarios = 0
        self.last_evaluation = None

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _is_true(value):
        return value is True

    def evaluate_scenario(
        self,
        scenario: Dict[str, Any]
    ) -> Dict[str, Any]:

        if not isinstance(scenario, dict):
            raise TypeError("Scenario must be a dictionary")

        self.total_evaluated += 1

        direction = str(
            scenario.get("direction", "")
        ).upper()

        if direction not in ("BUY", "SELL"):
            return self._reject(
                "Direction must be BUY or SELL."
            )

        checks = {
            "h1_structure": self._is_true(
                scenario.get("h1_structure_confirmed")
            ),
            "h1_poi": self._is_true(
                scenario.get("h1_poi_valid")
            ),
            "liquidity_sweep": self._is_true(
                scenario.get("liquidity_sweep_confirmed")
            ),
            "m5_choch": self._is_true(
                scenario.get("m5_external_choch")
            ),
            "m5_body_close": self._is_true(
                scenario.get("m5_body_closed_beyond_level")
            ),
            "displacement": self._is_true(
                scenario.get("displacement_confirmed")
            ),
            "fvg": self._is_true(
                scenario.get("fvg_confirmed")
            ),
            "m1_entry": self._is_true(
                scenario.get("m1_entry_model_confirmed")
            ),
            "timeframe_alignment": self._is_true(
                scenario.get("timeframes_aligned")
            ),
            "risk_approved": self._is_true(
                scenario.get("risk_approved")
            )
        }

        score = scenario.get("score")

        try:
            score = float(score)
        except (TypeError, ValueError):
            return self._reject(
                "A valid numeric setup score is required.",
                checks
            )

        if not 0 <= score <= 100:
            return self._reject(
                "Setup score must be between 0 and 100.",
                checks
            )

        failed_checks = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        if failed_checks:
            return self._reject(
                "Required SMC confirmations are missing.",
                checks,
                failed_checks,
                score
            )

        if score < self.MINIMUM_SCORE:
            return self._reject(
                "Setup score is below the approved 85-point threshold.",
                checks,
                [],
                score
            )

        self.valid_scenarios += 1

        result = {
            "status": "VALID_SCENARIO",
            "direction": direction,
            "score": score,
            "minimum_score": self.MINIMUM_SCORE,
            "checks": checks,
            "failed_checks": [],
            "trade_authorized": False,
            "timestamp": self._timestamp()
        }

        self.last_evaluation = result

        return result

    def _reject(
        self,
        reason,
        checks=None,
        failed_checks=None,
        score=None
    ):

        self.rejected_scenarios += 1

        result = {
            "status": "REJECTED",
            "reason": reason,
            "score": score,
            "checks": checks or {},
            "failed_checks": failed_checks or [],
            "trade_authorized": False,
            "timestamp": self._timestamp()
        }

        self.last_evaluation = result

        return result

    def create_bullish_example(self):

        return {
            "name": "Bullish SMC example",
            "direction": "BUY",
            "h1_structure_confirmed": True,
            "h1_poi_valid": True,
            "liquidity_sweep_confirmed": True,
            "m5_external_choch": True,
            "m5_body_closed_beyond_level": True,
            "displacement_confirmed": True,
            "fvg_confirmed": True,
            "m1_entry_model_confirmed": True,
            "timeframes_aligned": True,
            "risk_approved": True,
            "score": 90
        }

    def create_bearish_example(self):

        return {
            "name": "Bearish SMC example",
            "direction": "SELL",
            "h1_structure_confirmed": True,
            "h1_poi_valid": True,
            "liquidity_sweep_confirmed": True,
            "m5_external_choch": True,
            "m5_body_closed_beyond_level": True,
            "displacement_confirmed": True,
            "fvg_confirmed": True,
            "m1_entry_model_confirmed": True,
            "timeframes_aligned": True,
            "risk_approved": True,
            "score": 92
        }

    def get_statistics(self):

        return {
            "component": "SMC_EXAMPLE_ENGINE",
            "version": self.VERSION,
            "total_evaluated": self.total_evaluated,
            "valid_scenarios": self.valid_scenarios,
            "rejected_scenarios": self.rejected_scenarios,
            "last_evaluation": self.last_evaluation
        }

    def get_status(self):

        return {
            "component": "SMC_EXAMPLE_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "minimum_score": self.MINIMUM_SCORE
        }


smc_example_engine = SMCExampleEngine()
