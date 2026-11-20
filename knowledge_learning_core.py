import sqlite3
import json
import os
import threading
from datetime import datetime, timezone

from logging_config import get_logger

logger = get_logger("knowledge_learning_core")


class KnowledgeLearningCore:

    def __init__(self, database_path=None):

        self.database_path = database_path or os.getenv(
            "DATABASE_PATH",
            "data/vrotex_v1.db",
        )

        directory = os.path.dirname(self.database_path)

        if directory:
            os.makedirs(directory, exist_ok=True)

        self._lock = threading.RLock()
        self.initialize_database()

    @staticmethod
    def utc_now():
        return datetime.now(timezone.utc).isoformat()

    def connection(self):
        conn = sqlite3.connect(
            self.database_path,
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize_database(self):

        with self._lock:
            with self.connection() as conn:

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        timeframe TEXT,
                        category TEXT NOT NULL,
                        observation TEXT NOT NULL,
                        evidence_json TEXT,
                        created_at TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS learning_trade_outcomes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id TEXT UNIQUE NOT NULL,
                        symbol TEXT NOT NULL,
                        setup_type TEXT,
                        direction TEXT,
                        setup_score REAL,
                        outcome TEXT NOT NULL,
                        pnl REAL DEFAULT 0,
                        r_multiple REAL,
                        context_json TEXT,
                        created_at TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS setup_performance (
                        setup_key TEXT PRIMARY KEY,
                        total_trades INTEGER DEFAULT 0,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        breakeven INTEGER DEFAULT 0,
                        total_pnl REAL DEFAULT 0,
                        total_r REAL DEFAULT 0,
                        updated_at TEXT
                    )
                """)

    def record_observation(
        self,
        symbol,
        category,
        observation,
        timeframe=None,
        evidence=None,
    ):

        with self._lock:
            with self.connection() as conn:

                cursor = conn.execute("""
                    INSERT INTO knowledge_observations (
                        symbol, timeframe, category,
                        observation, evidence_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    symbol.upper(),
                    timeframe,
                    category,
                    observation,
                    json.dumps(evidence or {}, default=str),
                    self.utc_now(),
                ))

                return cursor.lastrowid

    def record_trade_outcome(
        self,
        trade_id,
        symbol,
        setup_type,
        direction,
        setup_score,
        outcome,
        pnl=0,
        r_multiple=None,
        context=None,
    ):

        outcome = outcome.upper()

        if outcome not in ("WIN", "LOSS", "BREAKEVEN"):
            raise ValueError("Invalid trade outcome")

        symbol = symbol.upper()
        setup_type = setup_type or "UNKNOWN"

        setup_key = f"{symbol}|{setup_type}|{direction}"

        with self._lock:
            with self.connection() as conn:

                cursor = conn.execute("""
                    INSERT OR IGNORE INTO learning_trade_outcomes (
                        trade_id, symbol, setup_type, direction,
                        setup_score, outcome, pnl, r_multiple,
                        context_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(trade_id),
                    symbol,
                    setup_type,
                    direction,
                    setup_score,
                    outcome,
                    float(pnl),
                    r_multiple,
                    json.dumps(context or {}, default=str),
                    self.utc_now(),
                ))

                if cursor.rowcount == 0:
                    return False

                conn.execute("""
                    INSERT INTO setup_performance (
                        setup_key, total_trades, wins, losses,
                        breakeven, total_pnl, total_r, updated_at
                    )
                    VALUES (?, 1, ?, ?, ?, ?, ?, ?)

                    ON CONFLICT(setup_key)
                    DO UPDATE SET
                        total_trades = total_trades + 1,
                        wins = wins + excluded.wins,
                        losses = losses + excluded.losses,
                        breakeven = breakeven + excluded.breakeven,
                        total_pnl = total_pnl + excluded.total_pnl,
                        total_r = total_r + excluded.total_r,
                        updated_at = excluded.updated_at
                """, (
                    setup_key,
                    int(outcome == "WIN"),
                    int(outcome == "LOSS"),
                    int(outcome == "BREAKEVEN"),
                    float(pnl),
                    float(r_multiple or 0),
                    self.utc_now(),
                ))

        logger.info("Trade learning recorded: %s", trade_id)
        return True

    def get_setup_performance(
        self,
        symbol=None,
        setup_type=None,
        direction=None,
    ):

        query = """
            SELECT
                symbol,
                setup_type,
                direction,
                COUNT(*) AS total_trades,
                SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN outcome = 'BREAKEVEN' THEN 1 ELSE 0 END) AS breakeven,
                SUM(pnl) AS total_pnl,
                AVG(pnl) AS average_pnl,
                AVG(r_multiple) AS average_r,
                AVG(setup_score) AS average_score
            FROM learning_trade_outcomes
            WHERE 1=1
        """

        parameters = []

        if symbol:
            query += " AND symbol = ?"
            parameters.append(symbol.upper())

        if setup_type:
            query += " AND setup_type = ?"
            parameters.append(setup_type)

        if direction:
            query += " AND direction = ?"
            parameters.append(direction.upper())

        query += """
            GROUP BY symbol, setup_type, direction
            ORDER BY total_trades DESC
        """

        with self.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()

        results = []

        for row in rows:
            item = dict(row)
            total = item["total_trades"]

            item["win_rate"] = round(
                item["wins"] / total * 100, 2
            ) if total else 0

            results.append(item)

        return results

    def get_recent_observations(self, symbol=None, limit=100):

        query = """
            SELECT *
            FROM knowledge_observations
        """

        parameters = []

        if symbol:
            query += " WHERE symbol = ?"
            parameters.append(symbol.upper())

        query += " ORDER BY id DESC LIMIT ?"
        parameters.append(max(1, min(int(limit), 1000)))

        with self.connection() as conn:
            rows = conn.execute(query, parameters).fetchall()

        results = []

        for row in rows:
            item = dict(row)

            try:
                item["evidence"] = json.loads(
                    item.pop("evidence_json") or "{}"
                )
            except json.JSONDecodeError:
                item["evidence"] = {}

            results.append(item)

        return results

    def get_learning_summary(self):

        with self.connection() as conn:

            total_trades = conn.execute("""
                SELECT COUNT(*) FROM learning_trade_outcomes
            """).fetchone()[0]

            total_observations = conn.execute("""
                SELECT COUNT(*) FROM knowledge_observations
            """).fetchone()[0]

            setup_count = conn.execute("""
                SELECT COUNT(*) FROM setup_performance
            """).fetchone()[0]

        return {
            "total_learning_trades": total_trades,
            "total_observations": total_observations,
            "unique_setup_groups": setup_count,
            "database_path": self.database_path,
        }


knowledge_learning_core = KnowledgeLearningCore()
