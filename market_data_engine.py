import asyncio
import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from config import settings
from logging_config import get_logger
from exness_connector import exness_connector
from live_tick_engine import live_tick_engine


logger = get_logger("market_data_engine")


class MarketDataEngine:

    MAX_CANDLES_PER_REQUEST = min(
        1000,
        getattr(settings, "MAX_CANDLES_PER_REQUEST", 1000),
    )

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
        self.tick_engine = live_tick_engine

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
    # CONFIGURATION
    # --------------------------------------------------

    @staticmethod
    def get_candle_target(timeframe):

        targets = getattr(
            settings,
            "CANDLE_TARGETS",
            {},
        )

        target = targets.get(
            timeframe,
            1000,
        )

        try:
            target = int(target)
        except (TypeError, ValueError):
            target = 1000

        return max(
            1,
            min(target, 1000),
        )

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

        if symbol not in self.PILOT_INSTRUMENTS:
            raise ValueError(
                f"Instrument is not approved for V1: {symbol}"
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

        if not isinstance(price_type, str):
            raise ValueError(
                "Invalid price type"
            )

        price_type = price_type.lower().strip()

        if price_type not in (
            "bid",
            "ask",
            "both",
        ):
            raise ValueError(
                "Price type must be bid, ask, or both"
            )

        return symbol, timeframe, price_type

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

            if value <= 0:
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

            candle_time = candle.get("time")

            if candle_time is None:
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
                    "bid": {
                        "open": float(bid["open"]),
                        "high": float(bid["high"]),
                        "low": float(bid["low"]),
                        "close": float(bid["close"]),
                    },
                    "ask": {
                        "open": float(ask["open"]),
                        "high": float(ask["high"]),
                        "low": float(ask["low"]),
                        "close": float(ask["close"]),
                    },
                    "volume": candle.get(
                        "volume",
                        0,
                    ),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "price_type": "both",
                }

            else:

                if not self.valid_ohlc(candle):
                    continue

                normalized_candle = {
                    "time": candle_time,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
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
            key=lambda item: str(item["time"])
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

        return age <= ttl

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

        self.cache[cache_key] = list(candles)

        self.cache_count[cache_key] = len(
            candles
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
            price_type.lower(),
        )

        return list(
            self.cache.get(
                cache_key,
                [],
            )
        )

    # --------------------------------------------------
    # LIVE TICK ACCESS
    # --------------------------------------------------

    def get_live_tick(self, instrument):

        if not isinstance(instrument, str):
            return None

        symbol = instrument.upper().strip()

        if symbol not in self.PILOT_INSTRUMENTS:
            return None

        try:

            tick = self.tick_engine.get_tick(
                symbol
            )

            if not isinstance(tick, dict):
                return None

            bid = float(tick.get("bid"))
            ask = float(tick.get("ask"))

            if not (
                math.isfinite(bid)
                and math.isfinite(ask)
            ):
                return None

            if bid <= 0 or ask < bid:
                return None

            age = tick.get("age")

            if age is None:
                received_at = tick.get(
                    "received_at"
                )

                if received_at is None:
                    return None

                age = (
                    time.time()
                    - float(received_at)
                )

            age = float(age)

            max_age = float(
                getattr(
                    settings,
                    "LIVE_TICK_MAX_AGE_SECONDS",
                    10,
                )
            )

            if not math.isfinite(age):
                return None

            if age < 0 or age > max_age:
                return None

            result = dict(tick)

            result.update({
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "mid": (bid + ask) / 2,
                "spread": ask - bid,
                "age": age,
                "fresh": True,
            })

            return result

        except Exception as exc:

            logger.error(
                "Live tick access failed | %s | %s",
                symbol,
                exc,
            )

            return None

    def get_live_ticks(self):

        ticks = {}

        for symbol in self.PILOT_INSTRUMENTS:

            tick = self.get_live_tick(
                symbol
            )

            if tick is not None:
                ticks[symbol] = tick

        return ticks

    def get_live_tick_status(self):

        try:

            status = self.tick_engine.get_status()

            if isinstance(status, dict):
                return dict(status)

            return {
                "ready": False,
                "error": "Invalid tick engine status",
            }

        except Exception as exc:

            return {
                "ready": False,
                "error": str(exc),
            }

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
                self.rate_limit_until - now
            )

            logger.warning(
                "Exness cooldown active: %.1f seconds",
                cooldown,
            )

            await asyncio.sleep(cooldown)

        elapsed = (
            time.monotonic()
            - self.last_request_time
        )

        if elapsed < self.MIN_REQUEST_INTERVAL:

            wait_time = (
                self.MIN_REQUEST_INTERVAL
                - elapsed
            )

            await asyncio.sleep(wait_time)

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
        count=1000,
        price_type="bid",
        force_refresh=False,
    ):

        symbol, timeframe, price_type = (
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

                result = await self.connector.connect()

                if not result.get("success"):

                    raise ConnectionError(
                        result.get(
                            "error",
                            "Exness connection unavailable",
                        )
                    )

            connection = self.connector.connection

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

                    await self.wait_for_request_slot()

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

                    if not isinstance(response, dict):

                        raise RuntimeError(
                            "Invalid Exness response"
                        )

                    candles = response.get("candles")

                    if not isinstance(candles, list):

                        raise RuntimeError(
                            "Invalid candle response format"
                        )

                    normalized = self.normalize_candles(
                        candles,
                        symbol,
                        timeframe,
                        price_type,
                    )

                    if not normalized:

                        raise RuntimeError(
                            "No valid candles received: "
                            f"{symbol} {timeframe}"
                        )

                    normalized = normalized[-count:]

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
                        "%s | %s | %s/%s",
                        symbol,
                        timeframe,
                        len(normalized),
                        count,
                    )

                    return list(normalized)

                except Exception as exc:

                    last_exception = exc

                    self.failed_requests += 1

                    self.errors[cache_key] = str(exc)

                    logger.error(
                        "Market data request failed | "
                        "%s | %s | %s",
                        symbol,
                        timeframe,
                        exc,
                    )

                    rate_limited = (
                        self.is_rate_limit_error(exc)
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

                    if attempt >= self.MAX_RETRIES + 1:
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

                    await asyncio.sleep(delay)

            raise last_exception

    # --------------------------------------------------
    # RECENT CANDLES
    # --------------------------------------------------

    async def get_recent_candles(
        self,
        symbol,
        timeframe,
        count=1000,
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
        count=1000,
    ):

        logger.info(
            "Starting V1 market-data verification | "
            "Instruments: %s | Strategy timeframes: %s | "
            "Candles per pair: %s",
            len(self.PILOT_INSTRUMENTS),
            len(self.REQUIRED_STRATEGY_TIMEFRAMES),
            count,
        )

        self.ready = False
        self.verified_pairs = []
        self.failed_pairs = []

        expected = (
            len(self.PILOT_INSTRUMENTS)
            * len(self.REQUIRED_STRATEGY_TIMEFRAMES)
        )

        for symbol in self.PILOT_INSTRUMENTS:

            for timeframe in self.REQUIRED_STRATEGY_TIMEFRAMES:

                pair = f"{symbol}:{timeframe}"

                try:

                    candles = await self.request_candles(
                        symbol=symbol,
                        timeframe=timeframe,
                        count=count,
                        price_type="bid",
                    )

                    if len(candles) < count:

                        raise RuntimeError(
                            f"Insufficient candles: "
                            f"{len(candles)}/{count}"
                        )

                    self.verified_pairs.append(pair)

                    logger.info(
                        "Market data verified | %s | %s/%s candles",
                        pair,
                        len(candles),
                        count,
                    )

                except Exception as exc:

                    self.failed_pairs.append({
                        "pair": pair,
                        "error": str(exc),
                    })

                    logger.error(
                        "Market data verification failed | "
                        "%s | %s",
                        pair,
                        exc,
                    )

        self.ready = (
            len(self.verified_pairs) == expected
            and not self.failed_pairs
        )

        logger.info(
            "V1 market-data verification complete | "
            "Verified: %s/%s | Failed: %s | Ready: %s",
            len(self.verified_pairs),
            expected,
            len(self.failed_pairs),
            self.ready,
        )

        return {
            "ready": self.ready,
            "verified": len(self.verified_pairs),
            "expected": expected,
            "verified_pairs": list(self.verified_pairs),
            "failed_pairs": list(self.failed_pairs),
            "candles_requested_per_pair": count,
        }

    # --------------------------------------------------
    # HISTORICAL COLLECTION
    # --------------------------------------------------

    async def retrieve_all_v1_history(
        self,
        target_candles=1000,
        price_type="bid",
    ):

        logger.info(
            "Starting V1 historical collection | "
            "Expected strategy pairs: 9 | "
            "Candles per pair: %s",
            target_candles,
        )

        results = {}

        for symbol in self.PILOT_INSTRUMENTS:

            results[symbol] = {}

            for timeframe in self.REQUIRED_STRATEGY_TIMEFRAMES:

                try:

                    candles = await self.request_candles(
                        symbol=symbol,
                        timeframe=timeframe,
                        count=target_candles,
                        price_type=price_type,
                        force_refresh=True,
                    )

                    success = (
                        len(candles) >= target_candles
                    )

                    results[symbol][timeframe] = {
                        "success": success,
                        "count": len(candles),
                        "target": target_candles,
                    }

                    if not success:

                        logger.error(
                            "Historical collection incomplete | "
                            "%s:%s | Received %s/%s",
                            symbol,
                            timeframe,
                            len(candles),
                            target_candles,
                        )

                except Exception as exc:

                    results[symbol][timeframe] = {
                        "success": False,
                        "error": str(exc),
                    }

                    logger.error(
                        "Historical collection failed | "
                        "%s:%s | %s",
                        symbol,
                        timeframe,
                        exc,
                    )

        successful_pairs = sum(
            1
            for symbol_data in results.values()
            for timeframe_data in symbol_data.values()
            if timeframe_data.get("success")
        )

        logger.info(
            "V1 historical collection completed | "
            "Successful pairs: %s/9",
            successful_pairs,
        )

        return results

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_status(self):

        expected_pairs = (
            len(self.PILOT_INSTRUMENTS)
            * len(self.REQUIRED_STRATEGY_TIMEFRAMES)
        )

        live_ticks = self.get_live_ticks()

        return {
            "ready": self.ready,
            "instruments": list(self.PILOT_INSTRUMENTS),
            "timeframes": list(
                self.REQUIRED_STRATEGY_TIMEFRAMES
            ),
            "verified_pairs": len(self.verified_pairs),
            "failed_pairs": len(self.failed_pairs),
            "expected_pairs": expected_pairs,
            "verified_pair_names": list(
                self.verified_pairs
            ),
            "failed_pair_details": list(
                self.failed_pairs
            ),
            "cached_pairs": len(self.cache),
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "rate_limit_hits": self.rate_limit_hits,
            "last_updates": dict(self.last_update),
            "errors": {
                str(key): value
                for key, value in self.errors.items()
            },
            "live_ticks": {
                symbol: {
                    "bid": tick["bid"],
                    "ask": tick["ask"],
                    "mid": tick["mid"],
                    "spread": tick["spread"],
                    "timestamp": tick.get("timestamp"),
                    "age": tick["age"],
                    "fresh": tick["fresh"],
                }
                for symbol, tick in live_ticks.items()
            },
            "live_tick_count": len(live_ticks),
            "live_tick_status": self.get_live_tick_status(),
        }


market_data_engine = MarketDataEngine()
