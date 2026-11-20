from config import settings
from logging_config import get_logger

logger = get_logger("decision_engine")


REQUIRED_CATEGORIES = (
    "structure",
    "poi",
    "liquidity",
    "entry_model",
    "timeframe_alignment",
    "fundamentals",
    "trade_quality",
)


class DecisionEngine:

    def __init__(self, minimum_score=None):

        self.minimum_score = (
            minimum_score
            if minimum_score is not None
            else settings.MIN_SETUP_SCORE
        )

        self.minimum_score = max(85, self.minimum_score)

    def validate_evidence(self, evidence):

        if not isinstance(evidence, dict):
            return False, "Evidence must be a dictionary"

        missing = [
            category
            for category in REQUIRED_CATEGORIES
            if category not in evidence
        ]

        if missing:
            return False, f"Missing evidence: {', '.join(missing)}"

        return True, "Evidence structure valid"

    def calculate_score(self, evidence):

        valid, reason = self.validate_evidence(evidence)

        if not valid:
            return 0, reason

        total = 0.0

        for category in REQUIRED_CATEGORIES:

            value = evidence.get(category, 0)

            try:
                value = float(value)
            except (TypeError, ValueError):
                return 0, f"Invalid score for {category}"

            if value < 0 or value > 100:
                return 0, f"Score out of range: {category}"

            total += value

        final_score = total / len(REQUIRED_CATEGORIES)

        return round(final_score, 2), "Score calculated"

    def evaluate(self, setup):

        if not isinstance(setup, dict):
            return self.reject("Invalid setup data")

        symbol = setup.get("symbol")
        direction = setup.get("direction")

        if not symbol:
            return self.reject("Missing instrument")

        if direction not in ("BUY", "SELL"):
            return self.reject("Invalid direction")

        evidence = setup.get("evidence")

        score, reason = self.calculate_score(evidence)

        if score == 0:
            return self.reject(reason)

        if score < self.minimum_score:
            return self.reject(
                f"Score {score} below minimum {self.minimum_score}",
                score
            )

        if setup.get("h1_bias") != direction:
            return self.reject("H1 bias does not match trade direction", score)

        if not setup.get("m5_confirmed", False):
            return self.reject("M5 confirmation missing", score)

        if not setup.get("m1_entry_confirmed", False):
            return self.reject("M1 entry confirmation missing", score)

        if not setup.get("liquidity_confirmed", False):
            return self.reject("Liquidity confirmation missing", score)

        if not setup.get("poi_valid", False):
            return self.reject("POI is invalid", score)

        if not setup.get("spread_acceptable", False):
            return self.reject("Spread is unacceptable", score)

        if not setup.get("risk_approved", False):
            return self.reject("Risk approval missing", score)

        logger.info(
            "SETUP APPROVED | %s | %s | Score: %.2f",
            symbol,
            direction,
            score
        )

        return {
            "approved": True,
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "reason": "All decision requirements passed",
        }

    @staticmethod
    def reject(reason, score=0):

        logger.info("SETUP REJECTED: %s", reason)

        return {
            "approved": False,
            "score": score,
            "reason": reason,
        }


decision_engine = DecisionEngine()
