
import asyncio
import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from config import settings
from logging_config import get_logger

from exness_connector import exness_connector


logger = get_logger("market_data_engine")


class MarketDataEngine:

    MAX_CANDLES_PER_REQUEST = 1000

    PILOT_INSTRUMENTS = (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    )

    REQUIRED_STRATEGY_TIMEFRAMES = (
        "H1",
        "M5",
        "M1",
    )

    MIN_REQUEST_INTERVAL = 2.0

    MAX_RETRIES = 2

    RATE_LIMIT_COOLDOWN = 30

    CACHE_TTL = {
        "M1": 60,
        "M5": 300,
        "H1": 3600,
    }

    def __init__(self):

        self.connector = exness_connector

        self._lock = asyncio.Lock()

        self.cache = {}
        self.cache_time = {}
        self.cache_count = {}

        self.last_update = {}
        self.errors = {}

        self.last_request_time = 0.0
        self.rate_limit_until = 0.0

        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.rate_limit_hits = 0

        self.ready = False
        self.verified_pairs = []
        self.failed_pairs = []

    # --------------------------------------------------
    # TIME
    # --------------------------------------------------

    @staticmethod
    def utc_now():

        return datetime.now(timezone.utc)

    @staticmethod
    def format_time(dt):

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        ).isoformat()

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------

    def validate_request(
        self,
        symbol,
        timeframe,
        count,
        price_type,
    ):

        if not isinstance(symbol, str):
            raise ValueError(
                "Invalid instrument"
            )

        if not isinstance(timeframe, str):
            raise ValueError(
                "Invalid timeframe"
            )

        symbol = symbol.upper().strip()
        timeframe = timeframe.upper().strip()

        if symbol not in settings.INSTRUMENTS:
            raise ValueError(
                f"Instrument not configured: {symbol}"
            )

        if timeframe not in settings.DATA_TIMEFRAMES:
            raise ValueError(
                f"Timeframe not configured: {timeframe}"
            )

        if (
            isinstance(count, bool)
            or not isinstance(count, int)
        ):
            raise ValueError(
                "Candle count must be an integer"
            )

        if count < 1:
            raise ValueError(
                "Candle count must be positive"
            )

        if count > self.MAX_CANDLES_PER_REQUEST:
            raise ValueError(
                "Maximum 1000 candles per request"
            )

        if price_type not in (
            "bid",
            "ask",
            "both",
        ):
            raise ValueError(
                "Price type must be bid, ask, or both"
            )

        return symbol, timeframe

    # --------------------------------------------------
    # OHLC VALIDATION
    # --------------------------------------------------

    @staticmethod
    def valid_ohlc(data):

        if not isinstance(data, dict):
            return False

        required = (
            "open",
            "high",
            "low",
            "close",
        )

        values = {}

        for field in required:

            value = data.get(field)

            try:
                value = float(value)

            except (
                TypeError,
                ValueError,
            ):
                return False

            if not math.isfinite(value):
                return False

            values[field] = value

        if values["high"] < max(
            values["open"],
            values["close"],
            values["low"],
        ):
            return False

        if values["low"] > min(
            values["open"],
            values["close"],
            values["high"],
        ):
            return False

        return True

    # --------------------------------------------------
    # NORMALIZATION
    # --------------------------------------------------

    def normalize_candles(
        self,
        candles,
        symbol,
        timeframe,
        price_type,
    ):

        normalized = []

        for candle in candles:

            if not isinstance(candle, dict):
                continue

            candle_time = candle.get(
                "time"
            )

            if not candle_time:
                continue

            if price_type == "both":

                bid = candle.get("bid")
                ask = candle.get("ask")

                if not self.valid_ohlc(bid):
                    continue

                if not self.valid_ohlc(ask):
                    continue

                normalized_candle = {
                    "time": candle_time,
                    "bid": bid,
                    "ask": ask,
                    "volume": candle.get(
                        "volume",
                        0,
                    ),
                    "symbol": symbol,
                    "timeframe": timeframe,
                }

            else:

                if not self.valid_ohlc(candle):
                    continue

                normalized_candle = {
                    "time": candle_time,
                    "open": float(
                        candle["open"]
                    ),
                    "high": float(
                        candle["high"]
                    ),
                    "low": float(
                        candle["low"]
                    ),
                    "close": float(
                        candle["close"]
                    ),
                    "volume": candle.get(
                        "volume",
                        0,
                    ),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "price_type": price_type,
                }

            normalized.append(
                normalized_candle
            )

        normalized.sort(
            key=lambda item: str(
                item["time"]
            )
        )

        return normalized

    # --------------------------------------------------
    # CACHE
    # --------------------------------------------------

    def _cache_is_valid(
        self,
        cache_key,
        requested_count,
    ):

        if cache_key not in self.cache:
            return False

        cached_count = self.cache_count.get(
            cache_key,
            0,
        )

        if cached_count < requested_count:
            return False

        cached_at = self.cache_time.get(
            cache_key,
            0,
        )

        age = (
            time.monotonic()
            - cached_at
        )

        timeframe = cache_key[1]

        ttl = self.CACHE_TTL.get(
            timeframe,
            60,
        )

        if age > ttl:
            return False

        return True

    def _read_cache(
        self,
        cache_key,
        requested_count,
    ):

        if not self._cache_is_valid(
            cache_key,
            requested_count,
        ):
            return None

        candles = self.cache.get(
            cache_key,
            [],
        )

        return list(
            candles[-requested_count:]
        )

    def _write_cache(
        self,
        cache_key,
        candles,
    ):

        self.cache[cache_key] = list(
            candles
        )

        self.cache_count[cache_key] = (
            len(candles)
        )

        self.cache_time[cache_key] = (
            time.monotonic()
        )

        self.last_update[cache_key] = (
            self.utc_now().isoformat()
        )

    def get_cached_candles(
        self,
        symbol,
        timeframe,
        price_type="bid",
    ):

        cache_key = (
            symbol.upper(),
            timeframe.upper(),
            price_type,
        )

        return list(
            self.cache.get(
                cache_key,
                [],
            )
        )

    # --------------------------------------------------
    # RATE-LIMIT DETECTION
    # --------------------------------------------------

    @staticmethod
    def is_rate_limit_error(exc):

        message = str(exc).upper()

        indicators = (
            "429",
            "3015",
            "REQUEST_RATE_LIMIT",
            "TOO MANY REQUESTS",
            "RATE LIMIT",
        )

        return any(
            indicator in message
            for indicator in indicators
        )

    # --------------------------------------------------
    # REQUEST PACING
    # --------------------------------------------------

    async def wait_for_request_slot(self):

        now = time.monotonic()

        if now < self.rate_limit_until:

            cooldown = (
                self.rate_limit_until
                - now
            )

            logger.warning(
                "Exness cooldown active: %.1f seconds",
                cooldown,
            )

            await asyncio.sleep(
                cooldown
            )

        elapsed = (
            time.monotonic()
            - self.last_request_time
        )

        if elapsed < self.MIN_REQUEST_INTERVAL:

            wait_time = (
                self.MIN_REQUEST_INTERVAL
                - elapsed
            )

            await asyncio.sleep(
                wait_time
            )

        self.last_request_time = (
            time.monotonic()
        )

    # --------------------------------------------------
    # REQUEST CANDLES
    # --------------------------------------------------

    async def request_candles(
        self,
        symbol,
        timeframe,
        count=500,
        price_type="bid",
        force_refresh=False,
    ):

        symbol, timeframe = (
            self.validate_request(
                symbol,
                timeframe,
                count,
                price_type,
            )
        )

        cache_key = (
            symbol,
            timeframe,
            price_type,
        )

        # Cache check before acquiring request lock.
        if not force_refresh:

            cached = self._read_cache(
                cache_key,
                count,
            )

            if cached is not None:

                logger.debug(
                    "Cache hit | %s | %s | %s",
                    symbol,
                    timeframe,
                    len(cached),
                )

                return cached

        async with self._lock:

            # Check cache again after waiting.
            if not force_refresh:

                cached = self._read_cache(
                    cache_key,
                    count,
                )

                if cached is not None:
                    return cached

            if not (
                self.connector.connected
                and self.connector.connection.connected
            ):

                result = await (
                    self.connector.connect()
                )

                if not result.get("success"):

                    raise ConnectionError(
                        result.get(
                            "error",
                            "Exness connection unavailable",
                        )
                    )

            connection = (
                self.connector.connection
            )

            if not connection.connected:

                raise ConnectionError(
                    "Exness connection is not active"
                )

            if not connection.access_point:

                raise ConnectionError(
                    "Exness Access Point not resolved"
                )

            last_exception = None

            for attempt in range(
                1,
                self.MAX_RETRIES + 2,
            ):

                try:

                    await (
                        self.wait_for_request_slot()
                    )

                    self.total_requests += 1

                    start_time = self.utc_now()

                    query = urlencode({
                        "instrument": symbol,
                        "timeframe": timeframe,
                        "price_type": price_type,
                        "from": self.format_time(
                            start_time
                        ),
                        "count": -count,
                    })

                    path = (
                        "/v1/market-data/accounts/"
                        f"{connection.account_id}/candles"
                        f"?{query}"
                    )

                    logger.info(
                        "Requesting candles | "
                        "%s | %s | %s | %s | attempt %s",
                        symbol,
                        timeframe,
                        count,
                        price_type,
                        attempt,
                    )

                    response = await (
                        connection.signed_request(
                            connection.access_point,
                            "GET",
                            path,
                        )
                    )

                    if not isinstance(
                        response,
                        dict,
                    ):

                        raise RuntimeError(
                            "Invalid Exness response"
                        )

                    candles = response.get(
                        "candles"
                    )

                    if not isinstance(
                        candles,
                        list,
                    ):

                        raise RuntimeError(
                            "Invalid candle response format"
                        )

                    normalized = (
                        self.normalize_candles(
                            candles,
                            symbol,
                            timeframe,
                            price_type,
                        )
                    )

                    if not normalized:

                        raise RuntimeError(
                            "No valid candles received: "
                            f"{symbol} {timeframe}"
                        )

                    normalized = normalized[
                        -count:
                    ]

                    self._write_cache(
                        cache_key,
                        normalized,
                    )

                    self.errors.pop(
                        cache_key,
                        None,
                    )

                    self.successful_requests += 1

                    logger.info(
                        "Candles received | "
                        "%s | %s | %s",
                        symbol,
                        timeframe,
                        len(normalized),
                    )

                    return list(normalized)

                except Exception as exc:

                    last_exception = exc

                    self.failed_requests += 1

                    self.errors[cache_key] = (
                        str(exc)
                    )

                    logger.error(
                        "Market data request failed | "
                        "%s | %s | %s",
                        symbol,
                        timeframe,
                        exc,
                    )

                    rate_limited = (
                        self.is_rate_limit_error(
                            exc
                        )
                    )

                    if rate_limited:

                        self.rate_limit_hits += 1

                        self.rate_limit_until = (
                            time.monotonic()
                            + self.RATE_LIMIT_COOLDOWN
                        )

                        logger.warning(
                            "Exness rate limit detected. "
                            "Cooldown set to %s seconds.",
                            self.RATE_LIMIT_COOLDOWN,
                        )

                    if attempt >= (
                        self.MAX_RETRIES + 1
                    ):
                        break

                    if rate_limited:

                        delay = (
                            self.RATE_LIMIT_COOLDOWN
                            * attempt
                        )

                    else:

                        delay = (
                            5 * (2 ** (attempt - 1))
                        )

                    logger.warning(
                        "Retrying candle request in %s seconds.",
                        delay,
                    )

                    await asyncio.sleep(
                        delay
                    )

            raise last_exception

    # --------------------------------------------------
    # RECENT CANDLES
    # --------------------------------------------------

    async def get_recent_candles(
        self,
        symbol,
        timeframe,
        count=500,
        price_type="bid",
    ):

        return await self.request_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count,
            price_type=price_type,
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

        self.verified_pairs = []
        self.failed_pairs = []

        for symbol in (
            self.PILOT_INSTRUMENTS
        ):

            for timeframe in (
                self.REQUIRED_STRATEGY_TIMEFRAMES
            ):

                pair = (
                    f"{symbol}:{timeframe}"
                )

                try:

                    candles = await (
                        self.request_candles(
                            symbol=symbol,
                            timeframe=timeframe,
                            count=count,
                            price_type="bid",
                        )
                    )

                    if not candles:

                        raise RuntimeError(
                            "No valid candles available"
                        )

                    self.verified_pairs.append(
                        pair
                    )

                except Exception as exc:

                    self.failed_pairs.append({
                        "pair": pair,
                        "error": str(exc),
                    })

                    logger.error(
                        "Market data verification failed | %s",
                        pair,
                    )

        expected = (
            len(self.PILOT_INSTRUMENTS)
            * len(
                self.REQUIRED_STRATEGY_TIMEFRAMES
            )
        )

        self.ready = (
            len(self.verified_pairs)
            == expected
            and not self.failed_pairs
        )

        logger.info(
            "Pilot verification complete | "
            "Verified: %s/%s | Ready: %s",
            len(self.verified_pairs),
            expected,
            self.ready,
        )

        return {
            "ready": self.ready,
            "verified": len(
                self.verified_pairs
            ),
            "expected": expected,
            "verified_pairs": list(
                self.verified_pairs
            ),
            "failed_pairs": list(
                self.failed_pairs
            ),
        }

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

        for symbol in (
            self.PILOT_INSTRUMENTS
        ):

            results[symbol] = {}

            for timeframe in (
                self.REQUIRED_STRATEGY_TIMEFRAMES
            ):

                try:

                    candles = await (
                        self.request_candles(
                            symbol=symbol,
                            timeframe=timeframe,
                            count=target_candles,
                            price_type=price_type,
                            force_refresh=True,
                        )
                    )

                    results[symbol][
                        timeframe
                    ] = {
                        "success": True,
                        "count": len(candles),
                    }

                except Exception as exc:

                    results[symbol][
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

        expected_pairs = (
            len(self.PILOT_INSTRUMENTS)
            * len(
                self.REQUIRED_STRATEGY_TIMEFRAMES
            )
        )

        return {
            "ready": self.ready,
            "instruments": list(
                self.PILOT_INSTRUMENTS
            ),
            "timeframes": list(
                self.REQUIRED_STRATEGY_TIMEFRAMES
            ),
            "verified_pairs": len(
                self.verified_pairs
            ),
            "failed_pairs": len(
                self.failed_pairs
            ),
            "expected_pairs": expected_pairs,
            "cached_pairs": len(
                self.cache
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
            "last_updates": dict(
                self.last_update
            ),
            "errors": dict(
                self.errors
            ),
        }


market_data_engine = MarketDataEngine()
