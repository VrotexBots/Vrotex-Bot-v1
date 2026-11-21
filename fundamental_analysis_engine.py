from datetime import datetime, timezone, timedelta
from logging_config import get_logger

logger = get_logger("fundamental_analysis_engine")


class FundamentalAnalysisEngine:

    def __init__(
        self,
        high_impact_minutes_before=30,
        high_impact_minutes_after=30,
    ):

        self.currency_data = {}
        self.crypto_data = {}
        self.events = []
        self.last_update = None

        self.high_impact_minutes_before = (
            max(0, int(high_impact_minutes_before))
        )

        self.high_impact_minutes_after = (
            max(0, int(high_impact_minutes_after))
        )

        self.supported_currencies = {
            "EUR", "GBP", "USD", "JPY"
        }

        self.supported_symbols = {
            "EURUSD",
            "GBPUSD",
            "BTCUSD",
        }

        self.currency_factor_weights = {
            "interest_rate": 0.25,
            "inflation": 0.20,
            "employment": 0.20,
            "growth": 0.20,
            "central_bank": 0.15,
        }

        self.crypto_factor_weights = {
            "institutional_flow": 0.25,
            "network_activity": 0.20,
            "market_demand": 0.20,
            "regulatory": 0.20,
            "macro_environment": 0.15,
        }

    # ==================================================
    # TIME UTILITIES
    # ==================================================

    @staticmethod
    def current_time():

        return datetime.now(timezone.utc)

    @staticmethod
    def parse_datetime(value):

        if isinstance(value, datetime):

            if value.tzinfo is None:
                return value.replace(
                    tzinfo=timezone.utc
                )

            return value.astimezone(
                timezone.utc
            )

        if not value:
            return None

        try:

            value = str(value).strip()

            if value.endswith("Z"):
                value = value[:-1] + "+00:00"

            parsed = datetime.fromisoformat(value)

            if parsed.tzinfo is None:

                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed.astimezone(
                timezone.utc
            )

        except (
            ValueError,
            TypeError,
            OverflowError,
        ):

            return None

    # ==================================================
    # DATA VALIDATION
    # ==================================================

    @staticmethod
    def normalize_score(value):

        if isinstance(value, dict):

            value = value.get("score")

        try:

            value = float(value)

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):

            return 0.0

        if value != value:
            return 0.0

        return max(
            -100.0,
            min(100.0, value),
        )

    @staticmethod
    def normalize_bias(score):

        if score >= 25:
            return "BULLISH"

        if score <= -25:
            return "BEARISH"

        return "NEUTRAL"

    @staticmethod
    def normalize_currency(currency):

        if not isinstance(currency, str):
            raise ValueError(
                "Currency must be a string"
            )

        return currency.strip().upper()

    @staticmethod
    def normalize_factor_data(data):

        normalized = {}

        for factor, value in data.items():

            if isinstance(value, dict):

                normalized[factor] = dict(value)

                if "score" in value:

                    normalized[factor]["score"] = (
                        FundamentalAnalysisEngine
                        .normalize_score(
                            value["score"]
                        )
                    )

            else:

                normalized[factor] = (
                    FundamentalAnalysisEngine
                    .normalize_score(value)
                )

        return normalized

    # ==================================================
    # CURRENCY DATA
    # ==================================================

    def update_currency_data(
        self,
        currency,
        data,
    ):

        currency = self.normalize_currency(
            currency
        )

        if currency not in self.supported_currencies:

            raise ValueError(
                f"Unsupported currency: {currency}"
            )

        if not isinstance(data, dict):

            raise ValueError(
                "Currency data must be a dictionary"
            )

        normalized = (
            self.normalize_factor_data(data)
        )

        self.currency_data[currency] = normalized

        self.last_update = (
            self.current_time().isoformat()
        )

        logger.info(
            "Fundamental data updated for %s",
            currency,
        )

    # ==================================================
    # CRYPTO DATA
    # ==================================================

    def update_crypto_data(
        self,
        symbol,
        data,
    ):

        symbol = str(symbol).strip().upper()

        if symbol != "BTC":

            raise ValueError(
                "Only BTC crypto data is supported"
            )

        if not isinstance(data, dict):

            raise ValueError(
                "Crypto data must be a dictionary"
            )

        normalized = (
            self.normalize_factor_data(data)
        )

        self.crypto_data[symbol] = normalized

        self.last_update = (
            self.current_time().isoformat()
        )

        logger.info(
            "Crypto fundamental data updated for %s",
            symbol,
        )

    # ==================================================
    # ECONOMIC CALENDAR
    # ==================================================

    def update_events(self, events):

        if not isinstance(events, list):

            raise ValueError(
                "Events must be a list"
            )

        normalized_events = []

        for event in events:

            if not isinstance(event, dict):
                continue

            item = dict(event)

            item["currency"] = (
                str(
                    item.get("currency", "")
                ).strip().upper()
            )

            item["impact"] = (
                str(
                    item.get("impact", "LOW")
                ).strip().upper()
            )

            if item["impact"] not in {
                "LOW",
                "MEDIUM",
                "HIGH",
            }:

                item["impact"] = "LOW"

            event_time = self.parse_datetime(
                item.get("time")
                or item.get("datetime")
                or item.get("timestamp")
            )

            if event_time:

                item["time_utc"] = (
                    event_time.isoformat()
                )

            else:

                item["time_utc"] = None

            normalized_events.append(item)

        self.events = normalized_events

        self.last_update = (
            self.current_time().isoformat()
        )

        logger.info(
            "Economic calendar updated: %s events",
            len(self.events),
        )

    # ==================================================
    # CURRENCY ANALYSIS
    # ==================================================

    def analyze_currency(self, currency):

        currency = self.normalize_currency(
            currency
        )

        if currency not in self.supported_currencies:

            return {
                "currency": currency,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": "Unsupported currency",
            }

        data = self.currency_data.get(
            currency
        )

        if data is None:

            return {
                "currency": currency,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "Fundamental data unavailable"
                ),
            }

        weighted_score = 0.0
        available_weight = 0.0
        available_factors = []

        factors = self.currency_factor_weights

        for factor, weight in factors.items():

            if factor not in data:
                continue

            raw_value = data[factor]

            if (
                isinstance(raw_value, dict)
                and "score" not in raw_value
            ):
                continue

            score = self.normalize_score(
                raw_value
            )

            weighted_score += (
                score * weight
            )

            available_weight += weight

            available_factors.append(
                factor
            )

        if available_weight == 0:

            return {
                "currency": currency,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "No scored fundamental factors"
                ),
            }

        score = (
            weighted_score
            / available_weight
        )

        bias = self.normalize_bias(
            score
        )

        confidence = min(
            100,
            round(
                available_weight * 100
            ),
        )

        return {
            "currency": currency,
            "bias": bias,
            "score": round(score, 2),
            "confidence": confidence,
            "factors": data,
            "available_factors": (
                available_factors
            ),
            "reason": (
                "Weighted fundamental assessment"
            ),
        }

    # ==================================================
    # CRYPTO ANALYSIS
    # ==================================================

    def analyze_crypto(self, symbol="BTC"):

        symbol = str(symbol).strip().upper()

        data = self.crypto_data.get(
            symbol
        )

        if data is None:

            return {
                "symbol": symbol,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "Crypto fundamental data unavailable"
                ),
            }

        weighted_score = 0.0
        available_weight = 0.0
        available_factors = []

        for factor, weight in (
            self.crypto_factor_weights.items()
        ):

            if factor not in data:
                continue

            raw_value = data[factor]

            if (
                isinstance(raw_value, dict)
                and "score" not in raw_value
            ):
                continue

            score = self.normalize_score(
                raw_value
            )

            weighted_score += (
                score * weight
            )

            available_weight += weight

            available_factors.append(
                factor
            )

        if available_weight == 0:

            return {
                "symbol": symbol,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "No scored crypto factors"
                ),
            }

        score = (
            weighted_score
            / available_weight
        )

        return {
            "symbol": symbol,
            "bias": self.normalize_bias(
                score
            ),
            "score": round(score, 2),
            "confidence": min(
                100,
                round(
                    available_weight * 100
                ),
            ),
            "factors": data,
            "available_factors": (
                available_factors
            ),
            "reason": (
                "Weighted crypto fundamental assessment"
            ),
        }

    # ==================================================
    # PAIR ANALYSIS
    # ==================================================

    def analyze_pair(self, symbol):

        symbol = str(symbol).strip().upper()

        if symbol not in self.supported_symbols:

            return {
                "symbol": symbol,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "Symbol is outside approved V1 instruments"
                ),
            }

        if symbol == "BTCUSD":

            btc_analysis = (
                self.analyze_crypto("BTC")
            )

            usd_analysis = (
                self.analyze_currency("USD")
            )

            if (
                btc_analysis["bias"] == "UNKNOWN"
                or usd_analysis["bias"] == "UNKNOWN"
            ):

                return {
                    "symbol": symbol,
                    "base": btc_analysis,
                    "quote": usd_analysis,
                    "bias": "UNKNOWN",
                    "score": 0,
                    "confidence": 0,
                    "reason": (
                        "Insufficient BTC or USD fundamental data"
                    ),
                }

            score = (
                btc_analysis["score"]
                - usd_analysis["score"]
            ) / 2

            confidence = min(
                btc_analysis["confidence"],
                usd_analysis["confidence"],
            )

            return {
                "symbol": symbol,
                "base": btc_analysis,
                "quote": usd_analysis,
                "bias": self.normalize_bias(
                    score
                ),
                "score": round(score, 2),
                "confidence": confidence,
                "reason": (
                    "Relative BTC and USD fundamental strength"
                ),
            }

        base = symbol[:3]
        quote = symbol[3:]

        base_analysis = (
            self.analyze_currency(base)
        )

        quote_analysis = (
            self.analyze_currency(quote)
        )

        if (
            base_analysis["bias"] == "UNKNOWN"
            or quote_analysis["bias"] == "UNKNOWN"
        ):

            return {
                "symbol": symbol,
                "base": base_analysis,
                "quote": quote_analysis,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "Insufficient currency data"
                ),
            }

        score = (
            base_analysis["score"]
            - quote_analysis["score"]
        ) / 2

        confidence = min(
            base_analysis["confidence"],
            quote_analysis["confidence"],
        )

        return {
            "symbol": symbol,
            "base": base_analysis,
            "quote": quote_analysis,
            "bias": self.normalize_bias(
                score
            ),
            "score": round(score, 2),
            "confidence": confidence,
            "reason": (
                "Relative currency strength"
            ),
        }

    # ==================================================
    # EVENT FILTERING
    # ==================================================

    def get_upcoming_events(
        self,
        currency=None,
        minimum_impact="HIGH",
    ):

        impact_levels = {
            "LOW": 1,
            "MEDIUM": 2,
            "HIGH": 3,
        }

        minimum_impact = str(
            minimum_impact
        ).upper()

        minimum_level = impact_levels.get(
            minimum_impact,
            3,
        )

        currency = (
            currency.upper()
            if currency
            else None
        )

        now = self.current_time()

        results = []

        for event in self.events:

            event_currency = (
                event.get("currency", "")
                .upper()
            )

            impact = (
                event.get("impact", "LOW")
                .upper()
            )

            if currency and (
                event_currency != currency
            ):
                continue

            if (
                impact_levels.get(impact, 0)
                < minimum_level
            ):
                continue

            event_time = self.parse_datetime(
                event.get("time_utc")
                or event.get("time")
                or event.get("datetime")
                or event.get("timestamp")
            )

            if event_time is not None:

                if event_time < now:
                    continue

            results.append(
                dict(event)
            )

        results.sort(
            key=lambda event: (
                event.get("time_utc")
                or ""
            )
        )

        return results

    # ==================================================
    # EVENT RISK
    # ==================================================

    def get_event_risk(
        self,
        symbol,
    ):

        symbol = str(symbol).upper()

        if symbol == "BTCUSD":

            currencies = ["USD"]

        elif symbol in self.supported_symbols:

            currencies = [
                symbol[:3],
                symbol[3:],
            ]

        else:

            return {
                "symbol": symbol,
                "risk": "UNKNOWN",
                "events": [],
                "reason": (
                    "Unsupported instrument"
                ),
            }

        now = self.current_time()

        before = timedelta(
            minutes=(
                self.high_impact_minutes_before
            )
        )

        after = timedelta(
            minutes=(
                self.high_impact_minutes_after
            )
        )

        relevant_events = []

        highest_impact = "NONE"

        impact_rank = {
            "LOW": 1,
            "MEDIUM": 2,
            "HIGH": 3,
        }

        for event in self.events:

            currency = (
                event.get("currency", "")
                .upper()
            )

            impact = (
                event.get("impact", "LOW")
                .upper()
            )

            if currency not in currencies:
                continue

            event_time = self.parse_datetime(
                event.get("time_utc")
                or event.get("time")
                or event.get("datetime")
                or event.get("timestamp")
            )

            if event_time is None:
                continue

            window_start = (
                event_time - before
            )

            window_end = (
                event_time + after
            )

            if window_start <= now <= window_end:

                item = dict(event)

                item["minutes_until"] = round(
                    (
                        event_time - now
                    ).total_seconds()
                    / 60,
                    1,
                )

                relevant_events.append(
                    item
                )

                if (
                    impact_rank.get(impact, 0)
                    > impact_rank.get(
                        highest_impact,
                        0,
                    )
                ):

                    highest_impact = impact

        if any(
            event["impact"] == "HIGH"
            for event in relevant_events
        ):

            risk = "HIGH"

        elif any(
            event["impact"] == "MEDIUM"
            for event in relevant_events
        ):

            risk = "MEDIUM"

        elif relevant_events:

            risk = "LOW"

        else:

            risk = "NONE"

        return {
            "symbol": symbol,
            "risk": risk,
            "highest_impact": highest_impact,
            "events": relevant_events,
            "event_window_active": (
                bool(relevant_events)
            ),
            "reason": (
                "Economic event risk assessment"
            ),
        }

    # ==================================================
    # FULL FUNDAMENTAL EVIDENCE
    # ==================================================

    def analyze_instrument(
        self,
        symbol,
    ):

        symbol = str(symbol).upper()

        pair_analysis = (
            self.analyze_pair(symbol)
        )

        event_risk = (
            self.get_event_risk(symbol)
        )

        upcoming_events = []

        currencies = []

        if symbol == "BTCUSD":
            currencies = ["USD"]

        elif symbol in self.supported_symbols:
            currencies = [
                symbol[:3],
                symbol[3:],
            ]

        for currency in currencies:

            upcoming_events.extend(
                self.get_upcoming_events(
                    currency=currency,
                    minimum_impact="MEDIUM",
                )
            )

        # Avoid duplicate calendar events.

        unique_events = []
        seen = set()

        for event in upcoming_events:

            key = (
                event.get("currency"),
                event.get("name"),
                event.get("time_utc"),
            )

            if key in seen:
                continue

            seen.add(key)

            unique_events.append(
                event
            )

        return {
            "success": True,
            "symbol": symbol,
            "pair_analysis": pair_analysis,
            "bias": pair_analysis["bias"],
            "score": pair_analysis["score"],
            "confidence": pair_analysis["confidence"],
            "event_risk": event_risk,
            "upcoming_events": unique_events,
            "data_updated": self.last_update,
            "evidence_only": True,
            "trade_authorization": False,
        }

    # ==================================================
    # STATUS
    # ==================================================

    def get_status(self):

        return {
            "supported_currencies": sorted(
                self.supported_currencies
            ),
            "supported_symbols": sorted(
                self.supported_symbols
            ),
            "currencies_loaded": sorted(
                self.currency_data.keys()
            ),
            "crypto_data_loaded": sorted(
                self.crypto_data.keys()
            ),
            "events_loaded": len(
                self.events
            ),
            "last_update": self.last_update,
            "evidence_only": True,
        }


# ==================================================
# ENGINE INSTANCE
# ==================================================

fundamental_analysis_engine = (
    FundamentalAnalysisEngine()
)
