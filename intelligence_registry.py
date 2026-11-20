
"""
Vrotex Bot V1 - Intelligence Registry

Shared runtime information exchange between bot engines.
"""

import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Optional


logger = logging.getLogger("vrotex.intelligence_registry")


class IntelligenceRegistry:
    """Thread-safe shared intelligence registry."""

    def __init__(self, history_limit: int = 100):
        self._lock = threading.RLock()
        self._data = {}
        self._history = defaultdict(
            lambda: deque(maxlen=history_limit)
        )
        self._metadata = {}

        logger.info("Intelligence registry initialized")

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    def publish(
        self,
        key: str,
        value: Any,
        source: str = "unknown",
        metadata: Optional[dict] = None
    ) -> dict:
        """Publish information under a registry key."""

        if not isinstance(key, str) or not key.strip():
            raise ValueError("Registry key is required")

        record = {
            "key": key,
            "value": value,
            "source": source,
            "metadata": metadata or {},
            "updated_at": self._timestamp()
        }

        with self._lock:
            self._data[key] = record
            self._metadata[key] = {
                "source": source,
                "updated_at": record["updated_at"]
            }

            self._history[key].append(record.copy())

        return {
            "success": True,
            "key": key,
            "updated_at": record["updated_at"]
        }

    def get(
        self,
        key: str,
        default: Any = None
    ) -> Any:
        """Retrieve a published value."""

        with self._lock:
            record = self._data.get(key)

            if record is None:
                return default

            return record["value"]

    def get_record(
        self,
        key: str
    ) -> Optional[dict]:
        """Retrieve the complete published record."""

        with self._lock:
            record = self._data.get(key)

            return record.copy() if record else None

    def get_history(
        self,
        key: str,
        limit: int = 20
    ) -> list:
        """Retrieve recent updates for a key."""

        limit = max(1, min(int(limit), 100))

        with self._lock:
            history = list(self._history.get(key, []))

            return [
                item.copy()
                for item in history[-limit:]
            ]

    def get_all(self) -> dict:
        """Retrieve a snapshot of all current values."""

        with self._lock:
            return {
                key: record["value"]
                for key, record in self._data.items()
            }

    def get_all_records(self) -> dict:
        """Retrieve complete records for all keys."""

        with self._lock:
            return {
                key: record.copy()
                for key, record in self._data.items()
            }

    def exists(self, key: str) -> bool:
        """Check whether a key exists."""

        with self._lock:
            return key in self._data

    def remove(self, key: str) -> bool:
        """Remove a key and its runtime history."""

        with self._lock:
            existed = key in self._data

            self._data.pop(key, None)
            self._metadata.pop(key, None)
            self._history.pop(key, None)

            return existed

    def clear(self) -> None:
        """Clear all runtime registry information."""

        with self._lock:
            self._data.clear()
            self._metadata.clear()
            self._history.clear()

        logger.warning("Intelligence registry cleared")

    def status(self) -> dict:
        """Return registry health and statistics."""

        with self._lock:
            return {
                "status": "ACTIVE",
                "active_keys": len(self._data),
                "history_entries": sum(
                    len(items)
                    for items in self._history.values()
                ),
                "keys": list(self._data.keys()),
                "checked_at": self._timestamp()
            }


# Shared registry instance for Vrotex engines.
intelligence_registry = IntelligenceRegistry()


def publish(
    key: str,
    value: Any,
    source: str = "unknown",
    metadata: Optional[dict] = None
) -> dict:
    return intelligence_registry.publish(
        key,
        value,
        source,
        metadata
    )


def get(key: str, default: Any = None) -> Any:
    return intelligence_registry.get(key, default)


def get_record(key: str) -> Optional[dict]:
    return intelligence_registry.get_record(key)


def get_history(
    key: str,
    limit: int = 20
) -> list:
    return intelligence_registry.get_history(key, limit)


def get_status() -> dict:
    return intelligence_registry.status()
