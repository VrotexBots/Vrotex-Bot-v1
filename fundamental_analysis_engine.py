from datetime import datetime, timezone
from logging_config import get_logger

logger = get_logger("fundamental_analysis_engine")


class FundamentalAnalysisEngine:

    def __init__(self):

        self.currency_data = {}
        self.events = []
        self.last_update = None

        self.supported_currencies = {
            "EUR", "GBP", "USD", "JPY"
        }

    def update_currency_data(
        self,
        currency,
        data,
    ):

        currency = currency.upper()

        if currency not in self.supported_currencies:
            raise ValueError(
                f"Unsupported currency: {currency}"
            )

        if not isinstance(data, dict):
            raise ValueError(
                "Currency data must be a dictionary"
            )

        self.currency_data[currency] = dict(data)

        self.last_update = datetime.now(
            timezone.utc
        ).isoformat()

        logger.info(
            "Fundamental data updated for %s",
            currency,
        )

    def update_events(self, events):

        if not isinstance(events, list):
            raise ValueError(
                "Events must be a list"
            )

        self.events = events

        self.last_update = datetime.now(
            timezone.utc
        ).isoformat()

        logger.info(
            "Economic calendar updated: %s events",
            len(events),
        )

    @staticmethod
    def normalize_score(value):

        try:
            value = float(value)

        except (TypeError, ValueError):
            return 0.0

        return max(-100.0, min(100.0, value))

    def analyze_currency(self, currency):

        currency = currency.upper()

        data = self.currency_data.get(currency)

        if data is None:

            return {
                "currency": currency,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": "Fundamental data unavailable",
            }

        factors = {
            "interest_rate": 0.25,
            "inflation": 0.20,
            "employment": 0.20,
            "growth": 0.20,
            "central_bank": 0.15,
        }

        weighted_score = 0
        available_weight = 0

        for factor, weight in factors.items():

            if factor not in data:
                continue

            score = self.normalize_score(
                data[factor]
            )

            weighted_score += score * weight
            available_weight += weight

        if available_weight == 0:

            return {
                "currency": currency,
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": "No scored fundamental factors",
            }

        score = weighted_score / available_weight

        if score >= 25:
            bias = "BULLISH"

        elif score <= -25:
            bias = "BEARISH"

        else:
            bias = "NEUTRAL"

        confidence = min(
            100,
            round(available_weight * 100)
        )

        return {
            "currency": currency,
            "bias": bias,
            "score": round(score, 2),
            "confidence": confidence,
            "factors": data,
            "reason": "Weighted fundamental assessment",
        }

    def analyze_pair(self, symbol):

        symbol = symbol.upper()

        if symbol == "BTCUSD":

            return {
                "symbol": symbol,
                "base": "BTC",
                "quote": "USD",
                "bias": "UNKNOWN",
                "score": 0,
                "confidence": 0,
                "reason": (
                    "BTC fundamental analysis requires "
                    "dedicated crypto data"
                ),
            }

        if len(symbol) != 6:
            raise ValueError(
                f"Invalid currency pair: {symbol}"
            )

        base = symbol[:3]
        quote = symbol[3:]

        base_analysis = self.analyze_currency(base)
        quote_analysis = self.analyze_currency(quote)

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
                "reason": "Insufficient currency data",
            }

        score = (
            base_analysis["score"]
            - quote_analysis["score"]
        ) / 2

        if score >= 25:
            bias = "BULLISH"

        elif score <= -25:
            bias = "BEARISH"

        else:
            bias = "NEUTRAL"

        confidence = min(
            base_analysis["confidence"],
            quote_analysis["confidence"],
        )

        return {
            "symbol": symbol,
            "base": base_analysis,
            "quote": quote_analysis,
            "bias": bias,
            "score": round(score, 2),
            "confidence": confidence,
            "reason": "Relative currency strength",
        }

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

        minimum_level = impact_levels.get(
            minimum_impact.upper(),
            3,
        )

        results = []

        for event in self.events:

            event_currency = event.get(
                "currency", ""
            ).upper()

            impact = event.get(
                "impact", "LOW"
            ).upper()

            if currency and (
                event_currency != currency.upper()
            ):
                continue

            if impact_levels.get(impact, 0) < minimum_level:
                continue

            results.append(dict(event))

        return results

    def get_status(self):

        return {
            "supported_currencies": sorted(
                self.supported_currencies
            ),
            "currencies_loaded": list(
                self.currency_data.keys()
            ),
            "events_loaded": len(self.events),
            "last_update": self.last_update,
        }


fundamental_analysis_engine = (
    FundamentalAnalysisEngine()
)
