
"""
Vrotex Bot V1 - Learning Memory Engine

Manages access to persistent learning observations,
historical trade experiences and learning summaries.

Uses knowledge_learning_core.py.

Does not modify approved strategy rules.
"""

import logging
from datetime import datetime, timezone

from knowledge_learning_core import knowledge_learning_core
from intelligence_registry import intelligence_registry


logger = logging.getLogger("vrotex.learning_memory")


class LearningMemoryEngine:

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

        self.memory_operations = 0
        self.last_operation = None

        logger.info(
            "Learning memory engine initialized"
        )

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _record_operation(self):
        self.memory_operations += 1
        self.last_operation = self._timestamp()

    def retrieve_recent_memory(
        self,
        limit=100
    ) -> dict:
        """Retrieve recent persistent learning observations."""

        limit = max(1, min(int(limit), 500))

        try:
            observations = (
                self.learning_core.get_recent_observations(
                    limit=limit
                )
            )

            result = {
                "success": True,
                "status": "MEMORY_RETRIEVED",
                "count": len(observations),
                "observations": observations,
                "retrieved_at": self._timestamp()
            }

            self.registry.publish(
                key="learning.memory.recent",
                value=result,
                source="learning_memory_engine"
            )

            self._record_operation()

            return result

        except Exception as exc:
            logger.exception(
                "Recent memory retrieval failed"
            )

            return {
                "success": False,
                "status": "MEMORY_RETRIEVAL_ERROR",
                "error": str(exc),
                "observations": []
            }

    def retrieve_learning_summary(self) -> dict:
        """Retrieve the persistent learning summary."""

        try:
            summary = (
                self.learning_core.get_learning_summary()
            )

            result = {
                "success": True,
                "status": "SUMMARY_RETRIEVED",
                "summary": summary,
                "retrieved_at": self._timestamp()
            }

            self.registry.publish(
                key="learning.memory.summary",
                value=result,
                source="learning_memory_engine"
            )

            self._record_operation()

            return result

        except Exception as exc:
            logger.exception(
                "Learning summary retrieval failed"
            )

            return {
                "success": False,
                "status": "SUMMARY_RETRIEVAL_ERROR",
                "error": str(exc)
            }

    def retrieve_setup_memory(
        self,
        setup_type: str
    ) -> dict:
        """Retrieve historical performance for a setup."""

        if not isinstance(setup_type, str) or not setup_type.strip():
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

            result = {
                "success": True,
                "status": "SETUP_MEMORY_RETRIEVED",
                "setup_type": setup_type,
                "performance": performance,
                "retrieved_at": self._timestamp()
            }

            self.registry.publish(
                key=f"learning.memory.setup.{setup_type}",
                value=result,
                source="learning_memory_engine"
            )

            self._record_operation()

            return result

        except Exception as exc:
            logger.exception(
                "Setup memory retrieval failed"
            )

            return {
                "success": False,
                "status": "SETUP_MEMORY_ERROR",
                "error": str(exc)
            }

    def search_memory(
        self,
        query: str,
        limit: int = 100
    ) -> dict:
        """
        Search historical observations by text.

        Searches observations returned by the learning core.
        """

        if not isinstance(query, str) or not query.strip():
            return {
                "success": False,
                "status": "INVALID_QUERY",
                "results": []
            }

        try:
            observations = (
                self.learning_core.get_recent_observations(
                    limit=max(1, min(int(limit), 500))
                )
            )

            search_term = query.casefold().strip()

            matches = []

            for observation in observations:

                searchable = str(
                    observation
                ).casefold()

                if search_term in searchable:
                    matches.append(observation)

            result = {
                "success": True,
                "status": (
                    "MATCHES_FOUND"
                    if matches
                    else "NO_MATCHES"
                ),
                "query": query,
                "count": len(matches),
                "results": matches,
                "searched_at": self._timestamp()
            }

            self.registry.publish(
                key="learning.memory.search",
                value=result,
                source="learning_memory_engine"
            )

            self._record_operation()

            return result

        except Exception as exc:
            logger.exception(
                "Memory search failed"
            )

            return {
                "success": False,
                "status": "MEMORY_SEARCH_ERROR",
                "error": str(exc),
                "results": []
            }

    def get_status(self) -> dict:
        """Return memory engine health."""

        return {
            "status": "ACTIVE",
            "memory_operations": self.memory_operations,
            "last_operation": self.last_operation,
            "persistent_storage": True,
            "automatic_strategy_changes": False
        }


# Shared learning memory instance.
learning_memory_engine = LearningMemoryEngine()
