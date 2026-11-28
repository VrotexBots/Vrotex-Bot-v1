
# trade_management.py
# Vrotex Bot V1
# Autonomous Trade Management
#
# Responsibilities:
# - Discover and track confirmed Exness positions.
# - Track entry, current price, SL, TP and P/L.
# - Monitor M1 external structure-break evidence.
# - Request break-even stop updates.
# - Detect closed positions.
# - Record trade outcomes.
# - Update Risk Manager trade statistics.
# - Preserve trade history in SQLite.
#
# Uses the existing ExnessConnection and RiskManager.

import asyncio
import json
import os
import sqlite3
import time
from datetime import date, datetime, time as datetime_time, timezone
from zoneinfo import ZoneInfo

from decimal import Decimal, InvalidOperation

from logging_config import get_logger
from exness_connection import exness_connection


logger = get_logger("trading.trade_management")


class TradeManager:

    VERSION = "1.1"

    MONITOR_INTERVAL = 2

    ALLOWED_INSTRUMENTS = {
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    }

    def __init__(self):

        self.connection = exness_connection

        self.active_positions = {}
        self.closed_positions = {}

        self.running = False
        self.monitor_task = None

        self.last_snapshot = None
        self.last_sync_time = None
        self.last_error = None

        self.db_path = os.path.join(
            "data",
            "vrotex_v1.db",
        )

        self._lock = asyncio.Lock()

        self._initialise_database()

        self._load_active_positions()

    # ==========================================================
    # DATABASE
    # ==========================================================

    def _database(self):

        os.makedirs(
            os.path.dirname(self.db_path) or ".",
            exist_ok=True,
        )

        connection = sqlite3.connect(
            self.db_path,
            timeout=30,
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _initialise_database(self):

        with self._database() as db:

            db.execute("""
                CREATE TABLE IF NOT EXISTS
                vrotex_managed_trades (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume TEXT,
                    entry_price TEXT,
                    current_price TEXT,
                    stop_loss TEXT,
                    take_profit TEXT,
                    initial_stop_loss TEXT,
                    risk_percent TEXT,
                    score REAL,
                    status TEXT NOT NULL,
                    break_even_triggered INTEGER DEFAULT 0,
                    break_even_applied INTEGER DEFAULT 0,
                    outcome TEXT,
                    profit_loss TEXT,
                    opened_at REAL,
                    closed_at REAL,
                    updated_at REAL,
                    raw_position TEXT
                )
            """)

            db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_vrotex_managed_status
                ON vrotex_managed_trades(status)
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS
                vrotex_trade_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details TEXT,
                    created_at REAL NOT NULL
                )
            """)

            # One immutable opening-equity baseline per Johannesburg trading day.
            # It must be captured close to midnight; late startup never guesses it.
            db.execute("""
                CREATE TABLE IF NOT EXISTS
                vrotex_daily_risk_state (
                    trading_day TEXT PRIMARY KEY,
                    start_of_day_equity TEXT NOT NULL,
                    captured_at REAL NOT NULL,
                    source TEXT NOT NULL
                )
            """)

    def _load_active_positions(self):

        with self._database() as db:

            rows = db.execute("""
                SELECT *
                FROM vrotex_managed_trades
                WHERE status = 'OPEN'
            """).fetchall()

        for row in rows:

            position = dict(row)

            position["break_even_triggered"] = bool(
                position["break_even_triggered"]
            )

            position["break_even_applied"] = bool(
                position["break_even_applied"]
            )

            position["raw_position"] = self._json_load(
                position.get("raw_position")
            )

            self.active_positions[
                str(position["position_id"])
            ] = position

        logger.info(
            "Trade manager restored %s active records",
            len(self.active_positions),
        )

    @staticmethod
    def _json_load(value):

        if not value:
            return {}

        try:
            return json.loads(value)

        except (ValueError, TypeError):
            return {}

    def _save_position(self, position):

        now = time.time()

        position["updated_at"] = now

        with self._database() as db:

            db.execute("""
                INSERT INTO vrotex_managed_trades (
                    position_id,
                    symbol,
                    side,
                    volume,
                    entry_price,
                    current_price,
                    stop_loss,
                    take_profit,
                    initial_stop_loss,
                    risk_percent,
                    score,
                    status,
                    break_even_triggered,
                    break_even_applied,
                    outcome,
                    profit_loss,
                    opened_at,
                    closed_at,
                    updated_at,
                    raw_position
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(position_id)
                DO UPDATE SET
                    current_price = excluded.current_price,
                    stop_loss = excluded.stop_loss,
                    take_profit = excluded.take_profit,
                    status = excluded.status,
                    break_even_triggered =
                        excluded.break_even_triggered,
                    break_even_applied =
                        excluded.break_even_applied,
                    outcome = excluded.outcome,
                    profit_loss = excluded.profit_loss,
                    closed_at = excluded.closed_at,
                    updated_at = excluded.updated_at,
                    raw_position = excluded.raw_position
            """, (
                str(position["position_id"]),
                position.get("symbol"),
                position.get("side"),
                str(position.get("volume", "")),
                str(position.get("entry_price", "")),
                str(position.get("current_price", "")),
                str(position.get("stop_loss", "")),
                str(position.get("take_profit", "")),
                str(position.get("initial_stop_loss", "")),
                str(position.get("risk_percent", "")),
                position.get("score"),
                position.get("status", "OPEN"),
                int(position.get("break_even_triggered", False)),
                int(position.get("break_even_applied", False)),
                position.get("outcome"),
                str(position.get("profit_loss", "")),
                position.get("opened_at", now),
                position.get("closed_at"),
                now,
                json.dumps(
                    position.get("raw_position", {}),
                    default=str,
                ),
            ))

    def _record_event(
        self,
        position_id,
        event,
        details=None,
    ):

        with self._database() as db:

            db.execute("""
                INSERT INTO vrotex_trade_events (
                    position_id,
                    event,
                    details,
                    created_at
                )
                VALUES (?, ?, ?, ?)
            """, (
                str(position_id),
                event,
                json.dumps(details or {}, default=str),
                time.time(),
            ))

    # ==========================================================
    # PERSISTENT DAILY RISK SNAPSHOTS
    # ==========================================================

    RISK_TIMEZONE = ZoneInfo("Africa/Johannesburg")
    DAY_START_CAPTURE_WINDOW_SECONDS = 300

    @classmethod
    def _johannesburg_day(cls, timestamp=None):
        """Return the Johannesburg calendar date for an epoch timestamp."""
        value = time.time() if timestamp is None else float(timestamp)
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(
            cls.RISK_TIMEZONE
        ).date()

    def record_day_start_equity(
        self,
        equity,
        *,
        captured_at=None,
        source="BROKER_MIDNIGHT_SNAPSHOT",
    ):
        """Persist the true day-opening equity; reject late/ambiguous baselines.

        The capture must occur within five minutes after Johannesburg midnight.
        Existing baselines are immutable to prevent a later balance from
        silently resetting the daily-loss calculation.
        """
        amount = self._decimal(equity)
        if amount is None or amount <= 0:
            raise ValueError("Day-start equity must be a positive finite value.")

        stamp = time.time() if captured_at is None else float(captured_at)
        if not source or not isinstance(source, str):
            raise ValueError("A verifiable day-start equity source is required.")

        local_dt = datetime.fromtimestamp(
            stamp, tz=timezone.utc
        ).astimezone(self.RISK_TIMEZONE)
        seconds_after_midnight = (
            local_dt.hour * 3600 + local_dt.minute * 60 + local_dt.second
        )
        if seconds_after_midnight > self.DAY_START_CAPTURE_WINDOW_SECONDS:
            raise ValueError(
                "Day-start equity was not captured within five minutes of "
                "Johannesburg midnight; refusing to invent a baseline."
            )

        trading_day = local_dt.date().isoformat()
        with self._database() as db:
            db.execute("""
                INSERT OR IGNORE INTO vrotex_daily_risk_state (
                    trading_day, start_of_day_equity, captured_at, source
                ) VALUES (?, ?, ?, ?)
            """, (trading_day, str(amount), stamp, source))
            row = db.execute("""
                SELECT start_of_day_equity, captured_at, source
                FROM vrotex_daily_risk_state
                WHERE trading_day = ?
            """, (trading_day,)).fetchone()

        return {
            "trading_day": trading_day,
            "start_of_day_equity": float(row["start_of_day_equity"]),
            "captured_at": float(row["captured_at"]),
            "source": row["source"],
            "created": abs(float(row["captured_at"]) - stamp) < 0.001,
        }

    def build_risk_snapshot(
        self,
        current_equity,
        *,
        pending_instruments=(),
        as_of=None,
    ):
        """Build the shared RiskSnapshot from persistent managed-trade history.

        Fails closed when the true midnight equity baseline is unavailable.
        `pending_instruments` must come from the live executor/order state.
        """
        from risk_management import RiskSnapshot

        equity = self._decimal(current_equity)
        if equity is None or equity <= 0:
            raise ValueError("Current broker equity must be positive and finite.")

        stamp = time.time() if as_of is None else float(as_of)
        day = self._johannesburg_day(stamp)
        day_start = datetime.combine(
            day, datetime_time.min, tzinfo=self.RISK_TIMEZONE
        ).timestamp()
        day_end = datetime.combine(
            date.fromordinal(day.toordinal() + 1),
            datetime_time.min,
            tzinfo=self.RISK_TIMEZONE,
        ).timestamp()

        with self._database() as db:
            baseline = db.execute("""
                SELECT start_of_day_equity
                FROM vrotex_daily_risk_state
                WHERE trading_day = ?
            """, (day.isoformat(),)).fetchone()

            if baseline is None:
                raise RuntimeError(
                    "Daily risk baseline unavailable for "
                    f"{day.isoformat()} Africa/Johannesburg. "
                    "Trading must remain blocked until a verified midnight "
                    "equity snapshot is recorded."
                )

            rows = db.execute("""
                SELECT symbol, status, outcome, opened_at, closed_at
                FROM vrotex_managed_trades
                WHERE opened_at >= ? AND opened_at < ?
            """, (day_start, day_end)).fetchall()

            active_rows = db.execute("""
                SELECT position_id, symbol
                FROM vrotex_managed_trades
                WHERE status = 'OPEN'
            """).fetchall()

            loss_rows = db.execute("""
                SELECT COUNT(*) AS loss_count
                FROM vrotex_managed_trades
                WHERE status = 'CLOSED'
                  AND outcome = 'LOSS'
                  AND closed_at >= ? AND closed_at < ?
            """, (day_start, day_end)).fetchone()

            recent_outcomes = db.execute("""
                SELECT outcome
                FROM vrotex_managed_trades
                WHERE status = 'CLOSED'
                  AND closed_at >= ? AND closed_at < ?
                  AND outcome IS NOT NULL
                ORDER BY closed_at DESC, rowid DESC
            """, (day_start, day_end)).fetchall()

        trades_taken = len(rows)
        daily_losses = int(loss_rows["loss_count"] or 0)
        consecutive_losses = 0
        for outcome_row in recent_outcomes:
            outcome = str(outcome_row["outcome"] or "").strip().upper()
            if outcome == "LOSS":
                consecutive_losses += 1
            else:
                # A win or breakeven ends the current losing streak.
                break
        start_equity = float(baseline["start_of_day_equity"])
        daily_loss_percent = max(
            0.0, ((start_equity - float(equity)) / start_equity) * 100.0
        )

        active_symbols = tuple(sorted({
            str(row["symbol"]).upper()
            for row in active_rows if row["symbol"]
        }))
        pending_symbols = tuple(sorted({
            str(symbol).strip().upper()
            for symbol in pending_instruments
            if isinstance(symbol, str) and symbol.strip()
        }))

        return RiskSnapshot(
            equity=float(equity),
            start_of_day_equity=start_equity,
            daily_loss_percent=daily_loss_percent,
            daily_losses_today=daily_losses,
            open_trade_count=len(active_rows),
            trades_taken_today=trades_taken,
            trading_day=day,
            active_instruments=active_symbols,
            pending_instruments=pending_symbols,
            consecutive_losses_today=consecutive_losses,
        )

    # ==========================================================
    # HELPERS
    # ==========================================================

    @staticmethod
    def _decimal(value):

        try:

            number = Decimal(str(value))

            if not number.is_finite():
                return None

            return number

        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):

            return None

    @staticmethod
    def _walk_dicts(value):

        if isinstance(value, dict):

            yield value

            for item in value.values():

                yield from TradeManager._walk_dicts(
                    item
                )

        elif isinstance(value, list):

            for item in value:

                yield from TradeManager._walk_dicts(
                    item
                )

    @staticmethod
    def _normalise_side(value):

        value = str(value or "").lower()

        if value in ("buy", "long", "bullish"):
            return "buy"

        if value in ("sell", "short", "bearish"):
            return "sell"

        return None

    @staticmethod
    def _extract(
        item,
        names,
    ):

        for name in names:

            if item.get(name) is not None:
                return item[name]

        return None

    # ==========================================================
    # POSITION DISCOVERY
    # ==========================================================

    def _extract_positions(self, snapshot):

        positions = []

        if not isinstance(snapshot, (dict, list)):
            return positions

        for item in self._walk_dicts(snapshot):

            symbol = str(
                self._extract(
                    item,
                    (
                        "instrument",
                        "symbol",
                        "instrument_name",
                    ),
                ) or ""
            ).upper()

            if symbol not in self.ALLOWED_INSTRUMENTS:
                continue

            position_id = self._extract(
                item,
                (
                    "position_id",
                    "positionId",
                    "ticket",
                    "id",
                ),
            )

            if position_id is None:
                continue

            side = self._normalise_side(
                self._extract(
                    item,
                    (
                        "side",
                        "direction",
                        "type",
                    ),
                )
            )

            if side is None:
                continue

            volume = self._decimal(
                self._extract(
                    item,
                    (
                        "volume",
                        "lots",
                        "quantity",
                    ),
                )
            )

            entry = self._decimal(
                self._extract(
                    item,
                    (
                        "entry_price",
                        "open_price",
                        "openPrice",
                        "price",
                    ),
                )
            )

            if volume is None or entry is None:
                continue

            positions.append({
                "position_id": str(position_id),
                "symbol": symbol,
                "side": side,
                "volume": str(volume),
                "entry_price": str(entry),

                "current_price": str(
                    self._extract(
                        item,
                        (
                            "current_price",
                            "market_price",
                            "currentPrice",
                            "price_current",
                        ),
                    ) or ""
                ),

                "stop_loss": str(
                    self._extract(
                        item,
                        (
                            "stop_loss_price",
                            "stop_loss",
                            "sl",
                        ),
                    ) or ""
                ),

                "take_profit": str(
                    self._extract(
                        item,
                        (
                            "take_profit_price",
                            "take_profit",
                            "tp",
                        ),
                    ) or ""
                ),

                "profit_loss": str(
                    self._extract(
                        item,
                        (
                            "profit",
                            "profit_loss",
                            "unrealized_pnl",
                            "unrealized_profit",
                        ),
                    ) or ""
                ),

                "comment": str(
                    item.get("comment", "")
                ),

                "raw_position": item,
            })

        return positions

    # ==========================================================
    # REGISTER CONFIRMED POSITION
    # ==========================================================

    async def register_confirmed_position(
        self,
        execution_result,
        setup=None,
    ):

        """
        Register a position confirmed by the executor.

        Expected executor result:
            {
                "status": "CONFIRMED",
                "verification": {
                    "position_id": ...
                    "position": {...}
                }
            }
        """

        if not isinstance(execution_result, dict):
            return False

        if execution_result.get("status") != "CONFIRMED":
            return False

        verification = execution_result.get(
            "verification",
            {},
        )

        if not isinstance(verification, dict):
            return False

        position = verification.get("position")

        if not isinstance(position, dict):
            return False

        position_id = (
            verification.get("position_id")
            or position.get("position_id")
            or position.get("positionId")
            or position.get("id")
            or position.get("ticket")
        )

        if position_id is None:
            return False

        setup = setup or {}

        symbol = str(
            execution_result.get(
                "instrument",
                setup.get("instrument", ""),
            )
        ).upper()

        side = self._normalise_side(
            execution_result.get(
                "side",
                setup.get("side"),
            )
        )

        entry = self._decimal(
            setup.get(
                "entry_price",
                position.get("entry_price"),
            )
        )

        volume = self._decimal(
            execution_result.get(
                "volume",
                setup.get("volume"),
            )
        )

        if (
            symbol not in self.ALLOWED_INSTRUMENTS
            or side is None
            or entry is None
            or volume is None
        ):
            return False

        now = time.time()

        managed = {
            "position_id": str(position_id),
            "symbol": symbol,
            "side": side,
            "volume": str(volume),
            "entry_price": str(entry),
            "current_price": str(
                position.get("current_price", "")
            ),
            "stop_loss": str(
                setup.get(
                    "stop_loss_price",
                    position.get("stop_loss_price", ""),
                )
            ),
            "take_profit": str(
                setup.get(
                    "take_profit_price",
                    position.get("take_profit_price", ""),
                )
            ),
            "initial_stop_loss": str(
                setup.get("stop_loss_price", "")
            ),
            "risk_percent": str(
                setup.get("risk_percent", "")
            ),
            "score": setup.get("score"),
            "status": "OPEN",
            "break_even_triggered": False,
            "break_even_applied": False,
            "outcome": None,
            "profit_loss": "",
            "opened_at": now,
            "closed_at": None,
            "raw_position": position,
        }

        async with self._lock:

            self.active_positions[str(position_id)] = managed

            self._save_position(managed)

            self._record_event(
                position_id,
                "POSITION_REGISTERED",
                {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": str(entry),
                },
            )

        logger.info(
            "Trade management registered position %s | %s %s",
            position_id,
            symbol,
            side.upper(),
        )

        return True

    # ==========================================================
    # SNAPSHOT SYNCHRONISATION
    # ==========================================================

    async def sync_positions(self):

        if not self.connection.connected:
            return {
                "success": False,
                "reason": "Exness connection unavailable",
            }

        async with self._lock:

            snapshot = (
                await self.connection.get_trading_snapshot()
            )

            if not isinstance(snapshot, (dict, list)):
                return {
                    "success": False,
                    "reason": "Invalid Exness snapshot",
                }

            self.last_snapshot = snapshot

            broker_positions = self._extract_positions(
                snapshot
            )

            seen_ids = set()

            for broker_position in broker_positions:

                position_id = broker_position["position_id"]

                seen_ids.add(position_id)

                if position_id in self.active_positions:

                    managed = self.active_positions[
                        position_id
                    ]

                    for field in (
                        "current_price",
                        "stop_loss",
                        "take_profit",
                        "profit_loss",
                    ):

                        value = broker_position.get(field)

                        if value not in (None, ""):
                            managed[field] = value

                    managed["raw_position"] = (
                        broker_position["raw_position"]
                    )

                    self._save_position(managed)

                else:

                    # Adopt only Vrotex-managed positions.
                    comment = broker_position.get(
                        "comment",
                        "",
                    )

                    if "vrotex" not in comment.lower():
                        continue

                    await self._adopt_position(
                        broker_position
                    )

            # A previously open position no longer appearing
            # in a successful snapshot is treated as closed.
            for position_id in list(
                self.active_positions.keys()
            ):

                if position_id not in seen_ids:

                    await self._finalise_position(
                        position_id,
                        "CLOSED",
                    )

            self.last_sync_time = time.time()
            self.last_error = None

            return {
                "success": True,
                "broker_positions": len(broker_positions),
                "managed_positions": len(self.active_positions),
            }

    async def _adopt_position(self, broker_position):

        position_id = broker_position["position_id"]

        now = time.time()

        managed = {
            **broker_position,
            "initial_stop_loss": broker_position.get(
                "stop_loss",
                "",
            ),
            "risk_percent": "",
            "score": None,
            "status": "OPEN",
            "break_even_triggered": False,
            "break_even_applied": False,
            "outcome": None,
            "opened_at": now,
            "closed_at": None,
        }

        self.active_positions[position_id] = managed

        self._save_position(managed)

        self._record_event(
            position_id,
            "POSITION_ADOPTED",
            broker_position,
        )

        logger.info(
            "Existing Vrotex position adopted: %s",
            position_id,
        )

    # ==========================================================
    # MARKET STATE AND BREAK EVEN
    # ==========================================================

    async def update_market_state(
        self,
        symbol,
        current_price,
        m1_external_break=False,
    ):

        """
        Called by the scanner when fresh market evidence
        becomes available.

        The M1 external break must be supplied explicitly
        by the existing technical analysis pipeline.
        """

        symbol = str(symbol).upper()

        price = self._decimal(current_price)

        if price is None or price <= 0:
            return False

        updated = 0

        for position_id, position in list(
            self.active_positions.items()
        ):

            if position["symbol"] != symbol:
                continue

            position["current_price"] = str(price)

            if m1_external_break is True:

                position["break_even_triggered"] = True

                self._record_event(
                    position_id,
                    "M1_EXTERNAL_BREAK",
                    {
                        "symbol": symbol,
                        "price": str(price),
                    },
                )

                await self._apply_break_even(
                    position_id,
                    position,
                )

            self._save_position(position)

            updated += 1

        return updated

    async def _apply_break_even(
        self,
        position_id,
        position,
    ):

        """
        Move SL to entry after the supplied M1 external break.

        This calls a broker modify_position method if the
        connection provides one.

        The current exness_connection.py does not yet expose
        modify_position(), so the manager records the request
        as pending until that connection method is implemented.
        """

        if position.get("break_even_applied"):
            return True

        entry = self._decimal(
            position.get("entry_price")
        )

        if entry is None:
            return False

        modifier = getattr(
            self.connection,
            "modify_position",
            None,
        )

        if not callable(modifier):

            position["break_even_status"] = (
                "WAITING_FOR_BROKER_MODIFY_METHOD"
            )

            self._record_event(
                position_id,
                "BREAK_EVEN_PENDING",
                {
                    "entry_price": str(entry),
                    "reason": (
                        "ExnessConnection.modify_position "
                        "is not available"
                    ),
                },
            )

            self._save_position(position)

            logger.warning(
                "Break-even triggered for %s but broker "
                "position modification method is unavailable",
                position_id,
            )

            return False

        try:

            result = modifier(
                position_id=position_id,
                stop_loss_price=str(entry),
            )

            if asyncio.iscoroutine(result):
                result = await result

            if not isinstance(result, dict):
                return False

            position["break_even_applied"] = True
            position["break_even_status"] = "APPLIED"
            position["stop_loss"] = str(entry)

            self._save_position(position)

            self._record_event(
                position_id,
                "BREAK_EVEN_APPLIED",
                {
                    "entry_price": str(entry),
                    "broker_response": result,
                },
            )

            logger.info(
                "Break-even stop updated: %s",
                position_id,
            )

            return True

        except Exception:

            logger.exception(
                "Break-even modification failed: %s",
                position_id,
            )

            return False

    # ==========================================================
    # TRADE OUTCOMES
    # ==========================================================

    @staticmethod
    def _determine_outcome(profit_loss):

        value = TradeManager._decimal(profit_loss)

        if value is None:
            return "UNKNOWN"

        if value > 0:
            return "WIN"

        if value < 0:
            return "LOSS"

        return "BREAKEVEN"

    async def _update_risk_manager(self, outcome):

        try:

            from risk_manager import risk_manager

            if outcome == "WIN":

                risk_manager.register_win()

            elif outcome == "LOSS":

                risk_manager.register_loss()

            logger.info(
                "Risk Manager updated with outcome: %s",
                outcome,
            )

        except Exception:

            logger.exception(
                "Risk Manager outcome update failed"
            )

    async def _finalise_position(
        self,
        position_id,
        reason="CLOSED",
    ):

        position = self.active_positions.get(
            str(position_id)
        )

        if position is None:
            return False

        raw = position.get("raw_position", {})

        profit = self._extract(
            raw,
            (
                "realized_profit",
                "realized_pnl",
                "profit",
                "profit_loss",
            ),
        )

        if profit is None:
            profit = position.get("profit_loss")

        outcome = self._determine_outcome(profit)

        position["status"] = "CLOSED"
        position["closed_at"] = time.time()
        position["outcome"] = outcome
        position["profit_loss"] = (
            str(profit)
            if profit is not None
            else ""
        )

        self._save_position(position)

        self._record_event(
            position_id,
            "POSITION_CLOSED",
            {
                "reason": reason,
                "outcome": outcome,
                "profit_loss": position["profit_loss"],
            },
        )

        self.closed_positions[str(position_id)] = position

        self.active_positions.pop(
            str(position_id),
            None,
        )

        if outcome in ("WIN", "LOSS"):

            await self._update_risk_manager(outcome)

        logger.info(
            "TRADE CLOSED | %s | Outcome=%s | P/L=%s",
            position_id,
            outcome,
            position["profit_loss"],
        )

        return True

    # ==========================================================
    # MONITORING LOOP
    # ==========================================================

    async def monitor_once(self):

        try:

            return await self.sync_positions()

        except Exception as exc:

            self.last_error = str(exc)

            logger.exception(
                "Trade monitoring cycle failed"
            )

            return {
                "success": False,
                "reason": str(exc),
            }

    async def _monitor_loop(self):

        logger.info(
            "Trade management monitoring started"
        )

        while self.running:

            await self.monitor_once()

            await asyncio.sleep(
                self.MONITOR_INTERVAL
            )

        logger.info(
            "Trade management monitoring stopped"
        )

    async def start(self):

        if self.running:
            return {
                "success": True,
                "status": "ALREADY_RUNNING",
            }

        if not self.connection.connected:

            return {
                "success": False,
                "reason": "Exness connection unavailable",
            }

        self.running = True

        self.monitor_task = asyncio.create_task(
            self._monitor_loop()
        )

        return {
            "success": True,
            "status": "RUNNING",
        }

    async def stop(self):

        self.running = False

        if self.monitor_task is not None:

            self.monitor_task.cancel()

            try:
                await self.monitor_task

            except asyncio.CancelledError:
                pass

            self.monitor_task = None

        return {
            "success": True,
            "status": "STOPPED",
        }

    # ==========================================================
    # MANUAL OUTCOME RECORDING
    # ==========================================================

    async def record_outcome(
        self,
        position_id,
        profit_loss,
    ):

        position_id = str(position_id)

        position = self.active_positions.get(
            position_id
        )

        if position is None:
            return False

        position["profit_loss"] = str(profit_loss)

        return await self._finalise_position(
            position_id,
            "OUTCOME_RECORDED",
        )

    # ==========================================================
    # STATUS
    # ==========================================================

    def get_status(self):

        return {
            "version": self.VERSION,
            "running": self.running,
            "active_positions": len(
                self.active_positions
            ),
            "closed_positions": len(
                self.closed_positions
            ),
            "tracked_positions": list(
                self.active_positions.keys()
            ),
            "last_sync_time": self.last_sync_time,
            "last_error": self.last_error,
            "break_even_pending": sum(
                1
                for position in self.active_positions.values()
                if (
                    position.get("break_even_triggered")
                    and not position.get("break_even_applied")
                )
            ),
        }


trade_manager = TradeManager()
