
import asyncio
import json
import math
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import websocket

from config import settings
from logging_config import get_logger
from exness_connector import exness_connector


logger = get_logger("live_tick_engine")


class LiveTickEngine:

    MAX_RECONNECT_DELAY = 60
    INITIAL_RECONNECT_DELAY = 1

    DEFAULT_MAX_TICK_AGE = getattr(
        settings,
        "LIVE_TICK_MAX_AGE_SECONDS",
        10,
    )

    STARTUP_TIMEOUT = getattr(
        settings,
        "LIVE_TICK_STARTUP_TIMEOUT_SECONDS",
        45,
    )

    def __init__(self):

        self.connector = exness_connector
        self.instruments = list(settings.INSTRUMENTS)

        self.latest_ticks = {}
        self.last_tick_time = {}

        self.connected = False
        self.running = False
        self.ready = False

        self.last_error = None

        self.websocket_app = None
        self.thread = None

        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        self._loop = None
        self._ready_event = None

        self.reconnect_attempts = 0

    @staticmethod
    def _parse_timestamp(value):

        if isinstance(value, (int, float)):

            timestamp = float(value)

            if not math.isfinite(timestamp):
                return None

            if timestamp > 100000000000:
                timestamp /= 1000.0

            return timestamp

        if isinstance(value, str):

            try:

                parsed = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )

                if parsed.tzinfo is None:

                    parsed = parsed.replace(
                        tzinfo=timezone.utc
                    )

                return parsed.timestamp()

            except ValueError:
                return None

        return None

    def build_websocket_url(self):

        connection = self.connector.connection

        if not connection.access_point:

            raise RuntimeError(
                "Exness Access Point is unavailable"
            )

        parsed = urlsplit(
            connection.access_point
        )

        if parsed.scheme == "https":
            scheme = "wss"

        elif parsed.scheme == "http":
            scheme = "ws"

        elif parsed.scheme in ("ws", "wss"):
            scheme = parsed.scheme

        else:

            raise ValueError(
                "Unsupported Exness Access Point scheme"
            )

        if not parsed.netloc:

            raise ValueError(
                "Invalid Exness Access Point"
            )

        account_id = connection.account_id

        if not account_id:

            raise RuntimeError(
                "Exness account ID is unavailable"
            )

        path = (
            f"/v1/server-events/accounts/"
            f"{account_id}/ws/ticks"
        )

        return (
            f"{scheme}://{parsed.netloc}{path}",
            path,
        )

    def build_headers(self, path):

        connection = self.connector.connection

        headers = connection.sign_request(
            method="GET",
            path=path,
            body=b"",
            idempotency_key="",
        )

        if not isinstance(headers, dict):

            raise RuntimeError(
                "Exness authentication headers are invalid"
            )

        return [
            f"{key}: {value}"
            for key, value in headers.items()
        ]

    def on_open(self, ws):

        logger.info(
            "Exness live tick WebSocket connected."
        )

        subscription = {
            "id": "vrotex-live-ticks",
            "subscribe": {
                "event": "ticks",
                "instruments": self.instruments,
            },
        }

        try:

            ws.send(
                json.dumps(subscription)
            )

            with self._lock:

                self.connected = True
                self.last_error = None

            logger.info(
                "Subscribed to live instruments: %s",
                self.instruments,
            )

        except Exception as exc:

            self.last_error = str(exc)

            logger.exception(
                "Live tick subscription failed."
            )

            ws.close()

    def on_message(self, ws, message):

        try:

            data = json.loads(message)

        except (json.JSONDecodeError, TypeError):

            logger.warning(
                "Invalid WebSocket message received."
            )

            return

        if not isinstance(data, dict):
            return

        if "error_message" in data:

            self.last_error = str(
                data.get("error_message")
            )

            logger.error(
                "Exness stream error: %s",
                self.last_error,
            )

            return

        instrument = str(
            data.get("instrument", "")
        ).upper()

        if instrument not in self.instruments:
            return

        try:

            bid = float(data["bid"])
            ask = float(data["ask"])

        except (KeyError, TypeError, ValueError):

            return

        if not math.isfinite(bid):
            return

        if not math.isfinite(ask):
            return

        if bid <= 0 or ask < bid:
            return

        source_timestamp = self._parse_timestamp(
            data.get("timestamp")
        )

        if source_timestamp is None:

            logger.warning(
                "Tick rejected: missing or invalid source timestamp."
            )

            return

        received_at = time.time()

        age = received_at - source_timestamp

        if (
            age < -5
            or age > self.DEFAULT_MAX_TICK_AGE
        ):

            logger.warning(
                "Stale or future tick rejected: %s age=%s",
                instrument,
                age,
            )

            return

        tick = {
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2.0,
            "spread": ask - bid,
            "timestamp": source_timestamp,
            "received_at": received_at,
            "age_seconds": max(0.0, age),
            "valid": True,
        }

        with self._lock:

            self.latest_ticks[instrument] = tick

            self.last_tick_time[instrument] = received_at

            self.ready = all(
                self._is_fresh_locked(symbol)
                for symbol in self.instruments
            )

            ready = self.ready

        if ready and self._loop and self._ready_event:

            try:

                self._loop.call_soon_threadsafe(
                    self._ready_event.set
                )

            except RuntimeError:
                pass

        logger.debug(
            "Tick | %s | Bid=%s | Ask=%s",
            instrument,
            bid,
            ask,
        )

    def on_error(self, ws, error):

        self.last_error = str(error)

        logger.error(
            "Live tick WebSocket error: %s",
            error,
        )

    def on_close(
        self,
        ws,
        close_status_code,
        close_message,
    ):

        with self._lock:

            self.connected = False
            self.ready = False

        logger.warning(
            "Tick stream closed | Code=%s | Message=%s",
            close_status_code,
            close_message,
        )

    def connection_loop(self):

        delay = self.INITIAL_RECONNECT_DELAY

        while not self._stop_event.is_set():

            try:

                url, path = self.build_websocket_url()

                headers = self.build_headers(path)

                self.websocket_app = websocket.WebSocketApp(
                    url,
                    header=headers,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )

                logger.info(
                    "Connecting live tick stream."
                )

                self.websocket_app.run_forever(
                    ping_interval=30,
                    ping_timeout=10,
                )

            except Exception as exc:

                self.last_error = str(exc)

                logger.exception(
                    "Tick stream connection failure."
                )

            finally:

                with self._lock:

                    self.connected = False
                    self.ready = False

            if self._stop_event.is_set():
                break

            self.reconnect_attempts += 1

            logger.warning(
                "Tick stream reconnect attempt %s in %s seconds.",
                self.reconnect_attempts,
                delay,
            )

            self._stop_event.wait(delay)

            delay = min(
                delay * 2,
                self.MAX_RECONNECT_DELAY,
            )

        with self._lock:

            self.connected = False
            self.ready = False
            self.running = False

        logger.info(
            "Live tick engine thread stopped."
        )

    async def start(self):

        if self.running:
            return self.get_status()

        if not self.connector.connected:

            result = await self.connector.connect()

            if not result.get("success"):

                raise ConnectionError(
                    "Cannot start tick engine: Exness connection failed"
                )

        if not self.connector.connection.access_point:

            raise ConnectionError(
                "Exness access point is unavailable"
            )

        self._loop = asyncio.get_running_loop()
        self._ready_event = asyncio.Event()

        self._stop_event.clear()

        with self._lock:

            self.running = True
            self.connected = False
            self.ready = False
            self.last_error = None
            self.reconnect_attempts = 0

        self.thread = threading.Thread(
            target=self.connection_loop,
            name="Vrotex-Live-Ticks",
            daemon=True,
        )

        self.thread.start()

        logger.info(
            "Live tick engine started for %s instruments.",
            len(self.instruments),
        )

        try:

            await asyncio.wait_for(
                self._ready_event.wait(),
                timeout=self.STARTUP_TIMEOUT,
            )

            if not self.is_ready():

                raise ConnectionError(
                    "Live tick feed lost readiness during startup"
                )

            logger.info(
                "Live Bid/Ask feed ready for all instruments."
            )

            return self.get_status()

        except Exception:

            await self.stop()

            raise

    async def stop(self):

        self._stop_event.set()

        ws = self.websocket_app

        if ws is not None:

            try:

                ws.close()

            except Exception as exc:

                logger.warning(
                    "WebSocket shutdown warning: %s",
                    exc,
                )

        thread = self.thread

        if thread is not None and thread.is_alive():

            await asyncio.to_thread(
                thread.join,
                10,
            )

        with self._lock:

            self.running = False
            self.connected = False
            self.ready = False

        self.websocket_app = None
        self.thread = None

        logger.info(
            "Live tick engine stopped."
        )

    def _is_fresh_locked(
        self,
        instrument,
        max_age_seconds=None,
    ):

        tick = self.latest_ticks.get(instrument)

        if tick is None:
            return False

        max_age = (
            max_age_seconds
            if max_age_seconds is not None
            else self.DEFAULT_MAX_TICK_AGE
        )

        age = time.time() - tick["timestamp"]

        return (
            -5 <= age <= max_age
            and tick["bid"] > 0
            and tick["ask"] >= tick["bid"]
        )

    def get_tick(
        self,
        instrument,
        max_age_seconds=None,
    ):

        instrument = str(instrument).upper()

        with self._lock:

            if not self._is_fresh_locked(
                instrument,
                max_age_seconds,
            ):

                return None

            tick = self.latest_ticks.get(instrument)

            return dict(tick) if tick else None

    def get_all_ticks(self):

        result = {}

        for instrument in self.instruments:

            tick = self.get_tick(instrument)

            if tick is not None:
                result[instrument] = tick

        return result

    def is_tick_fresh(
        self,
        instrument,
        max_age_seconds=10,
    ):

        instrument = str(instrument).upper()

        with self._lock:

            return self._is_fresh_locked(
                instrument,
                max_age_seconds,
            )

    def is_ready(self):

        with self._lock:

            return (
                self.running
                and self.connected
                and all(
                    self._is_fresh_locked(symbol)
                    for symbol in self.instruments
                )
            )

    def get_status(self):

        with self._lock:

            ticks = {}

            for instrument in self.instruments:

                if self._is_fresh_locked(instrument):

                    ticks[instrument] = dict(
                        self.latest_ticks[instrument]
                    )

            return {
                "running": self.running,
                "connected": self.connected,
                "ready": self.is_ready(),
                "instruments": list(self.instruments),
                "ticks_received": len(ticks),
                "expected_ticks": len(self.instruments),
                "latest_ticks": ticks,
                "reconnect_attempts": self.reconnect_attempts,
                "last_error": self.last_error,
            }


live_tick_engine = LiveTickEngine()
