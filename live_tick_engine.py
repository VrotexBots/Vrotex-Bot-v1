import asyncio
import json
import threading
import time
from urllib.parse import urlsplit

import websocket

from config import settings
from logging_config import get_logger
from broker.exness_connector import exness_connector


logger = get_logger("live_tick_engine")


class LiveTickEngine:

    def __init__(self):

        self.connector = exness_connector

        self.instruments = list(settings.INSTRUMENTS)

        self.latest_ticks = {}

        self.connected = False
        self.running = False

        self.last_tick_time = {}
        self.last_error = None

        self.websocket_app = None
        self.thread = None

        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        self.reconnect_attempts = 0
        self.max_reconnect_delay = 60

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

        account_id = connection.account_id

        path = (
            f"/v1/server-events/accounts/"
            f"{account_id}/ws/ticks"
        )

        url = f"{scheme}://{parsed.netloc}{path}"

        return url, path

    def build_headers(self, path):

        connection = self.connector.connection

        headers = connection.sign_request(
            method="GET",
            path=path,
            body=b"",
            idempotency_key="",
        )

        return headers

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

        ws.send(
            json.dumps(subscription)
        )

        with self._lock:

            self.connected = True
            self.last_error = None

    def on_message(self, ws, message):

        try:

            data = json.loads(message)

        except json.JSONDecodeError:

            logger.warning(
                "Invalid WebSocket message received."
            )

            return

        if not isinstance(data, dict):
            return

        if "error_message" in data:

            logger.error(
                "Exness stream error: %s",
                data.get("error_message"),
            )

            self.last_error = data.get(
                "error_message"
            )

            return

        instrument = data.get("instrument")

        if instrument not in self.instruments:
            return

        try:

            bid = float(data["bid"])
            ask = float(data["ask"])

        except (KeyError, TypeError, ValueError):

            return

        if bid <= 0 or ask <= 0 or ask < bid:
            return

        tick = {
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "spread": ask - bid,
            "timestamp": data.get("timestamp"),
            "received_at": time.time(),
        }

        with self._lock:

            self.latest_ticks[instrument] = tick

            self.last_tick_time[instrument] = (
                tick["received_at"]
            )

        logger.debug(
            "Tick | %s | Bid: %s | Ask: %s",
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

        logger.warning(
            "Tick stream closed | Code: %s | Message: %s",
            close_status_code,
            close_message,
        )

    def connection_loop(self):

        delay = 1

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

                if self._stop_event.is_set():
                    break

                self.connected = False

                self.reconnect_attempts += 1

                logger.warning(
                    "Tick stream disconnected. "
                    "Reconnect attempt %s",
                    self.reconnect_attempts,
                )

                self._stop_event.wait(delay)

                delay = min(
                    delay * 2,
                    self.max_reconnect_delay,
                )

            except Exception as exc:

                self.connected = False
                self.last_error = str(exc)

                logger.exception(
                    "Tick stream connection failure."
                )

                self.reconnect_attempts += 1

                self._stop_event.wait(delay)

                delay = min(
                    delay * 2,
                    self.max_reconnect_delay,
                )

        self.connected = False
        self.running = False

        logger.info(
            "Live tick engine thread stopped."
        )

    async def start(self):

        if self.running:
            return {
                "running": True,
                "connected": self.connected,
                "message": "Already running",
            }

        if not self.connector.connected:

            result = await self.connector.connect()

            if not result.get("success"):
                raise ConnectionError(
                    "Cannot start tick engine: "
                    "Exness connection failed"
                )

        self._stop_event.clear()

        self.running = True

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

        return {
            "running": True,
            "connected": self.connected,
            "instruments": self.instruments,
            "message": "Tick engine started",
        }

    async def stop(self):

        self._stop_event.set()

        if self.websocket_app is not None:

            try:
                self.websocket_app.close()

            except Exception:
                pass

        if self.thread is not None:

            await asyncio.to_thread(
                self.thread.join,
                10,
            )

        self.running = False
        self.connected = False

        logger.info(
            "Live tick engine stopped."
        )

    def get_tick(self, instrument):

        instrument = instrument.upper()

        with self._lock:

            tick = self.latest_ticks.get(instrument)

            if tick is None:
                return None

            return dict(tick)

    def get_all_ticks(self):

        with self._lock:

            return {
                symbol: dict(tick)
                for symbol, tick
                in self.latest_ticks.items()
            }

    def is_tick_fresh(
        self,
        instrument,
        max_age_seconds=10,
    ):

        instrument = instrument.upper()

        with self._lock:

            timestamp = self.last_tick_time.get(
                instrument
            )

        if timestamp is None:
            return False

        return (
            time.time() - timestamp
        ) <= max_age_seconds

    def get_status(self):

        with self._lock:

            ticks_received = len(
                self.latest_ticks
            )

            return {
                "running": self.running,
                "connected": self.connected,
                "instruments": self.instruments,
                "ticks_received": ticks_received,
                "latest_ticks": self.get_all_ticks(),
                "reconnect_attempts": (
                    self.reconnect_attempts
                ),
                "last_error": self.last_error,
            }


live_tick_engine = LiveTickEngine()
