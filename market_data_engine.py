import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from config import settings
from logging_config import get_logger
from utils.validators import (
    validate_instrument,
    validate_timeframe,
)

from broker.exness_connector import exness_connector


logger = get_logger("market_data_engine")


class MarketDataEngine:

    MAX_CANDLES_PER_REQUEST = 1000

    def __init__(self):

        self.connector = exness_connector

        self._lock = asyncio.Lock()

        self.cache = {}

        self.last_update = {}
        self.errors = {}

        self.ready = False

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
        price_type
    ):

        symbol = symbol.upper().strip()
        timeframe = timeframe.upper().strip()

        if not validate_instrument(symbol):
            raise ValueError(
                f"Instrument not approved: {symbol}"
            )

        if not validate_timeframe(timeframe):
            raise ValueError(
                f"Timeframe not approved: {timeframe}"
            )

        if symbol not in settings.INSTRUMENTS:
            raise ValueError(
                f"Instrument not configured: {symbol}"
            )

        if timeframe not in settings.DATA_TIMEFRAMES:
            raise ValueError(
                f"Timeframe not configured: {timeframe}"
            )

        if not isinstance(count, int):
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

        if not self.connector.connected:

            result = await self.connector.connect()

            if not result.get("success"):
                raise ConnectionError(
                    "Exness connection unavailable"
                )

        connection = self.connector.connection

        if not connection.access_point:
            raise ConnectionError(
                "Exness Access Point not resolved"
            )

        # Negative count requests candles preceding
        # the supplied starting timestamp.
        start_time = self.utc_now()

        query = urlencode({
            "instrument": symbol,
            "timeframe": timeframe,
            "price_type": price_type,
            "from": self.format_time(start_time),
            "count": -count,
        })

        path = (
            f"/v1/market-data/accounts/"
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

        candles = response.get("candles", [])

        if not isinstance(candles, list):
            raise RuntimeError(
                "Invalid candle response format"
            )

        normalized = []

        for candle in candles:

            if not isinstance(candle, dict):
                continue

            if price_type == "both":

                bid = candle.get("bid")
                ask = candle.get("ask")

                if not bid or not ask:
                    continue

                normalized_candle = {
                    "time": candle.get("time"),
                    "bid": bid,
                    "ask": ask,
                    "volume": candle.get("volume", 0),
                    "symbol": symbol,
                    "timeframe": timeframe,
                }

            else:

                normalized_candle = {
                    "time": candle.get("time"),
                    "open": candle.get("open"),
                    "high": candle.get("high"),
                    "low": candle.get("low"),
                    "close": candle.get("close"),
                    "volume": candle.get("volume", 0),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "price_type": price_type,
                }

            normalized.append(normalized_candle)

        normalized.sort(
            key=lambda candle: candle["time"]
        )

        cache_key = (
            symbol,
            timeframe,
            price_type,
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

        return normalized

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
            "cached_pairs": len(self.cache),
            "last_updates": dict(self.last_update),
            "errors": dict(self.errors),
        }


market_data_engine = MarketDataEngine()
