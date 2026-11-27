
"""
VROTEX BOT V1 - ORB SESSION ENGINE
File: orb_session_engine.py

Detects trading sessions and opening-range windows.
All session times use their configured local time zones.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from orb_config import (
    ORB_ENABLED,
    ORB_SESSIONS,
    ORB_CANDLE_DURATION_MINUTES,
)


class ORBSessionEngine:

    def __init__(self):
        self.sessions = ORB_SESSIONS
        self.session_states = {}

    @staticmethod
    def _utc_now():
        return datetime.now(timezone.utc)

    def _session_open(self, session_name, session_date):
        config = self.sessions[session_name]

        local_zone = ZoneInfo(config["timezone"])

        local_open = datetime(
            year=session_date.year,
            month=session_date.month,
            day=session_date.day,
            hour=config["hour"],
            minute=config["minute"],
            tzinfo=local_zone,
        )

        return local_open.astimezone(timezone.utc)

    def get_session_window(self, session_name, now=None):

        if not ORB_ENABLED:
            return None

        if session_name not in self.sessions:
            raise ValueError(
                f"Unknown ORB session: {session_name}"
            )

        config = self.sessions[session_name]

        if not config.get("enabled", False):
            return None

        now = now or self._utc_now()

        if now.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware.")

        local_zone = ZoneInfo(config["timezone"])
        local_date = now.astimezone(local_zone).date()

        opening_time = self._session_open(
            session_name,
            local_date,
        )

        closing_time = opening_time + timedelta(
            minutes=ORB_CANDLE_DURATION_MINUTES
        )

        return {
            "session": session_name,
            "timezone": config["timezone"],
            "opening_time": opening_time,
            "closing_time": closing_time,
            "status": self._get_status(
                now,
                opening_time,
                closing_time,
            ),
        }

    @staticmethod
    def _get_status(now, opening_time, closing_time):

        if now < opening_time:
            return "WAITING"

        if opening_time <= now < closing_time:
            return "OPENING_CANDLE_FORMING"

        return "OPENING_CANDLE_COMPLETE"

    def get_active_sessions(self, now=None):

        now = now or self._utc_now()

        active = []

        for session_name in self.sessions:

            window = self.get_session_window(
                session_name,
                now,
            )

            if window is None:
                continue

            if window["status"] != "WAITING":
                active.append(window)

        return active

    def get_opening_candle_window(
        self,
        session_name,
        now=None,
    ):

        window = self.get_session_window(
            session_name,
            now,
        )

        if window is None:
            return None

        return {
            "session": session_name,
            "start": window["opening_time"],
            "end": window["closing_time"],
            "complete": (
                window["status"] == "OPENING_CANDLE_COMPLETE"
            ),
        }

    def is_opening_candle_complete(
        self,
        session_name,
        now=None,
    ):

        window = self.get_session_window(
            session_name,
            now,
        )

        if window is None:
            return False

        return (
            window["status"] == "OPENING_CANDLE_COMPLETE"
        )

    def update_session_state(
        self,
        session_name,
        symbol,
        opening_high=None,
        opening_low=None,
        completed=False,
    ):

        key = (session_name, symbol)

        self.session_states[key] = {
            "session": session_name,
            "symbol": symbol,
            "opening_high": opening_high,
            "opening_low": opening_low,
            "completed": bool(completed),
            "updated_at": self._utc_now(),
        }

    def get_session_state(self, session_name, symbol):

        return self.session_states.get(
            (session_name, symbol)
        )

    def reset_session(self, session_name, symbol):

        self.session_states.pop(
            (session_name, symbol),
            None,
        )
