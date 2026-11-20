
"""
Vrotex Bot V1 - Learning Validation Engine

Validates learned setup performance using historical
trade outcomes and minimum sample requirements.

This module does not modify trading rules,
risk settings or execution decisions.
"""

import logging
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger("vrotex.learning_validation")


class LearningValidationEngine:

    def __init__(
        self,
        minimum_sample_size: int = 30,
        minimum_win_rate: float = 0.0,
        minimum_expectancy: float = 0.0
    ):
        self.minimum_sample_size = max(
            1, int(minimum_sample_size)
        )

        self.minimum_win_rate = float(
            minimum_win_rate
        )

        self.minimum_expectancy = float(
            minimum_expectancy
        )

        self.validation_count = 0
        self.last_validation = None

        logger.info(
            "Learning validation engine initialized"
        )

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _number(value, field):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{field} must be numeric"
            )

        if number != number or abs(number) == float("inf"):
            raise ValueError(
                f"{field} must be finite"
            )

        return number

    def validate_setup(
        self,
        setup_type: str,
        outcomes: list,
        expectancy: Optional[float] = None
    ) -> dict:
        """
        Validate a setup using individual completed trade outcomes.

        Outcomes must be numeric net results:
        positive = profit
        negative = loss
        zero = break-even

        Expectancy, if supplied, must use a consistent
        unit such as R-multiples.
        """

        if not isinstance(setup_type, str) or not setup_type.strip():
            return {
                "success": False,
                "status": "INVALID_SETUP_TYPE"
            }

        if not isinstance(outcomes, list):
            return {
                "success": False,
                "status": "INVALID_OUTCOMES"
            }

        try:
            values = [
                self._number(value, "outcome")
                for value in outcomes
            ]

            sample_size = len(values)

            wins = sum(
                1 for value in values if value > 0
            )

            losses = sum(
                1 for value in values if value < 0
            )

            breakeven = sum(
                1 for value in values if value == 0
            )

            win_rate = (
                wins / sample_size * 100
                if sample_size
                else 0.0
            )

            average_result = (
                sum(values) / sample_size
                if sample_size
                else 0.0
            )

            if expectancy is not None:
                expectancy_value = self._number(
                    expectancy,
                    "expectancy"
                )
            else:
                expectancy_value = average_result

            sample_valid = (
                sample_size >= self.minimum_sample_size
            )

            win_rate_valid = (
                win_rate >= self.minimum_win_rate
            )

            expectancy_valid = (
                expectancy_value >= self.minimum_expectancy
            )

            validated = (
                sample_valid
                and win_rate_valid
                and expectancy_valid
            )

            if not sample_valid:
                status = "INSUFFICIENT_SAMPLE"
            elif not win_rate_valid:
                status = "WIN_RATE_BELOW_THRESHOLD"
            elif not expectancy_valid:
                status = "EXPECTANCY_BELOW_THRESHOLD"
            else:
                status = "VALIDATED"

            result = {
                "success": True,
                "setup_type": setup_type,
                "status": status,
                "validated": validated,
                "sample_size": sample_size,
                "required_sample_size": (
                    self.minimum_sample_size
                ),
                "wins": wins,
                "losses": losses,
                "breakeven": breakeven,
                "win_rate_percent": round(
                    win_rate, 2
                ),
                "average_result": round(
                    average_result, 6
                ),
                "expectancy": round(
                    expectancy_value, 6
                ),
                "thresholds": {
                    "minimum_win_rate": (
                        self.minimum_win_rate
                    ),
                    "minimum_expectancy": (
                        self.minimum_expectancy
                    )
                },
                "strategy_modified": False,
                "validated_at": self._timestamp()
            }

            self.validation_count += 1
            self.last_validation = result["validated_at"]

            logger.info(
                "Setup validation: %s status=%s sample=%s",
                setup_type,
                status,
                sample_size
            )

            return result

        except ValueError as exc:
            return {
                "success": False,
                "status": "INVALID_DATA",
                "error": str(exc)
            }

        except Exception:
            logger.exception(
                "Unexpected learning validation error"
            )

            return {
                "success": False,
                "status": "VALIDATION_ERROR"
            }

    def get_status(self) -> dict:
        return {
            "status": "ACTIVE",
            "validation_count": self.validation_count,
            "minimum_sample_size": (
                self.minimum_sample_size
            ),
            "last_validation": self.last_validation,
            "strategy_auto_modification": False
        }


# Shared validation engine.
learning_validation_engine = LearningValidationEngine()
