import threading
import time
from datetime import datetime, timezone


class StateManager:

    def __init__(self):
        self._lock = threading.RLock()

        self._state = {
            "bot_name": "Vrotex Bot V1",
            "status": "INITIALIZING",
            "mode": "DEMO",
            "started_at": None,
            "last_heartbeat": None,
            "last_scan": None,
            "connected": False,
            "market_data_ready": False,
            "execution_enabled": False,
            "shutdown_requested": False,
            "instruments": [],
            "active_trades": 0,
            "daily_trades": 0,
            "consecutive_losses": 0,
            "daily_pnl": 0.0,
            "errors": [],
        }

    @staticmethod
    def utc_now():
        return datetime.now(timezone.utc).isoformat()

    def initialize(self, mode="DEMO", instruments=None):
        with self._lock:
            self._state["status"] = "STARTING"
            self._state["mode"] = mode
            self._state["started_at"] = self.utc_now()
            self._state["last_heartbeat"] = self.utc_now()
            self._state["instruments"] = list(instruments or [])
            self._state["shutdown_requested"] = False

    def set_status(self, status):
        with self._lock:
            self._state["status"] = str(status).upper()
            self._state["last_heartbeat"] = self.utc_now()

    def heartbeat(self):
        with self._lock:
            self._state["last_heartbeat"] = self.utc_now()

    def update_scan(self):
        with self._lock:
            self._state["last_scan"] = self.utc_now()

    def set_connection(self, connected):
        with self._lock:
            self._state["connected"] = bool(connected)

    def set_market_data_ready(self, ready):
        with self._lock:
            self._state["market_data_ready"] = bool(ready)

    def set_execution_enabled(self, enabled):
        with self._lock:
            self._state["execution_enabled"] = bool(enabled)

    def set_active_trades(self, count):
        with self._lock:
            self._state["active_trades"] = max(0, int(count))

    def set_daily_trades(self, count):
        with self._lock:
            self._state["daily_trades"] = max(0, int(count))

    def set_consecutive_losses(self, count):
        with self._lock:
            self._state["consecutive_losses"] = max(0, int(count))

    def set_daily_pnl(self, pnl):
        with self._lock:
            self._state["daily_pnl"] = float(pnl)

    def add_error(self, message):
        with self._lock:
            self._state["errors"].append({
                "time": self.utc_now(),
                "message": str(message),
            })

            # Keep recent errors only in runtime memory.
            self._state["errors"] = self._state["errors"][-20:]

    def request_shutdown(self):
        with self._lock:
            self._state["shutdown_requested"] = True
            self._state["status"] = "STOPPING"

    def get_state(self):
        with self._lock:
            return dict(self._state)

    def is_running(self):
        with self._lock:
            return (
                self._state["status"] == "RUNNING"
                and not self._state["shutdown_requested"]
            )


state_manager = StateManager()
