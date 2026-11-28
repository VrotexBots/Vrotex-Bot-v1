"""Vrotex V1 currency conversion engine.

Converts an instrument's quote-currency P/L into the Exness account currency
using fresh bid/ask quotes from the configured broker market-data feed.
No public mid-market fallback, static rates, or guessed conversions are used.
"""
from __future__ import annotations

import inspect
import logging
import math
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("vrotex.currency_conversion")


class CurrencyConversionError(ValueError):
    pass


@dataclass(frozen=True)
class CurrencyConversion:
    from_currency: str
    to_currency: str
    rate: Decimal
    source_symbol: str
    source_side: str
    bid: Decimal
    ask: Decimal
    age_seconds: float
    timestamp: float

    def as_dict(self) -> dict:
        return {
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate": str(self.rate),
            "source_symbol": self.source_symbol,
            "source_side": self.source_side,
            "bid": str(self.bid),
            "ask": str(self.ask),
            "age_seconds": round(self.age_seconds, 3),
            "timestamp": self.timestamp,
            "verified_live_quote": True,
        }


class CurrencyConversionEngine:
    VERSION = "1.0"
    DEFAULT_MAX_AGE_SECONDS = 10.0

    def __init__(self, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS):
        self.max_age_seconds = float(max_age_seconds)
        if not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive and finite")
        self.last_conversion: Optional[CurrencyConversion] = None

    @staticmethod
    def _currency(value: Any) -> str:
        code = str(value or "").strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise CurrencyConversionError("Valid three-letter currency codes are required.")
        return code

    @staticmethod
    def _positive(value: Any, name: str) -> Decimal:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise CurrencyConversionError(f"Live conversion quote {name} is missing or invalid.")
        if not number.is_finite() or number <= 0:
            raise CurrencyConversionError(f"Live conversion quote {name} must be positive and finite.")
        return number

    @staticmethod
    def _timestamp_and_age(quote: dict, now: float) -> tuple[float, float]:
        age = quote.get("age_seconds", quote.get("age"))
        timestamp = quote.get("timestamp", quote.get("received_at"))
        if timestamp is not None:
            try:
                timestamp = float(timestamp)
            except (TypeError, ValueError):
                timestamp = None
        if timestamp is not None and math.isfinite(timestamp) and timestamp > 0:
            computed_age = now - timestamp
            if age is None:
                age = computed_age
            else:
                try:
                    age = min(float(age), computed_age) if computed_age >= 0 else computed_age
                except (TypeError, ValueError):
                    age = computed_age
        if age is None:
            raise CurrencyConversionError("Conversion quote has no verifiable timestamp or age.")
        try:
            age = float(age)
        except (TypeError, ValueError):
            raise CurrencyConversionError("Conversion quote age is invalid.")
        if not math.isfinite(age) or age < 0:
            raise CurrencyConversionError("Conversion quote age is invalid.")
        if timestamp is None:
            timestamp = now - age
        return timestamp, age

    @staticmethod
    async def _get_quote(provider: Callable, symbol: str):
        result = provider(symbol)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def get_conversion(
        self,
        from_currency: str,
        to_currency: str,
        *,
        quote_provider: Callable[[str], Any],
        now: Optional[float] = None,
    ) -> CurrencyConversion:
        source = self._currency(from_currency)
        target = self._currency(to_currency)
        current_time = time.time() if now is None else float(now)

        if source == target:
            result = CurrencyConversion(
                source, target, Decimal("1"), "IDENTITY", "IDENTITY",
                Decimal("1"), Decimal("1"), 0.0, current_time,
            )
            self.last_conversion = result
            return result
        if not callable(quote_provider):
            raise CurrencyConversionError("A live broker quote provider is unavailable.")

        direct_symbol = source + target
        inverse_symbol = target + source
        failures = []
        for symbol, inverse in ((direct_symbol, False), (inverse_symbol, True)):
            try:
                quote = await self._get_quote(quote_provider, symbol)
                if not isinstance(quote, dict):
                    raise CurrencyConversionError("No live quote returned.")
                bid = self._positive(quote.get("bid"), "bid")
                ask = self._positive(quote.get("ask"), "ask")
                if ask < bid:
                    raise CurrencyConversionError("Live quote ask is below bid.")
                timestamp, age = self._timestamp_and_age(quote, current_time)
                if age > self.max_age_seconds:
                    raise CurrencyConversionError(
                        f"Live quote is stale ({age:.2f}s; maximum {self.max_age_seconds:.2f}s)."
                    )
                reported_symbol = str(quote.get("symbol", quote.get("instrument", symbol))).upper().strip()
                if reported_symbol != symbol:
                    raise CurrencyConversionError("Live quote symbol does not match requested conversion pair.")

                # Conservative conversion: use the higher possible account-currency
                # loss multiplier. For a direct pair this is ask; for inverse it is 1/bid.
                if inverse:
                    rate = Decimal("1") / bid
                    side = "INVERSE_BID"
                else:
                    rate = ask
                    side = "DIRECT_ASK"
                if not rate.is_finite() or rate <= 0:
                    raise CurrencyConversionError("Calculated conversion rate is invalid.")
                result = CurrencyConversion(
                    source, target, rate, symbol, side, bid, ask, age, timestamp
                )
                self.last_conversion = result
                logger.info(
                    "CURRENCY_CONVERSION_OK | %s->%s | rate=%s | pair=%s | side=%s | age=%.3fs",
                    source, target, rate, symbol, side, age,
                )
                return result
            except Exception as exc:
                failures.append(f"{symbol}: {exc}")

        reason = " | ".join(failures)
        logger.error("CURRENCY_CONVERSION_BLOCKED | %s->%s | %s", source, target, reason)
        raise CurrencyConversionError(
            f"No fresh verified broker conversion quote for {source}->{target}. {reason}"
        )


currency_conversion_engine = CurrencyConversionEngine()
