import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from logging_config import get_logger
from exness_connector import exness_connector


logger = get_logger("market_data_engine")


class MarketDataEngine:

    # PILOT ONLY
    PILOT_INSTRUMENTS = [
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    ]

    REQUIRED_TIMEFRAMES = [
        "H1",
        "M5",
        "M1",
    ]

    MAX_CANDLES_PER_REQUEST = 1000

    # Request protection
    MIN_REQUEST_INTERVAL = 2.0

    MAX_RETRIES = 2

    INITIAL_RETRY_DELAY = 5

    RATE_LIMIT_COOLDOWN = 30

    # Cache lifetime
    CACHE_TTL = {
        "M1": 60,
        "M5": 300,
        "H1": 3600,
    }

    def __init__(self):

        self.connector = exness_connector

        self.connected = False
        self.ready = False

        self._lock = asyncio.Lock()

        self._cache = {}

        self._last_request_time = 0

        self._rate_limit_until = 0

        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.rate_limit_hits = 0

        self.last_error = None

        self.pair_status = {}

        logger.info(
            "Market Data Engine initialized."
        )

        logger.info(
            "Pilot instruments: %s",
            self.PILOT_INSTRUMENTS,
        )

        logger.info(
            "Required timeframes: %s",
            self.REQUIRED_TIMEFRAMES,
        )

    # --------------------------------------------------
    # CONNECTION
    # --------------------------------------------------

    async def ensure_connection(self):

        if (
            self.connector.connected
            and self.connector.connection.connected
        ):
            self.connected = True
            return True

        result = await self.connector.connect()

        self.connected = bool(
            result.get("success")
        )

        if not self.connected:

            self.last_error = result.get(
                "error",
                "Connection failed",
            )

            logger.error(
                "Market data connection unavailable."
            )

        return self.connected

    # --------------------------------------------------
    # REQUEST PACING
    # --------------------------------------------------

    async def _wait_for_request_slot(self):

        now = time.monotonic()

        if now < self._rate_limit_until:

            wait_time = (
                self._rate_limit_until - now
            )

            logger.warning(
                "Rate-limit cooldown: %.1f seconds",
                wait_time,
            )

            await asyncio.sleep(wait_time)

        elapsed = (
            time.monotonic()
            - self._last_request_time
        )

        if elapsed < self.MIN_REQUEST_INTERVAL:

            wait_time = (
                self.MIN_REQUEST_INTERVAL
                - elapsed
            )

            await asyncio.sleep(wait_time)

        self._last_request_time = (
            time.monotonic()
        )

    # --------------------------------------------------
    # RATE LIMIT DETECTION
    # --------------------------------------------------

    @staticmethod
    def _is_rate_limit_error(error):

        message = str(error).upper()

        indicators = [
            "429",
            "3015",
            "REQUEST_RATE_LIMIT",
            "TOO MANY REQUESTS",
            "RATE LIMIT",
        ]

        return any(
            indicator in message
            for indicator in indicators
        )

    # --------------------------------------------------
    # CACHE
    # --------------------------------------------------

    def _get_cached_candles(
        self,
        instrument,
        timeframe,
        count,
    ):

        key = (
            instrument,
            timeframe,
        )

        cached = self._cache.get(key)

        if not cached:
            return None

        age = (
            time.monotonic()
            - cached["timestamp"]
        )

        ttl = self.CACHE_TTL.get(
            timeframe,
            60,
        )

        if age > ttl:
            return None

        candles = cached["candles"]

        # Never return insufficient cached history.
        if len(candles) < count:
            return None

        return candles[-count:]

    def _store_cache(
        self,
        instrument,
        timeframe,
        candles,
    ):

        key = (
            instrument,
            timeframe,
        )

        self._cache[key] = {
            "candles": candles,
            "timestamp": time.monotonic(),
        }

    def clear_cache(
        self,
        instrument=None,
        timeframe=None,
    ):

        if (
            instrument is None
            and timeframe is None
        ):

            self._cache.clear()

            logger.info(
                "Market data cache cleared."
            )

            return

        keys = list(
            self._cache.keys()
        )

        for key in keys:

            cached_instrument, cached_timeframe = key

            if (
                instrument is not None
                and cached_instrument != instrument
            ):
                continue

            if (
                timeframe is not None
                and cached_timeframe != timeframe
            ):
                continue

            self._cache.pop(
                key,
                None,
            )

    # --------------------------------------------------
    # CANDLE NORMALIZATION
    # --------------------------------------------------

    @staticmethod
    def _normalize_candles(candles):

        if not isinstance(
            candles,
            list,
        ):
            return []

        normalized = []

        for candle in candles:

            if not isinstance(
                candle,
                dict,
            ):
                continue

            item = dict(candle)

            # Normalize common timestamp field names.
            if "time" not in item:

                for timestamp_key in (
                    "timestamp",
                    "datetime",
                    "date",
                ):

                    if timestamp_key in item:

                        item["time"] = item[
                            timestamp_key
                        ]

                        break

            normalized.append(item)

        return normalized

    # --------------------------------------------------
    # REQUEST CANDLES
    # --------------------------------------------------

    async def request_candles(
        self,
        instrument,
        timeframe,
        count=100,
        price_type="bid",
        force_refresh=False,
    ):

        instrument = instrument.upper()

        timeframe = timeframe.upper()

        if instrument not in self.PILOT_INSTRUMENTS:

            raise ValueError(
                f"Instrument not in pilot: {instrument}"
            )

        if timeframe not in self.REQUIRED_TIMEFRAMES:

            raise ValueError(
                f"Unsupported pilot timeframe: {timeframe}"
            )

        if count <= 0:

            raise ValueError(
                "Candle count must be greater than zero."
            )

        if count > self.MAX_CANDLES_PER_REQUEST:

            count = (
                self.MAX_CANDLES_PER_REQUEST
            )

        # Cache first.
        if not force_refresh:

            cached = self._get_cached_candles(
                instrument,
                timeframe,
                count,
            )

            if cached is not None:

                logger.debug(
                    "Cache hit: %s %s",
                    instrument,
                    timeframe,
                )

                return cached

        async with self._lock:

            # Recheck cache after waiting for lock.
            if not force_refresh:

                cached = self._get_cached_candles(
                    instrument,
                    timeframe,
                    count,
                )

                if cached is not None:
                    return cached

            if not await self.ensure_connection():

                raise ConnectionError(
                    "Exness connection unavailable."
                )

            last_exception = None

            for attempt in range(
                1,
                self.MAX_RETRIES + 2,
            ):

                try:

                    await self._wait_for_request_slot()

                    self.total_requests += 1

                    logger.info(
                        "Requesting candles: %s %s | count=%s | attempt=%s",
                        instrument,
                        timeframe,
                        count,
                        attempt,
                    )

                    response = await (
                        self.connector.connection
                        .get_historical_candles(
                            instrument=instrument,
                            timeframe=timeframe,
                            count=count,
                            price_type=price_type,
                        )
                    )

                    if isinstance(
                        response,
                        dict,
                    ):

                        candles = response.get(
                            "candles",
                            [],
                        )

                    else:

                        candles = response

                    candles = (
                        self._normalize_candles(
                            candles
                        )
                    )

                    if not candles:

                        raise ValueError(
                            "Exness returned no candles."
                        )

                    candles = candles[-count:]

                    self._store_cache(
                        instrument,
                        timeframe,
                        candles,
                    )

                    self.successful_requests += 1

                    self.last_error = None

                    self.pair_status[
                        f"{instrument}_{timeframe}"
                    ] = {
                        "success": True,
                        "candles": len(candles),
                        "last_update": (
                            datetime.now(
                                timezone.utc
                            ).isoformat()
                        ),
                    }

                    logger.info(
                        "Candles received: %s %s | %s",
                        instrument,
                        timeframe,
                        len(candles),
                    )

                    return candles

                except Exception as exc:

                    last_exception = exc

                    self.failed_requests += 1

                    self.last_error = str(exc)

                    if self._is_rate_limit_error(
                        exc
                    ):

                        self.rate_limit_hits += 1

                        self._rate_limit_until = (
                            time.monotonic()
                            + self.RATE_LIMIT_COOLDOWN
                        )

                        logger.warning(
                            "Exness rate limit detected. Cooling down."
                        )

                    logger.error(
                        "Candle request failed: %s %s | %s",
                        instrument,
                        timeframe,
                        exc,
                    )

                    if (
                        attempt
                        >= self.MAX_RETRIES + 1
                    ):
                        break

                    # Exponential backoff.
                    delay = (
                        self.INITIAL_RETRY_DELAY
                        * (2 ** (attempt - 1))
                    )

                    if self._is_rate_limit_error(
                        exc
                    ):

                        delay = max(
                            delay,
                            self.RATE_LIMIT_COOLDOWN,
                        )

                    logger.warning(
                        "Retrying in %s seconds.",
                        delay,
                    )

                    await asyncio.sleep(
                        delay
                    )

            self.pair_status[
                f"{instrument}_{timeframe}"
            ] = {
                "success": False,
                "error": str(
                    last_exception
                ),
            }

            raise last_exception

    # --------------------------------------------------
    # RECENT CANDLES
    # --------------------------------------------------

    async def get_recent_candles(
        self,
        instrument,
        timeframe,
        count=100,
    ):

        return await self.request_candles(
            instrument=instrument,
            timeframe=timeframe,
            count=count,
        )

    # --------------------------------------------------
    # PILOT VERIFICATION
    # --------------------------------------------------

    async def verify_required_market_data(
        self,
        count=100,
    ):

        logger.info(
            "Starting pilot market-data verification."
        )

        self.ready = False

        total_pairs = (
            len(self.PILOT_INSTRUMENTS)
            * len(self.REQUIRED_TIMEFRAMES)
        )

        successful_pairs = 0

        failed_pairs = []

        for instrument in (
            self.PILOT_INSTRUMENTS
        ):

            for timeframe in (
                self.REQUIRED_TIMEFRAMES
            ):

                try:

                    candles = await self.request_candles(
                        instrument=instrument,
                        timeframe=timeframe,
                        count=count,
                    )

                    if candles:

                        successful_pairs += 1

                    else:

                        failed_pairs.append(
                            f"{instrument}_{timeframe}"
                        )

                except Exception as exc:

                    failed_pairs.append(
                        f"{instrument}_{timeframe}"
                    )

                    logger.error(
                        "Verification failed: %s %s | %s",
                        instrument,
                        timeframe,
                        exc,
                    )

        self.ready = (
            successful_pairs
            == total_pairs
        )

        result = {
            "ready": self.ready,
            "successful_pairs": successful_pairs,
            "total_pairs": total_pairs,
            "failed_pairs": failed_pairs,
            "instruments": (
                self.PILOT_INSTRUMENTS
            ),
            "timeframes": (
                self.REQUIRED_TIMEFRAMES
            ),
        }

        logger.info(
            "Pilot verification complete: %s/%s | ready=%s",
            successful_pairs,
            total_pairs,
            self.ready,
        )

        return result

    # --------------------------------------------------
    # HISTORICAL COLLECTION
    # --------------------------------------------------

    async def retrieve_all_v1_history(
        self,
        target_candles=100,
        price_type="bid",
    ):

        logger.info(
            "Starting pilot historical collection."
        )

        results = {}

        for instrument in (
            self.PILOT_INSTRUMENTS
        ):

            results[instrument] = {}

            for timeframe in (
                self.REQUIRED_TIMEFRAMES
            ):

                try:

                    candles = await self.request_candles(
                        instrument=instrument,
                        timeframe=timeframe,
                        count=target_candles,
                        price_type=price_type,
                        force_refresh=True,
                    )

                    results[instrument][
                        timeframe
                    ] = {
                        "success": True,
                        "count": len(candles),
                    }

                except Exception as exc:

                    results[instrument][
                        timeframe
                    ] = {
                        "success": False,
                        "error": str(exc),
                    }

        logger.info(
            "Pilot historical collection completed."
        )

        return results

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_status(self):

        total_pairs = (
            len(self.PILOT_INSTRUMENTS)
            * len(self.REQUIRED_TIMEFRAMES)
        )

        successful_pairs = sum(
            1
            for pair in self.pair_status.values()
            if pair.get("success")
        )

        return {
            "connected": self.connected,
            "ready": self.ready,
            "instruments": (
                self.PILOT_INSTRUMENTS
            ),
            "timeframes": (
                self.REQUIRED_TIMEFRAMES
            ),
            "pairs_verified": (
                successful_pairs
            ),
            "total_pairs": (
                total_pairs
            ),
            "total_requests": (
                self.total_requests
            ),
            "successful_requests": (
                self.successful_requests
            ),
            "failed_requests": (
                self.failed_requests
            ),
            "rate_limit_hits": (
                self.rate_limit_hits
            ),
            "cached_pairs": (
                len(self._cache)
            ),
            "last_error": (
                self.last_error
            ),
        }


# ------------------------------------------------------
# GLOBAL ENGINE INSTANCE
# ------------------------------------------------------

market_data_engine = MarketDataEngine()
