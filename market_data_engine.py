
import asyncio
import math
from datetime import datetime, timezone
from urllib.parse import urlencode

from config import settings
from logging_config import get_logger

from broker.exness_connector import exness_connector


logger = get_logger("market_data_engine")


class MarketDataEngine:

    MAX_CANDLES_PER_REQUEST = 1000

    REQUIRED_STRATEGY_TIMEFRAMES = (
        "H1",
        "M5",
        "M1",
    )

    def __init__(self):

        self.connector = exness_connector

        self._lock = asyncio.Lock()

        self.cache = {}
        self.last_update = {}
        self.errors = {}

        self.ready = False
        self.verified_pairs = []
        self.failed_pairs = []

    @staticmethod
    def utc_now():

        return datetime.now(timezone.utc)

    @staticmethod
    def format_time(dt):

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc).isoformat()

    def validate_request(
        self,
        symbol,
        timeframe,
        count,
        price_type,
    ):

        if not isinstance(symbol, str):
            raise ValueError("Invalid instrument")

        if not isinstance(timeframe, str):
            raise ValueError("Invalid timeframe")

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

        if price_type not in ("bid", "ask", "both"):
            raise ValueError(
                "Price type must be bid, ask, or both"
            )

        return symbol, timeframe

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
            except (TypeError, ValueError):
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
                    "volume": candle.get("volume", 0),
                    "symbol": symbol,
                    "timeframe": timeframe,
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
                    "volume": candle.get("volume", 0),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "price_type": price_type,
                }

            normalized.append(normalized_candle)

        normalized.sort(
            key=lambda item: str(item["time"])
        )

        return normalized

    async def request_candles(
        self,
        symbol,
        timeframe,
        count=500,
        price_type="bid",
    ):

        symbol, timeframe = self.validate_request(
            symbol,
            timeframe,
            count,
            price_type,
        )

        cache_key = (
            symbol,
            timeframe,
            price_type,
        )

        try:

            async with self._lock:

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

                start_time = self.utc_now()

                query = urlencode({
                    "instrument": symbol,
                    "timeframe": timeframe,
                    "price_type": price_type,
                    "from": self.format_time(start_time),
                    "count": -count,
                })

                path = (
                    "/v1/market-data/accounts/"
                    f"{connection.account_id}/candles"
                    f"?{query}"
                )

                logger.info(
                    "Requesting candles | %s | %s | %s | %s",
                    symbol,
                    timeframe,
                    count,
                    price_type,
                )

                response = await connection.signed_request(
                    connection.access_point,
                    "GET",
                    path,
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
                        f"No valid candles received: "
                        f"{symbol} {timeframe}"
                    )

                self.cache[cache_key] = normalized

                self.last_update[cache_key] = (
                    self.utc_now().isoformat()
                )

                self.errors.pop(cache_key, None)

                logger.info(
                    "Candles received | %s | %s | %s",
                    symbol,
                    timeframe,
                    len(normalized),
                )

                return list(normalized)

        except Exception as exc:

            self.errors[cache_key] = str(exc)

            logger.exception(
                "Market data request failed | %s | %s",
                symbol,
                timeframe,
            )

            raise

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

    async def verify_required_market_data(
        self,
        count=100,
    ):

        logger.info(
            "Starting V1 strategy market-data verification."
        )

        self.ready = False
        self.verified_pairs = []
        self.failed_pairs = []

        for symbol in settings.INSTRUMENTS:

            for timeframe in self.REQUIRED_STRATEGY_TIMEFRAMES:

                pair = f"{symbol}:{timeframe}"

                try:

                    candles = await self.request_candles(
                        symbol=symbol,
                        timeframe=timeframe,
                        count=count,
                        price_type="bid",
                    )

                    if not candles:
                        raise RuntimeError(
                            "No valid candles available"
                        )

                    self.verified_pairs.append(pair)

                except Exception as exc:

                    self.failed_pairs.append({
                        "pair": pair,
                        "error": str(exc),
                    })

                    logger.error(
                        "Market data verification failed: %s",
                        pair,
                    )

        expected = (
            len(settings.INSTRUMENTS)
            * len(self.REQUIRED_STRATEGY_TIMEFRAMES)
        )

        self.ready = (
            len(self.verified_pairs) == expected
            and not self.failed_pairs
        )

        logger.info(
            "Market data verification complete | "
            "Verified: %s/%s | Ready: %s",
            len(self.verified_pairs),
            expected,
            self.ready,
        )

        return {
            "ready": self.ready,
            "verified": len(self.verified_pairs),
            "expected": expected,
            "verified_pairs": list(self.verified_pairs),
            "failed_pairs": list(self.failed_pairs),
        }

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
            self.cache.get(cache_key, [])
        )

    def get_status(self):

        return {
            "ready": self.ready,
            "verified_pairs": len(self.verified_pairs),
            "failed_pairs": len(self.failed_pairs),
            "expected_pairs": (
                len(settings.INSTRUMENTS)
                * len(self.REQUIRED_STRATEGY_TIMEFRAMES)
            ),
            "cached_pairs": len(self.cache),
            "last_updates": dict(self.last_update),
            "errors": dict(self.errors),
        }


market_data_engine = MarketDataEngine()
