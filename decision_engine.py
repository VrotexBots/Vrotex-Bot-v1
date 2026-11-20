
from math import isfinite

from config import settings
from logging_config import get_logger

logger = get_logger("decision_engine")


CATEGORY_WEIGHTS = {
    "structure": 20,
    "poi": 15,
    "liquidity": 15,
    "entry_model": 20,
    "timeframe_alignment": 15,
    "fundamentals": 5,
    "trade_quality": 10,
}

REQUIRED_CATEGORIES = tuple(CATEGORY_WEIGHTS.keys())


class DecisionEngine:

    VERSION = "2.0"
    MINIMUM_APPROVED_SCORE = 85.0

    def __init__(self, minimum_score=None):

        configured_score = (
            minimum_score
            if minimum_score is not None
            else settings.MIN_SETUP_SCORE
        )

        try:
            configured_score = float(configured_score)
        except (TypeError, ValueError):
            configured_score = self.MINIMUM_APPROVED_SCORE

        if not isfinite(configured_score):
            configured_score = self.MINIMUM_APPROVED_SCORE

        self.minimum_score = max(
            self.MINIMUM_APPROVED_SCORE,
            configured_score
        )

        if self.minimum_score > 100:
            self.minimum_score = 100.0

        self.total_evaluations = 0
        self.approved_setups = 0
        self.rejected_setups = 0
        self.last_decision = None

    def validate_evidence(self, evidence):

        if not isinstance(evidence, dict):
            return False, "Evidence must be a dictionary"

        missing = [
            category
            for category in REQUIRED_CATEGORIES
            if category not in evidence
        ]

        if missing:
            return False, (
                f"Missing evidence: {', '.join(missing)}"
            )

        for category in REQUIRED_CATEGORIES:

            value = evidence[category]

            if isinstance(value, bool):
                return False, f"Invalid score for {category}"

            try:
                value = float(value)
            except (TypeError, ValueError):
                return False, f"Invalid score for {category}"

            if not isfinite(value):
                return False, f"Non-finite score for {category}"

            if not 0 <= value <= 100:
                return False, f"Score out of range: {category}"

        return True, "Evidence structure valid"

    def calculate_score(self, evidence):

        valid, reason = self.validate_evidence(evidence)

        if not valid:
            return 0.0, reason

        total = 0.0

        weighted_breakdown = {}

        for category, weight in CATEGORY_WEIGHTS.items():

            value = float(evidence[category])

            contribution = value * weight / 100.0

            weighted_breakdown[category] = round(
                contribution, 2
            )

            total += contribution

        final_score = round(total, 2)

        return final_score, "Weighted score calculated"

    def evaluate(self, setup):

        self.total_evaluations += 1

        if not isinstance(setup, dict):
            return self.reject("Invalid setup data")

        symbol = setup.get("symbol")
        direction = setup.get("direction")

        if not isinstance(symbol, str) or not symbol.strip():
            return self.reject("Missing instrument")

        symbol = symbol.strip().upper()

        if direction not in ("BUY", "SELL"):
            return self.reject("Invalid direction")

        evidence = setup.get("evidence")

        score, reason = self.calculate_score(evidence)

        if reason != "Weighted score calculated":
            return self.reject(reason)

        if score < self.minimum_score:
            return self.reject(
                f"Score {score} below minimum "
                f"{self.minimum_score}",
                score
            )

        if setup.get("h1_bias") != direction:
            return self.reject(
                "H1 bias does not match trade direction",
                score
            )

        required_checks = {
            "m5_confirmed": "M5 confirmation missing",
            "m1_entry_confirmed": "M1 entry confirmation missing",
            "liquidity_confirmed": "Liquidity confirmation missing",
            "poi_valid": "POI is invalid",
            "spread_acceptable": "Spread is unacceptable",
            "risk_approved": "Risk approval missing",
        }

        for check, rejection_reason in required_checks.items():

            if setup.get(check) is not True:
                return self.reject(rejection_reason, score)

        logger.info(
            "SETUP APPROVED | %s | %s | Score: %.2f",
            symbol,
            direction,
            score
        )

        self.approved_setups += 1

        result = {
            "approved": True,
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "minimum_score": self.minimum_score,
            "grade": "A_PLUS",
            "reason": "All decision requirements passed",
            "execution_authorized": False,
        }

        self.last_decision = result

        return result

    def reject(self, reason, score=0):

        self.rejected_setups += 1

        logger.info("SETUP REJECTED: %s", reason)

        result = {
            "approved": False,
            "score": score,
            "reason": reason,
            "execution_authorized": False,
        }

        self.last_decision = result

        return result

    def get_status(self):

        return {
            "module": "DECISION_ENGINE",
            "version": self.VERSION,
            "minimum_score": self.minimum_score,
            "category_weights": dict(CATEGORY_WEIGHTS),
            "total_evaluations": self.total_evaluations,
            "approved_setups": self.approved_setups,
            "rejected_setups": self.rejected_setups,
            "execution_authorized": False,
        }


decision_engine = DecisionEngine()
