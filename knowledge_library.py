
"""
Vrotex Bot V1 - Knowledge Library

Persistent searchable knowledge storage.
Uses the existing Vrotex SQLite database.
Does not modify approved trading rules.
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger("vrotex.knowledge_library")


class KnowledgeLibrary:

    def __init__(self, database_path=None):
        self.database_path = str(
            database_path
            or os.getenv(
                "VROTEX_DB_PATH",
                "data/vrotex_v1.db"
            )
        )

        Path(self.database_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self._initialize_database()

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=30
        )

        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )

        return connection

    def _initialize_database(self):
        with self._connect() as connection:

            connection.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_library (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_key TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_category
                ON knowledge_library(category)
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_knowledge_enabled
                ON knowledge_library(enabled)
            """)

        logger.info("Knowledge library initialized")

    @staticmethod
    def _format_record(row):
        if row is None:
            return None

        record = dict(row)

        try:
            record["tags"] = json.loads(
                record["tags"]
            )
        except (TypeError, ValueError):
            record["tags"] = []

        try:
            record["metadata"] = json.loads(
                record["metadata"]
            )
        except (TypeError, ValueError):
            record["metadata"] = {}

        record["enabled"] = bool(
            record["enabled"]
        )

        return record

    def add_knowledge(
        self,
        knowledge_key,
        category,
        title,
        content,
        source=None,
        tags=None,
        metadata=None
    ):
        """Add a new knowledge record without overwriting existing data."""

        values = [
            knowledge_key,
            category,
            title,
            content
        ]

        if not all(
            isinstance(value, str) and value.strip()
            for value in values
        ):
            raise ValueError(
                "Knowledge key, category, title and content are required"
            )

        now = self._timestamp()

        with self._connect() as connection:

            cursor = connection.execute("""
                INSERT OR IGNORE INTO knowledge_library (
                    knowledge_key,
                    category,
                    title,
                    content,
                    source,
                    tags,
                    metadata,
                    version,
                    enabled,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """, (
                knowledge_key.strip(),
                category.strip(),
                title.strip(),
                content.strip(),
                source,
                json.dumps(tags or []),
                json.dumps(metadata or {}),
                now,
                now
            ))

        inserted = cursor.rowcount == 1

        return {
            "success": inserted,
            "status": (
                "ADDED"
                if inserted
                else "KEY_ALREADY_EXISTS"
            ),
            "knowledge_key": knowledge_key
        }

    def update_knowledge(
        self,
        knowledge_key,
        category=None,
        title=None,
        content=None,
        source=None,
        tags=None,
        metadata=None
    ):
        """Deliberately update an existing knowledge record."""

        updates = {
            "category": category,
            "title": title,
            "content": content,
            "source": source
        }

        fields = []
        values = []

        for field, value in updates.items():

            if value is not None:

                if (
                    isinstance(value, str)
                    and not value.strip()
                    and field != "source"
                ):
                    raise ValueError(
                        f"{field} cannot be empty"
                    )

                fields.append(f"{field} = ?")
                values.append(value)

        if tags is not None:
            fields.append("tags = ?")
            values.append(json.dumps(tags))

        if metadata is not None:
            fields.append("metadata = ?")
            values.append(json.dumps(metadata))

        if not fields:
            return {
                "success": False,
                "status": "NO_CHANGES"
            }

        fields.extend([
            "version = version + 1",
            "updated_at = ?"
        ])

        values.append(self._timestamp())
        values.append(knowledge_key)

        with self._connect() as connection:

            cursor = connection.execute(
                f"""
                UPDATE knowledge_library
                SET {", ".join(fields)}
                WHERE knowledge_key = ?
                """,
                values
            )

        return {
            "success": cursor.rowcount > 0,
            "status": (
                "UPDATED"
                if cursor.rowcount > 0
                else "NOT_FOUND"
            ),
            "knowledge_key": knowledge_key
        }

    def get_knowledge(self, knowledge_key):
        """Retrieve one enabled knowledge record."""

        with self._connect() as connection:

            row = connection.execute("""
                SELECT *
                FROM knowledge_library
                WHERE knowledge_key = ?
                AND enabled = 1
            """, (knowledge_key,)).fetchone()

        return self._format_record(row)

    def search_knowledge(
        self,
        query,
        category=None,
        limit=20
    ):
        """Search knowledge by title, content, category or tags."""

        query = str(query).strip()

        if not query:
            return []

        limit = max(1, min(int(limit), 100))
        search_term = f"%{query}%"

        sql = """
            SELECT *
            FROM knowledge_library
            WHERE enabled = 1
            AND (
                title LIKE ?
                OR content LIKE ?
                OR category LIKE ?
                OR tags LIKE ?
            )
        """

        parameters = [
            search_term,
            search_term,
            search_term,
            search_term
        ]

        if category:
            sql += " AND category = ?"
            parameters.append(category)

        sql += """
            ORDER BY updated_at DESC
            LIMIT ?
        """

        parameters.append(limit)

        with self._connect() as connection:

            rows = connection.execute(
                sql,
                parameters
            ).fetchall()

        return [
            self._format_record(row)
            for row in rows
        ]

    def list_knowledge(
        self,
        category=None,
        limit=100
    ):
        """List enabled knowledge records."""

        limit = max(1, min(int(limit), 500))

        sql = """
            SELECT *
            FROM knowledge_library
            WHERE enabled = 1
        """

        parameters = []

        if category:
            sql += " AND category = ?"
            parameters.append(category)

        sql += """
            ORDER BY category, title
            LIMIT ?
        """

        parameters.append(limit)

        with self._connect() as connection:

            rows = connection.execute(
                sql,
                parameters
            ).fetchall()

        return [
            self._format_record(row)
            for row in rows
        ]

    def disable_knowledge(self, knowledge_key):
        """Disable a record without deleting it."""

        with self._connect() as connection:

            cursor = connection.execute("""
                UPDATE knowledge_library
                SET enabled = 0,
                    updated_at = ?
                WHERE knowledge_key = ?
            """, (
                self._timestamp(),
                knowledge_key
            ))

        return cursor.rowcount > 0

    def enable_knowledge(self, knowledge_key):
        """Re-enable a previously disabled record."""

        with self._connect() as connection:

            cursor = connection.execute("""
                UPDATE knowledge_library
                SET enabled = 1,
                    updated_at = ?
                WHERE knowledge_key = ?
            """, (
                self._timestamp(),
                knowledge_key
            ))

        return cursor.rowcount > 0

    def get_statistics(self):
        """Return knowledge library statistics."""

        with self._connect() as connection:

            total = connection.execute("""
                SELECT COUNT(*)
                FROM knowledge_library
            """).fetchone()[0]

            enabled = connection.execute("""
                SELECT COUNT(*)
                FROM knowledge_library
                WHERE enabled = 1
            """).fetchone()[0]

            categories = connection.execute("""
                SELECT category, COUNT(*) AS total
                FROM knowledge_library
                WHERE enabled = 1
                GROUP BY category
                ORDER BY category
            """).fetchall()

        return {
            "total_records": total,
            "enabled_records": enabled,
            "disabled_records": total - enabled,
            "categories": {
                row["category"]: row["total"]
                for row in categories
            },
            "database": self.database_path
        }


# Shared knowledge library instance.
knowledge_library = KnowledgeLibrary()
