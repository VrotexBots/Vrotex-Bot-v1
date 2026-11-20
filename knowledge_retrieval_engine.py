
"""
Vrotex Bot V1 - Knowledge Retrieval Engine

Connects:
- knowledge_library.py
- intelligence_registry.py

Retrieves stored trading knowledge and publishes
results for other Vrotex engines.

Does not modify approved trading rules.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from knowledge_library import knowledge_library
from intelligence_registry import intelligence_registry


logger = logging.getLogger("vrotex.knowledge_retrieval")


class KnowledgeRetrievalEngine:

    def __init__(
        self,
        library=None,
        registry=None
    ):
        self.library = library or knowledge_library
        self.registry = registry or intelligence_registry

        self.retrieval_count = 0
        self.success_count = 0
        self.last_retrieval = None

        logger.info(
            "Knowledge retrieval engine initialized"
        )

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    def retrieve(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
        publish_result: bool = True
    ) -> dict:
        """
        Search the persistent knowledge library.

        Results can optionally be published to the
        shared intelligence registry.
        """

        if not isinstance(query, str) or not query.strip():
            return {
                "success": False,
                "status": "INVALID_QUERY",
                "results": []
            }

        self.retrieval_count += 1

        try:
            results = self.library.search_knowledge(
                query=query.strip(),
                category=category,
                limit=limit
            )

            timestamp = self._timestamp()

            response = {
                "success": True,
                "status": (
                    "RESULTS_FOUND"
                    if results
                    else "NO_RESULTS"
                ),
                "query": query.strip(),
                "category": category,
                "count": len(results),
                "results": results,
                "retrieved_at": timestamp
            }

            if publish_result:
                self.registry.publish(
                    key="knowledge.latest_retrieval",
                    value=response,
                    source="knowledge_retrieval_engine",
                    metadata={
                        "query": query.strip(),
                        "category": category,
                        "count": len(results)
                    }
                )

            self.success_count += 1
            self.last_retrieval = timestamp

            logger.info(
                "Knowledge retrieval completed: "
                "query=%s results=%s",
                query,
                len(results)
            )

            return response

        except Exception as exc:
            logger.exception(
                "Knowledge retrieval failed"
            )

            return {
                "success": False,
                "status": "RETRIEVAL_ERROR",
                "error": str(exc),
                "query": query,
                "results": []
            }

    def retrieve_by_key(
        self,
        knowledge_key: str,
        publish_result: bool = True
    ) -> dict:
        """Retrieve one knowledge record by its unique key."""

        if not knowledge_key:
            return {
                "success": False,
                "status": "INVALID_KEY",
                "record": None
            }

        try:
            record = self.library.get_knowledge(
                knowledge_key
            )

            response = {
                "success": record is not None,
                "status": (
                    "FOUND" if record else "NOT_FOUND"
                ),
                "knowledge_key": knowledge_key,
                "record": record,
                "retrieved_at": self._timestamp()
            }

            if publish_result and record is not None:
                self.registry.publish(
                    key=f"knowledge.record.{knowledge_key}",
                    value=record,
                    source="knowledge_retrieval_engine"
                )

            return response

        except Exception as exc:
            logger.exception(
                "Knowledge key retrieval failed"
            )

            return {
                "success": False,
                "status": "RETRIEVAL_ERROR",
                "error": str(exc),
                "record": None
            }

    def retrieve_category(
        self,
        category: str,
        limit: int = 100,
        publish_result: bool = True
    ) -> dict:
        """Retrieve all enabled records in a category."""

        if not category:
            return {
                "success": False,
                "status": "INVALID_CATEGORY",
                "results": []
            }

        try:
            results = self.library.list_knowledge(
                category=category,
                limit=limit
            )

            response = {
                "success": True,
                "status": (
                    "RESULTS_FOUND"
                    if results
                    else "NO_RESULTS"
                ),
                "category": category,
                "count": len(results),
                "results": results,
                "retrieved_at": self._timestamp()
            }

            if publish_result:
                self.registry.publish(
                    key=f"knowledge.category.{category}",
                    value=response,
                    source="knowledge_retrieval_engine"
                )

            return response

        except Exception as exc:
            logger.exception(
                "Category retrieval failed"
            )

            return {
                "success": False,
                "status": "RETRIEVAL_ERROR",
                "error": str(exc),
                "results": []
            }

    def get_status(self) -> dict:
        """Return retrieval engine statistics."""

        return {
            "status": "ACTIVE",
            "retrieval_count": self.retrieval_count,
            "successful_retrievals": self.success_count,
            "failed_retrievals": (
                self.retrieval_count - self.success_count
            ),
            "last_retrieval": self.last_retrieval
        }


# Shared engine instance.
knowledge_retrieval_engine = KnowledgeRetrievalEngine()
