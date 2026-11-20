import sqlite3
import os
import threading
from contextlib import contextmanager


class Storage:

    def __init__(self, database_path=None):

        self.database_path = database_path or os.getenv(
            "DATABASE_PATH", "data/vrotex_v1.db"
        )

        directory = os.path.dirname(self.database_path)

        if directory:
            os.makedirs(directory, exist_ok=True)

        self._lock = threading.RLock()

        self.initialize_database()

    @contextmanager
    def connection(self):

        conn = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False
        )

        conn.row_factory = sqlite3.Row

        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")

            yield conn

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def initialize_database(self):

        with self._lock:
            with self.connection() as conn:

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id TEXT UNIQUE,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        entry_price REAL,
                        stop_loss REAL,
                        take_profit REAL,
                        lot_size REAL,
                        risk_percent REAL,
                        setup_score REAL,
                        status TEXT NOT NULL DEFAULT 'PENDING',
                        pnl REAL DEFAULT 0,
                        opened_at TEXT,
                        closed_at TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS system_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_statistics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trading_date TEXT UNIQUE,
                        trades INTEGER DEFAULT 0,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        pnl REAL DEFAULT 0,
                        consecutive_losses INTEGER DEFAULT 0
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trades_symbol
                    ON trades(symbol)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_trades_status
                    ON trades(status)
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_type
                    ON system_events(event_type)
                """)

    def save_trade(self, trade):

        with self._lock:
            with self.connection() as conn:

                conn.execute("""
                    INSERT OR IGNORE INTO trades (
                        trade_id,
                        symbol,
                        direction,
                        entry_price,
                        stop_loss,
                        take_profit,
                        lot_size,
                        risk_percent,
                        setup_score,
                        status,
                        pnl,
                        opened_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.get("trade_id"),
                    trade.get("symbol"),
                    trade.get("direction"),
                    trade.get("entry_price"),
                    trade.get("stop_loss"),
                    trade.get("take_profit"),
                    trade.get("lot_size"),
                    trade.get("risk_percent"),
                    trade.get("setup_score"),
                    trade.get("status", "PENDING"),
                    trade.get("pnl", 0),
                    trade.get("opened_at"),
                ))

    def update_trade(self, trade_id, updates):

        allowed_fields = {
            "entry_price",
            "stop_loss",
            "take_profit",
            "lot_size",
            "risk_percent",
            "setup_score",
            "status",
            "pnl",
            "opened_at",
            "closed_at",
        }

        filtered = {
            key: value
            for key, value in updates.items()
            if key in allowed_fields
        }

        if not filtered:
            return False

        assignments = ", ".join(
            f"{key} = ?" for key in filtered
        )

        values = list(filtered.values())
        values.append(trade_id)

        with self._lock:
            with self.connection() as conn:

                cursor = conn.execute(
                    f"""
                    UPDATE trades
                    SET {assignments}
                    WHERE trade_id = ?
                    """,
                    values
                )

                return cursor.rowcount > 0

    def get_trade(self, trade_id):

        with self.connection() as conn:

            row = conn.execute("""
                SELECT *
                FROM trades
                WHERE trade_id = ?
            """, (trade_id,)).fetchone()

            return dict(row) if row else None

    def get_trades(self, limit=100):

        with self.connection() as conn:

            rows = conn.execute("""
                SELECT *
                FROM trades
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [dict(row) for row in rows]

    def get_open_trades(self):

        with self.connection() as conn:

            rows = conn.execute("""
                SELECT *
                FROM trades
                WHERE status IN ('OPEN', 'PENDING')
                ORDER BY id DESC
            """).fetchall()

            return [dict(row) for row in rows]

    def log_event(self, event_type, message):

        with self._lock:
            with self.connection() as conn:

                conn.execute("""
                    INSERT INTO system_events (
                        event_type,
                        message
                    )
                    VALUES (?, ?)
                """, (event_type, message))

    def get_events(self, limit=100):

        with self.connection() as conn:

            rows = conn.execute("""
                SELECT *
                FROM system_events
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [dict(row) for row in rows]


storage = Storage()
