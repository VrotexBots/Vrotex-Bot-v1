import time
from datetime import datetime, timezone

from state_manager import state_manager


class HealthMonitor:

    def __init__(self, heartbeat_timeout=120):
        self.heartbeat_timeout = heartbeat_timeout
        self.created_at = time.time()

    def check_heartbeat(self):
        state = state_manager.get_state()

        heartbeat = state.get("last_heartbeat")

        if not heartbeat:
            return False

        try:
            heartbeat_time = datetime.fromisoformat(heartbeat)

            if heartbeat_time.tzinfo is None:
                heartbeat_time = heartbeat_time.replace(
                    tzinfo=timezone.utc
                )

            age = (
                datetime.now(timezone.utc) - heartbeat_time
            ).total_seconds()

            return age <= self.heartbeat_timeout

        except (ValueError, TypeError):
            return False

    def check_connection(self):
        state = state_manager.get_state()
        return bool(state.get("connected"))

    def check_market_data(self):
        state = state_manager.get_state()
        return bool(state.get("market_data_ready"))

    def check_shutdown(self):
        state = state_manager.get_state()
        return bool(state.get("shutdown_requested"))

    def get_health(self):

        heartbeat_ok = self.check_heartbeat()
        connection_ok = self.check_connection()
        market_data_ok = self.check_market_data()
        shutdown = self.check_shutdown()

        if shutdown:
            status = "STOPPING"

        elif not heartbeat_ok:
            status = "UNHEALTHY"

        elif not connection_ok:
            status = "DEGRADED"

        elif not market_data_ok:
            status = "DEGRADED"

        else:
            status = "HEALTHY"

        return {
            "status": status,
            "heartbeat": heartbeat_ok,
            "connection": connection_ok,
            "market_data": market_data_ok,
            "shutdown_requested": shutdown,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


health_monitor = HealthMonitor()
