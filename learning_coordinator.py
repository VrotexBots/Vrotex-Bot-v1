
"""
Vrotex Bot V1 - Learning Coordinator

Coordinates the knowledge and learning components.

Responsibilities:
- Coordinate learning analysis.
- Validate learning results.
- Detect recurring trading patterns.
- Retrieve persistent learning memory.
- Publish learning-cycle results.
- Report component health.

This module does not change approved trading rules
or authorize trade execution.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from learning_analysis_engine import LearningAnalysisEngine
from learning_validation_engine import LearningValidationEngine
from learning_pattern_engine import LearningPatternEngine
from learning_memory_engine import LearningMemoryEngine
from intelligence_registry import IntelligenceRegistry


logger = logging.getLogger("vrotex.learning.coordinator")


class LearningCoordinator:

    def __init__(
        self,
        analysis_engine=None,
        validation_engine=None,
        pattern_engine=None,
        memory_engine=None,
        registry=None,
    ):
        self.analysis_engine = (
            analysis_engine or LearningAnalysisEngine()
        )

        self.validation_engine = (
            validation_engine or LearningValidationEngine()
        )

        self.pattern_engine = (
            pattern_engine or LearningPatternEngine()
        )

        self.memory_engine = (
            memory_engine or LearningMemoryEngine()
        )

        self.registry = registry or IntelligenceRegistry()

        self.last_cycle = None
        self.cycle_count = 0
        self.last_error = None

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_status(component):
        try:
            method = getattr(component, "get_status", None)

            if callable(method):
                return method()

            return {"status": "AVAILABLE"}

        except Exception as exc:
            return {
                "status": "ERROR",
                "error": str(exc),
            }

    def get_status(self):
        return {
            "component": "LEARNING_COORDINATOR",
            "status": (
                "ERROR" if self.last_error else "ACTIVE"
            ),
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "last_error": self.last_error,
            "components": {
                "analysis": self._safe_status(
                    self.analysis_engine
                ),
                "validation": self._safe_status(
                    self.validation_engine
                ),
                "patterns": self._safe_status(
                    self.pattern_engine
                ),
                "memory": self._safe_status(
                    self.memory_engine
                ),
            },
        }

    def run_learning_cycle(
        self,
        completed_trades: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        Runs an analysis cycle using supplied completed trades.

        This method does not record trade outcomes automatically.
        Trade persistence must be handled by the feedback pipeline
        after its interfaces have been verified.
        """

        completed_trades = completed_trades or []

        if not isinstance(completed_trades, list):
            raise TypeError(
                "completed_trades must be a list"
            )

        for trade in completed_trades:
            if not isinstance(trade, dict):
                raise ValueError(
                    "Every completed trade must be a dictionary"
                )

        cycle = {
            "timestamp": self._timestamp(),
            "status": "STARTED",
            "trade_count": len(completed_trades),
            "analysis": None,
            "validation": None,
            "patterns": None,
            "memory": None,
            "errors": [],
        }

        try:
            if completed_trades:
                try:
                    cycle["patterns"] = (
                        self.pattern_engine.analyze_patterns(
                            completed_trades
                        )
                    )
                except Exception as exc:
                    cycle["errors"].append(
                        f"Pattern analysis: {exc}"
                    )

            try:
                cycle["analysis"] = (
                    self.analysis_engine.run_analysis()
                )
            except Exception as exc:
                cycle["errors"].append(
                    f"Learning analysis: {exc}"
                )

            try:
                cycle["validation"] = (
                    self.validation_engine.get_status()
                )
            except Exception as exc:
                cycle["errors"].append(
                    f"Learning validation: {exc}"
                )

            try:
                cycle["memory"] = (
                    self.memory_engine.get_memory_summary()
                )
            except Exception as exc:
                cycle["errors"].append(
                    f"Learning memory: {exc}"
                )

            cycle["status"] = (
                "COMPLETED"
                if not cycle["errors"]
                else "COMPLETED_WITH_ERRORS"
            )

            self.cycle_count += 1
            self.last_cycle = cycle["timestamp"]
            self.last_error = (
                "; ".join(cycle["errors"])
                if cycle["errors"]
                else None
            )

            try:
                self.registry.publish(
                    "learning.latest_cycle",
                    cycle,
                )
            except Exception as exc:
                logger.warning(
                    "Could not publish learning cycle: %s",
                    exc,
                )

            logger.info(
                "Learning cycle finished: status=%s trades=%s",
                cycle["status"],
                cycle["trade_count"],
            )

            return cycle

        except Exception as exc:
            self.last_error = str(exc)

            logger.exception(
                "Learning cycle failed"
            )

            cycle["status"] = "FAILED"
            cycle["errors"].append(str(exc))

            return cycle


learning_coordinator = LearningCoordinator()
