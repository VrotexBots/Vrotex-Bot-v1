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
        self.tick_counts = {}

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
        self._connected_event = None

        self.reconnect_attempts = 0

    # --------------------------------------------------
    # TIMESTAMP HANDLING
    # --------------------------------------------------

    @staticmethod
    def _parse_timestamp(value):

        if isinstance(value, (int, float)):

            timestamp = float(value)

            if not math.isfinite(timestamp):
                return None

            # Milliseconds -> seconds
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
                pass

            try:

                timestamp = float(value)

                if timestamp > 100000000000:
                    timestamp /= 1000.0

                if math.isfinite(timestamp):
                    return timestamp

            except (ValueError, TypeError):
                pass

        return None

    # --------------------------------------------------
    # WEBSOCKET URL
    # --------------------------------------------------

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

        url = (
            f"{scheme}://{parsed.netloc}{path}"
        )

        return url, path

    # --------------------------------------------------
    # AUTHENTICATION
    # --------------------------------------------------

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

    # --------------------------------------------------
    # CONNECTION SIGNALS
    # --------------------------------------------------

    def _signal_connected(self):

        if self._loop and self._connected_event:

            try:

                self._loop.call_soon_threadsafe(
                    self._connected_event.set
                )

            except RuntimeError:
                pass

    def _signal_tick_ready(self):

        if self._loop and self._ready_event:

            try:

                self._loop.call_soon_threadsafe(
                    self._ready_event.set
                )

            except RuntimeError:
                pass

    # --------------------------------------------------
    # WEBSOCKET OPEN
    # --------------------------------------------------

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

            # Connection readiness is separate from
            # market tick readiness.
            self._signal_connected()

            logger.info(
                "Tick subscription sent successfully: %s",
                self.instruments,
            )

            logger.info(
                "Waiting for Exness to push new ticks."
            )

        except Exception as exc:

            self.last_error = str(exc)

            logger.exception(
                "Live tick subscription failed."
            )

            ws.close()

    # --------------------------------------------------
    # MESSAGE EXTRACTION
    # --------------------------------------------------

    def _extract_tick_messages(self, data):

        """
        Extract tick objects from common JSON message
        wrappers without assuming every message is a tick.
        """

        if isinstance(data, list):

            for item in data:

                yield from self._extract_tick_messages(
                    item
                )

            return

        if not isinstance(data, dict):
            return

        # Direct tick message
        if (
            "instrument" in data
            or "symbol" in data
            or "instrument_name" in data
        ):

            yield data
            return

        # Common message containers
        for key in (
            "data",
            "tick",
            "ticks",
            "payload",
            "result",
        ):

            nested = data.get(key)

            if isinstance(nested, (dict, list)):

                yield from self._extract_tick_messages(
                    nested
                )

    # --------------------------------------------------
    # TICK PROCESSING
    # --------------------------------------------------

    def _process_tick(self, data):

        instrument = str(
            data.get(
                "instrument",
                data.get(
                    "symbol",
                    data.get(
                        "instrument_name",
                        data.get(
                            "instrumentName",
                            "",
                        ),
                    ),
                ),
            )
        ).upper().strip()

        if instrument not in self.instruments:

            logger.debug(
                "Ignoring tick for unconfigured instrument: %s",
                instrument,
            )

            return False

        # Bid/Ask are required.
        try:

            bid = float(data["bid"])
            ask = float(data["ask"])

        except (
            KeyError,
            TypeError,
            ValueError,
        ):

            logger.debug(
                "Tick ignored: missing Bid/Ask for %s",
                instrument,
            )

            return False

        if not math.isfinite(bid):
            return False

        if not math.isfinite(ask):
            return False

        if bid <= 0 or ask < bid:

            logger.warning(
                "Invalid Bid/Ask rejected: %s | Bid=%s | Ask=%s",
                instrument,
                bid,
                ask,
            )

            return False

        # Accept supported timestamp fields.
        source_timestamp = None

        for timestamp_key in (
            "timestamp",
            "time",
            "ts",
            "server_time",
        ):

            if timestamp_key in data:

                source_timestamp = self._parse_timestamp(
                    data.get(timestamp_key)
                )

                if source_timestamp is not None:
                    break

        received_at = time.time()

        # If the provider message does not contain a
        # timestamp, use reception time. The tick is still
        # a new WebSocket event, not a polled price.
        timestamp_source = (
            "exness"
            if source_timestamp is not None
            else "received"
        )

        if source_timestamp is None:
            source_timestamp = received_at

        age = received_at - source_timestamp

        # Reject clearly invalid timestamps.
        if age < -5:

            logger.warning(
                "Future tick rejected: %s | Age=%s",
                instrument,
                age,
            )

            return False

        # Do not reject a tick merely because the
        # provider's timestamp is old. Reception itself
        # is recorded separately. Freshness is checked
        # using received_at by the strategy.

        tick = {
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2.0,
            "spread": ask - bid,
            "timestamp": source_timestamp,
            "timestamp_source": timestamp_source,
            "received_at": received_at,
            "age_seconds": max(0.0, age),
            "valid": True,
        }

        with self._lock:

            self.latest_ticks[instrument] = tick

            self.last_tick_time[instrument] = received_at

            self.tick_counts[instrument] = (
                self.tick_counts.get(
                    instrument,
                    0,
                ) + 1
            )

            # All instruments being fresh is the
            # market-data readiness condition.
            self.ready = all(
                self._is_fresh_locked(symbol)
                for symbol in self.instruments
            )

            ready = self.ready

        if ready:
            self._signal_tick_ready()

        logger.debug(
            "LIVE TICK | %s | Bid=%s | Ask=%s | Count=%s",
            instrument,
            bid,
            ask,
            self.tick_counts.get(instrument, 0),
        )

        return True

    # --------------------------------------------------
    # WEBSOCKET MESSAGE
    # --------------------------------------------------

    def on_message(self, ws, message):

        try:

            data = json.loads(message)

        except (
            json.JSONDecodeError,
            TypeError,
        ):

            logger.warning(
                "Non-JSON WebSocket message received."
            )

            return

        if isinstance(data, dict):

            # Provider error
            if (
                "error_message" in data
                or "error" in data
            ):

                self.last_error = str(
                    data.get(
                        "error_message",
                        data.get("error"),
                    )
                )

                logger.error(
                    "Exness WebSocket message error: %s",
                    self.last_error,
                )

                return

            # Subscription acknowledgement or
            # informational event.
            if (
                "id" in data
                and "subscribe" not in data
            ):

                logger.info(
                    "WebSocket response received: %s",
                    data.get("id"),
                )

        messages_processed = 0

        for tick_data in self._extract_tick_messages(
            data
        ):

            if self._process_tick(tick_data):
                messages_processed += 1

        # Diagnostics for messages which are valid JSON
        # but contain no recognized tick.
        if messages_processed == 0:

            logger.debug(
                "WebSocket message received but no recognized tick found."
            )

    # --------------------------------------------------
    # WEBSOCKET ERROR
    # --------------------------------------------------

    def on_error(self, ws, error):

        self.last_error = str(error)

        logger.error(
            "Live tick WebSocket error: %s",
            error,
        )

    # --------------------------------------------------
    # WEBSOCKET CLOSE
    # --------------------------------------------------

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

    # --------------------------------------------------
    # RECONNECT LOOP
    # --------------------------------------------------

    def connection_loop(self):

        delay = self.INITIAL_RECONNECT_DELAY

        while not self._stop_event.is_set():

            try:

                url, path = self.build_websocket_url()

                headers = self.build_headers(path)

                self.websocket_app = (
                    websocket.WebSocketApp(
                        url,
                        header=headers,
                        on_open=self.on_open,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                    )
                )

                logger.info(
                    "Connecting to Exness live tick stream."
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

    # --------------------------------------------------
    # START
    # --------------------------------------------------

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

        self._connected_event = asyncio.Event()

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

        logger.info(
            "Waiting for WebSocket connection, not polling prices."
        )

        try:

            # Startup waits for the WebSocket connection,
            # NOT for every market to produce a tick.
            await asyncio.wait_for(
                self._connected_event.wait(),
                timeout=self.STARTUP_TIMEOUT,
            )

            if not self.connected:

                raise ConnectionError(
                    "WebSocket connection lost during startup"
                )

            logger.info(
                "Live tick WebSocket connection established."
            )

            logger.info(
                "Tick reception is event-driven. "
                "Waiting for Exness market updates."
            )

            return self.get_status()

        except Exception:

            await self.stop()

            raise

    # --------------------------------------------------
    # STOP
    # --------------------------------------------------

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

        if (
            thread is not None
            and thread.is_alive()
        ):

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

    # --------------------------------------------------
    # FRESHNESS
    # --------------------------------------------------

    def _is_fresh_locked(
        self,
        instrument,
        max_age_seconds=None,
    ):

        tick = self.latest_ticks.get(
            instrument
        )

        if tick is None:
            return False

        max_age = (
            max_age_seconds
            if max_age_seconds is not None
            else self.DEFAULT_MAX_TICK_AGE
        )

        # Freshness is measured from reception time.
        age = (
            time.time()
            - tick["received_at"]
        )

        return (
            0 <= age <= max_age
            and tick["bid"] > 0
            and tick["ask"] >= tick["bid"]
        )

    # --------------------------------------------------
    # GET TICK
    # --------------------------------------------------

    def get_tick(
        self,
        instrument,
        max_age_seconds=None,
    ):

        instrument = str(
            instrument
        ).upper()

        with self._lock:

            if not self._is_fresh_locked(
                instrument,
                max_age_seconds,
            ):

                return None

            tick = self.latest_ticks.get(
                instrument
            )

            return (
                dict(tick)
                if tick
                else None
            )

    # --------------------------------------------------
    # GET ALL FRESH TICKS
    # --------------------------------------------------

    def get_all_ticks(self):

        result = {}

        for instrument in self.instruments:

            tick = self.get_tick(
                instrument
            )

            if tick is not None:

                result[instrument] = tick

        return result

    # --------------------------------------------------
    # PER-INSTRUMENT FRESHNESS
    # --------------------------------------------------

    def is_tick_fresh(
        self,
        instrument,
        max_age_seconds=10,
    ):

        instrument = str(
            instrument
        ).upper()

        with self._lock:

            return self._is_fresh_locked(
                instrument,
                max_age_seconds,
            )

    # --------------------------------------------------
    # MARKET DATA READINESS
    # --------------------------------------------------

    def is_ready(self):

        with self._lock:

            return (
                self.running
                and self.connected
                and all(
                    self._is_fresh_locked(
                        symbol
                    )
                    for symbol in self.instruments
                )
            )

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_status(self):

        with self._lock:

            ticks = {}

            instrument_status = {}

            for instrument in self.instruments:

                tick = self.latest_ticks.get(
                    instrument
                )

                fresh = self._is_fresh_locked(
                    instrument
                )

                if fresh and tick:

                    ticks[instrument] = dict(
                        tick
                    )

                age = None

                if tick:

                    age = max(
                        0.0,
                        time.time()
                        - tick["received_at"],
                    )

                instrument_status[instrument] = {
                    "received": tick is not None,
                    "fresh": fresh,
                    "tick_count": self.tick_counts.get(
                        instrument,
                        0,
                    ),
                    "age_seconds": age,
                    "bid": (
                        tick["bid"]
                        if tick
                        else None
                    ),
                    "ask": (
                        tick["ask"]
                        if tick
                        else None
                    ),
                }

            all_fresh = all(
                self._is_fresh_locked(
                    symbol
                )
                for symbol in self.instruments
            )

            return {
                "running": self.running,
                "connected": self.connected,

                # True means every configured instrument
                # has a fresh tick.
                "ready": (
                    self.running
                    and self.connected
                    and all_fresh
                ),

                # Connection health is independent of
                # market tick freshness.
                "stream_connected": self.connected,

                "instruments": list(
                    self.instruments
                ),

                "ticks_received": len(
                    ticks
                ),

                "expected_ticks": len(
                    self.instruments
                ),

                "latest_ticks": ticks,

                "instrument_status": (
                    instrument_status
                ),

                "tick_counts": dict(
                    self.tick_counts
                ),

                "reconnect_attempts": (
                    self.reconnect_attempts
                ),

                "last_error": self.last_error,
            }


live_tick_engine = LiveTickEngine()
