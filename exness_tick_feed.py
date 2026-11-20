import asyncio
import json
import math
import threading
import time

from datetime import datetime, timezone
from urllib.parse import urlsplit

import websocket

from logging_config import get_logger
from exness_connection import exness_connection


logger = get_logger("exness_tick_feed")


class ExnessTickFeed:

    INSTRUMENTS = (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    )

    WS_PATH_TEMPLATE = (
        "/v1/server-events/accounts/{account_id}/ws/ticks"
    )

    MAX_RECONNECT_DELAY = 30
    INITIAL_RECONNECT_DELAY = 2
    MAX_TICK_AGE_SECONDS = 10
    STARTUP_TIMEOUT_SECONDS = 45

    def __init__(self, connection=None):

        self.connection = connection or exness_connection

        self.websocket_app = None
        self.websocket_thread = None

        self.running = False
        self.connected = False
        self.ready = False

        self.last_error = None
        self.last_message_time = None
        self.reconnect_count = 0

        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self._loop = None
        self._ready_event = None

        self._ticks = {
            symbol: None
            for symbol in self.INSTRUMENTS
        }

    @staticmethod
    def _parse_timestamp(value):

        if isinstance(value, (int, float)):

            timestamp = float(value)

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

    @staticmethod
    def _websocket_url(access_point, path):

        if not access_point:
            raise ConnectionError(
                "Exness access point is unavailable"
            )

        access_point = access_point.strip().rstrip("/")

        if access_point.startswith("https://"):
            base = "wss://" + access_point[8:]

        elif access_point.startswith("http://"):
            base = "ws://" + access_point[7:]

        elif access_point.startswith("wss://"):
            base = access_point

        elif access_point.startswith("ws://"):
            base = access_point

        else:
            base = "wss://" + access_point

        parsed = urlsplit(base)

        if not parsed.netloc:
            raise ValueError(
                "Invalid Exness WebSocket access point"
            )

        return base + path

    def _get_headers(self):

        account_id = self.connection.account_id

        if not account_id:
            raise ConnectionError(
                "Exness account ID is unavailable"
            )

        path = self.WS_PATH_TEMPLATE.format(
            account_id=account_id
        )

        signed = self.connection.sign_request(
            method="GET",
            path=path,
            body=b"",
            idempotency_key="",
        )

        if not isinstance(signed, dict):
            raise ValueError(
                "Exness signing returned invalid headers"
            )

        headers = []

        for key, value in signed.items():
            headers.append(
                f"{key}: {value}"
            )

        return path, headers

    def _set_connected(self, value):

        with self._lock:
            self.connected = bool(value)

    def _set_error(self, error):

        with self._lock:
            self.last_error = str(error)

    def _on_open(self, ws):

        logger.info(
            "Exness live tick WebSocket connected."
        )

        self._set_connected(True)

        subscription = {
            "id": "vrotex-v1-live-ticks",
            "subscribe": {
                "event": "ticks",
                "instruments": list(self.INSTRUMENTS),
            },
        }

        try:

            ws.send(
                json.dumps(subscription)
            )

            logger.info(
                "Subscribed to live ticks: %s",
                ", ".join(self.INSTRUMENTS),
            )

        except Exception as exc:

            self._set_error(exc)

            logger.error(
                "WebSocket subscription failed: %s",
                exc,
            )

            ws.close()

    def _on_message(self, ws, message):

        try:

            payload = json.loads(message)

            if not isinstance(payload, dict):
                return

            instrument = str(
                payload.get("instrument", "")
            ).upper()

            if instrument not in self.INSTRUMENTS:
                return

            bid = float(payload.get("bid"))
            ask = float(payload.get("ask"))

            timestamp = self._parse_timestamp(
                payload.get("timestamp")
            )

            if not math.isfinite(bid):
                return

            if not math.isfinite(ask):
                return

            if bid <= 0 or ask < bid:
                return

            if timestamp is None:
                return

            now = time.time()

            age = now - timestamp

            if age < -5:
                return

            if age > self.MAX_TICK_AGE_SECONDS:
                return

            tick = {
                "instrument": instrument,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2.0,
                "timestamp": timestamp,
                "received_at": now,
                "age_seconds": max(0.0, age),
                "valid": True,
            }

            with self._lock:

                self._ticks[instrument] = tick

                self.last_message_time = now

                self.ready = all(
                    self._tick_is_fresh_locked(symbol)
                    for symbol in self.INSTRUMENTS
                )

                ready = self.ready

            if ready and self._loop and self._ready_event:

                self._loop.call_soon_threadsafe(
                    self._ready_event.set
                )

        except Exception as exc:

            logger.warning(
                "Invalid Exness tick message: %s",
                exc,
            )

    def _on_error(self, ws, error):

        self._set_error(error)

        logger.error(
            "Exness WebSocket error: %s",
            error,
        )

    def _on_close(
        self,
        ws,
        close_status_code,
        close_msg
    ):

        self._set_connected(False)

        with self._lock:
            self.ready = False

        logger.warning(
            "Exness WebSocket closed. Code=%s Message=%s",
            close_status_code,
            close_msg,
        )

    def _tick_is_fresh_locked(self, instrument):

        tick = self._ticks.get(instrument)

        if not tick:
            return False

        age = time.time() - tick["timestamp"]

        return (
            age >= -5
            and age <= self.MAX_TICK_AGE_SECONDS
            and tick["bid"] > 0
            and tick["ask"] >= tick["bid"]
        )

    def _run_connection_loop(self):

        delay = self.INITIAL_RECONNECT_DELAY

        while not self._stop_event.is_set():

            try:

                path, headers = self._get_headers()

                url = self._websocket_url(
                    self.connection.access_point,
                    path,
                )

                self.websocket_app = websocket.WebSocketApp(
                    url,
                    header=headers,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )

                self.websocket_app.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                )

            except Exception as exc:

                self._set_error(exc)

                logger.error(
                    "WebSocket connection failed: %s",
                    exc,
                )

            finally:

                self._set_connected(False)

                with self._lock:
                    self.ready = False

            if self._stop_event.is_set():
                break

            self.reconnect_count += 1

            logger.warning(
                "Reconnecting to Exness live ticks in %s seconds. Attempt=%s",
                delay,
                self.reconnect_count,
            )

            self._stop_event.wait(delay)

            delay = min(
                delay * 2,
                self.MAX_RECONNECT_DELAY,
            )

        logger.info(
            "Exness tick feed connection loop stopped."
        )

    async def start(self):

        if self.running:
            return self.get_status()

        if not self.connection.connected:
            raise ConnectionError(
                "Exness REST connection must be established first"
            )

        if not self.connection.access_point:
            raise ConnectionError(
                "Exness access point has not been resolved"
            )

        self._loop = asyncio.get_running_loop()
        self._ready_event = asyncio.Event()

        self._stop_event.clear()

        self.running = True
        self.ready = False

        self.last_error = None
        self.reconnect_count = 0

        self.websocket_thread = threading.Thread(
            target=self._run_connection_loop,
            name="Vrotex-Exness-TickFeed",
            daemon=True,
        )

        self.websocket_thread.start()

        logger.info(
            "Waiting for initial live Bid/Ask prices for all three instruments."
        )

        try:

            await asyncio.wait_for(
                self._ready_event.wait(),
                timeout=self.STARTUP_TIMEOUT_SECONDS,
            )

            logger.info(
                "Live tick feed ready for all three instruments."
            )

            return self.get_status()

        except asyncio.TimeoutError:

            logger.error(
                "Live tick startup timed out. Not all instruments supplied fresh ticks."
            )

            await self.stop()

            raise TimeoutError(
                "Live tick feed did not become ready for all three instruments"
            )

    def get_tick(self, instrument):

        instrument = str(instrument).upper()

        if instrument not in self.INSTRUMENTS:
            return None

        with self._lock:

            if not self._tick_is_fresh_locked(instrument):
                return None

            tick = self._ticks.get(instrument)

            return dict(tick) if tick else None

    def get_all_ticks(self):

        result = {}

        for instrument in self.INSTRUMENTS:

            tick = self.get_tick(instrument)

            if tick is not None:
                result[instrument] = tick

        return result

    def is_ready(self):

        with self._lock:

            return (
                self.running
                and self.connected
                and all(
                    self._tick_is_fresh_locked(symbol)
                    for symbol in self.INSTRUMENTS
                )
            )

    async def stop(self):

        if not self.running:
            return

        logger.info(
            "Stopping Exness live tick feed."
        )

        self.running = False
        self._stop_event.set()

        ws = self.websocket_app

        if ws is not None:

            try:
                ws.close()

            except Exception as exc:

                logger.warning(
                    "WebSocket close warning: %s",
                    exc,
                )

        thread = self.websocket_thread

        if thread and thread.is_alive():

            await asyncio.to_thread(
                thread.join,
                5,
            )

        self.websocket_app = None
        self.websocket_thread = None

        self._set_connected(False)

        with self._lock:
            self.ready = False

        logger.info(
            "Exness live tick feed stopped."
        )

    def get_status(self):

        with self._lock:

            ticks = {}

            for instrument in self.INSTRUMENTS:

                tick = self._ticks.get(instrument)

                if tick and self._tick_is_fresh_locked(instrument):
                    ticks[instrument] = dict(tick)

            return {
                "running": self.running,
                "connected": self.connected,
                "ready": self.is_ready(),
                "instruments": list(self.INSTRUMENTS),
                "ticks_received": len(ticks),
                "expected_ticks": len(self.INSTRUMENTS),
                "reconnect_count": self.reconnect_count,
                "last_message_time": self.last_message_time,
                "last_error": self.last_error,
                "ticks": ticks,
            }


exness_tick_feed = ExnessTickFeed()
