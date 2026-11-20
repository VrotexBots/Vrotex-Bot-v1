
"""
Vrotex Bot V1 - Learning Analysis Engine

Analyses historical trade outcomes and setup performance.
Uses knowledge_learning_core.py.

Does not automatically modify strategy rules,
risk limits or execution settings.
"""

import logging
from datetime import datetime, timezone
from collections import defaultdict

from knowledge_learning_core import knowledge_learning_core
from intelligence_registry import intelligence_registry


logger = logging.getLogger("vrotex.learning_analysis")


class LearningAnalysisEngine:

    def __init__(
        self,
        learning_core=None,
        registry=None
    ):
        self.learning_core = (
            learning_core or knowledge_learning_core
        )

        self.registry = (
            registry or intelligence_registry
        )

        self.analysis_count = 0
        self.last_analysis = None

        logger.info(
            "Learning analysis engine initialized"
        )

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    def analyse_setup(
        self,
        setup_type: str
    ) -> dict:
        """Analyse recorded outcomes for one setup type."""

        if not setup_type:
            return {
                "success": False,
                "status": "INVALID_SETUP_TYPE"
            }

        try:
            performance = (
                self.learning_core.get_setup_performance(
                    setup_type
                )
            )

            if not performance:
                performance = {}

            result = {
                "success": True,
                "setup_type": setup_type,
                "performance": performance,
                "analysed_at": self._timestamp()
            }

            self.registry.publish(
                key=f"learning.setup.{setup_type}",
                value=result,
                source="learning_analysis_engine"
            )

            self.analysis_count += 1
            self.last_analysis = result["analysed_at"]

            return result

        except Exception as exc:
            logger.exception(
                "Setup analysis failed: %s",
                setup_type
            )

            return {
                "success": False,
                "status": "ANALYSIS_ERROR",
                "error": str(exc)
            }

    def get_learning_summary(self) -> dict:
        """Retrieve the overall learning summary."""

        try:
            summary = (
                self.learning_core.get_learning_summary()
            )

            if not isinstance(summary, dict):
                summary = {
                    "raw_summary": summary
                }

            result = {
                "success": True,
                "summary": summary,
                "analysed_at": self._timestamp()
            }

            self.registry.publish(
                key="learning.overall_summary",
                value=result,
                source="learning_analysis_engine"
            )

            self.analysis_count += 1
            self.last_analysis = result["analysed_at"]

            return result

        except Exception as exc:
            logger.exception(
                "Learning summary analysis failed"
            )

            return {
                "success": False,
                "status": "ANALYSIS_ERROR",
                "error": str(exc)
            }

    def retrieve_recent_observations(
        self,
        limit: int = 100
    ) -> dict:
        """Retrieve recent stored learning observations."""

        limit = max(1, min(int(limit), 500))

        try:
            observations = (
                self.learning_core.get_recent_observations(
                    limit=limit
                )
            )

            return {
                "success": True,
                "count": len(observations),
                "observations": observations,
                "retrieved_at": self._timestamp()
            }

        except Exception as exc:
            logger.exception(
                "Observation retrieval failed"
            )

            return {
                "success": False,
                "status": "RETRIEVAL_ERROR",
                "error": str(exc),
                "observations": []
            }

    def compare_setups(
        self,
        setup_types: list
    ) -> dict:
        """Compare historical performance across setup types."""

        if not isinstance(setup_types, list) or not setup_types:
            return {
                "success": False,
                "status": "NO_SETUP_TYPES"
            }

        comparisons = {}

        for setup_type in setup_types:
            result = self.analyse_setup(setup_type)

            if result["success"]:
                comparisons[setup_type] = (
                    result["performance"]
                )

        return {
            "success": True,
            "comparison_count": len(comparisons),
            "comparisons": comparisons,
            "analysed_at": self._timestamp()
        }

    def get_status(self) -> dict:
        """Return learning analysis engine health."""

        return {
            "status": "ACTIVE",
            "analysis_count": self.analysis_count,
            "last_analysis": self.last_analysis,
            "strategy_auto_modification": False
        }


# Shared learning analysis instance.
learning_analysis_engine = LearningAnalysisEngine()
