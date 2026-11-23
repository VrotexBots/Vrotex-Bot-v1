
from math import isfinite

from config import settings
from logging_config import get_logger

logger = get_logger("decision_engine")

CATEGORY_WEIGHTS = {
    "structure": 20,
    "poi": 15,
    "liquidity": 15,
    "entry_models": 20,
    "timeframe_alignment": 15,
    "fundamentals": 5,
    "trade_quality_risk": 10,
}

REQUIRED_RISK_CHECKS = (
    "spread_valid",
    "stop_loss_valid",
    "risk_within_limit",
    "daily_limit_valid",
    "consecutive_loss_limit_valid",
    "reward_risk_valid",
)


class DecisionEngine:

    VERSION = "2.1"
    MINIMUM_APPROVED_SCORE = 85.0

    def __init__(self, minimum_score=None):
        configured = (
            minimum_score
            if minimum_score is not None
            else settings.MIN_SETUP_SCORE
        )

        try:
            configured = float(configured)
        except (TypeError, ValueError):
            configured = self.MINIMUM_APPROVED_SCORE

        if not isfinite(configured):
            configured = self.MINIMUM_APPROVED_SCORE

        self.minimum_score = min(
            100.0,
            max(self.MINIMUM_APPROVED_SCORE, configured),
        )

        self.total_evaluations = 0
        self.approved_setups = 0
        self.rejected_setups = 0
        self.last_decision = None

    @staticmethod
    def _number(value):
        try:
            number = float(value)
            return number if isfinite(number) else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _direction(value):
        value = str(value or "").strip().upper()

        aliases = {
            "BULLISH": "BUY",
            "BULL": "BUY",
            "LONG": "BUY",
            "BUY": "BUY",
            "BEARISH": "SELL",
            "BEAR": "SELL",
            "SHORT": "SELL",
            "SELL": "SELL",
        }

        return aliases.get(value)

    def _extract_smc_data(self, setup):
        """
        Accept either the complete Master SMC result or its
        execution_payload. Does not calculate or manufacture
        an A+ score.
        """
        payload = setup.get("execution_payload")

        if not isinstance(payload, dict):
            payload = setup

        best = setup.get("best_setup")
        if not isinstance(best, dict):
            best = {}

        scoring = best.get("scoring")
        if not isinstance(scoring, dict):
            scoring = {}

        score = self._number(
            payload.get(
                "score",
                setup.get(
                    "score",
                    scoring.get("score"),
                ),
            )
        )

        symbol = (
            payload.get("symbol")
            or setup.get("symbol")
            or setup.get("instrument")
        )

        direction = (
            payload.get("direction")
            or setup.get("direction")
            or setup.get("trade_direction")
            or best.get("direction")
        )

        risk_checks = payload.get(
            "risk_checks",
            setup.get("risk_checks"),
        )

        if not isinstance(risk_checks, dict):
            risk_checks = {}

        smc_authorized = (
            setup.get("execution_authorized") is True
            or payload.get("authorized") is True
        )

        return {
            "symbol": (
                str(symbol).strip().upper()
                if symbol
                else None
            ),
            "direction": self._direction(direction),
            "score": score,
            "risk_checks": risk_checks,
            "smc_authorized": smc_authorized,
            "pathway": (
                payload.get("pathway")
                or setup.get("pathway")
                or best.get("pathway")
            ),
            "scoring_complete": (
                scoring.get("complete") is True
                if scoring
                else None
            ),
        }

    def validate_evidence(self, evidence):
        if not isinstance(evidence, dict):
            return False, "Evidence must be a dictionary"

        missing = [
            category
            for category in CATEGORY_WEIGHTS
            if category not in evidence
        ]

        if missing:
            return False, (
                "Missing evidence: " + ", ".join(missing)
            )

        for category in CATEGORY_WEIGHTS:
            value = evidence[category]

            if isinstance(value, bool):
                return False, f"Invalid score for {category}"

            number = self._number(value)

            if number is None or not 0 <= number <= 100:
                return False, f"Invalid score for {category}"

        return True, "Evidence structure valid"

    def calculate_score(self, evidence):
        valid, reason = self.validate_evidence(evidence)

        if not valid:
            return 0.0, reason

        total = sum(
            float(evidence[name]) * weight / 100.0
            for name, weight in CATEGORY_WEIGHTS.items()
        )

        return round(total, 2), "Weighted score calculated"

    def evaluate(self, setup):
        self.total_evaluations += 1

        if not isinstance(setup, dict):
            return self.reject("Invalid setup data")

        data = self._extract_smc_data(setup)

        if not data["smc_authorized"]:
            return self.reject(
                "Master SMC authorization missing"
            )

        if not data["symbol"]:
            return self.reject("Missing instrument")

        if data["direction"] not in ("BUY", "SELL"):
            return self.reject("Invalid SMC trade direction")

        if data["score"] is None:
            return self.reject("SMC A+ score missing")

        if data["score"] < self.minimum_score:
            return self.reject(
                f"Score {data['score']} below minimum "
                f"{self.minimum_score}",
                data["score"],
            )

        if data["scoring_complete"] is False:
            return self.reject(
                "Master SMC scoring is incomplete",
                data["score"],
            )

        failed = [
            name
            for name in REQUIRED_RISK_CHECKS
            if data["risk_checks"].get(name) is not True
        ]

        if failed:
            return self.reject(
                "Risk checks missing or failed: "
                + ", ".join(failed),
                data["score"],
            )

        result = {
            "approved": True,
            "symbol": data["symbol"],
            "direction": data["direction"],
            "pathway": data["pathway"],
            "score": data["score"],
            "minimum_score": self.minimum_score,
            "grade": "A_PLUS",
            "reason": "Master SMC and risk authorization verified",
            # This engine does not manufacture SMC authorization.
            "execution_authorized": False,
        }

        self.approved_setups += 1
        self.last_decision = result

        logger.info(
            "DECISION APPROVED | %s | %s | Score %.2f",
            data["symbol"],
            data["direction"],
            data["score"],
        )

        return result

    def reject(self, reason, score=0):
        self.rejected_setups += 1

        result = {
            "approved": False,
            "score": score,
            "reason": reason,
            "execution_authorized": False,
        }

        self.last_decision = result

        logger.warning("DECISION REJECTED | %s", reason)

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
