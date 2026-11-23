
from math import isfinite

from logging_config import get_logger

logger = get_logger("decision_engine")


class DecisionEngine:

    VERSION = "2.2"

    def __init__(self, minimum_score=None):
        # Kept as a compatibility argument only.
        # The Decision Engine no longer calculates or
        # independently enforces a scoring threshold.

        self.total_evaluations = 0
        self.approved_setups = 0
        self.rejected_setups = 0
        self.last_decision = None

    @staticmethod
    def _number(value):
        try:
            number = float(value)

            if not isfinite(number):
                return None

            return number

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

    # =====================================================
    # MASTER SMC OUTPUT EXTRACTION
    # =====================================================

    def _extract_smc_data(self, setup):

        if not isinstance(setup, dict):
            return None

        # Accept the scanner result containing smc_decision.
        smc = setup.get("smc_decision")

        if not isinstance(smc, dict):
            smc = setup

        payload = smc.get("execution_payload")

        if not isinstance(payload, dict):
            payload = {}

        best = smc.get("best_setup")

        if not isinstance(best, dict):
            best = {}

        # The Master SMC Engine is the authority.
        # Never derive authorization from a score.
        smc_authorized = (
            smc.get("execution_authorized") is True
        )

        score = self._number(
            smc.get(
                "score",
                smc.get("a_plus_score"),
            )
        )

        if score is None:
            score = self._number(
                payload.get("score")
            )

        symbol = (
            smc.get("symbol")
            or payload.get("symbol")
            or setup.get("symbol")
            or setup.get("instrument")
        )

        direction = (
            smc.get("direction")
            or payload.get("direction")
            or smc.get("trade_direction")
            or best.get("direction")
        )

        pathway = (
            smc.get("pathway")
            or payload.get("pathway")
            or best.get("pathway")
        )

        status = smc.get("status")

        return {
            "symbol": (
                str(symbol).strip().upper()
                if symbol
                else None
            ),
            "direction": self._direction(direction),
            "score": score,
            "pathway": pathway,
            "status": status,
            "smc_authorized": smc_authorized,
            "execution_payload": payload,
            "smc_result": smc,
        }

    # =====================================================
    # DECISION EVALUATION
    # =====================================================

    def evaluate(self, setup):

        self.total_evaluations += 1

        data = self._extract_smc_data(setup)

        if data is None:
            return self.reject(
                "Invalid Master SMC decision input"
            )

        # Gate 1: SMC must explicitly authorize execution.
        if data["smc_authorized"] is not True:
            return self.reject(
                "Master SMC execution authorization missing"
            )

        # Gate 2: SMC must report an approved A+ setup.
        if data["status"] != "A_PLUS_SETUP":
            return self.reject(
                "Master SMC did not return A_PLUS_SETUP",
                data["score"],
            )

        # Gate 3: Instrument must be present.
        if not data["symbol"]:
            return self.reject(
                "Master SMC instrument missing",
                data["score"],
            )

        # Gate 4: Direction must be valid.
        if data["direction"] not in ("BUY", "SELL"):
            return self.reject(
                "Master SMC direction missing or invalid",
                data["score"],
            )

        # The score is passed through unchanged.
        # No second scoring calculation.
        # No competing category weights.
        # No second minimum-score decision.
        # No duplicate risk-check validation.

        result = {
            "approved": True,
            "symbol": data["symbol"],
            "direction": data["direction"],
            "pathway": data["pathway"],
            "score": data["score"],
            "grade": "A_PLUS",
            "reason": (
                "Master SMC authorization accepted"
            ),

            # Preserve the actual SMC authorization.
            "execution_authorized": True,

            # Preserve the original SMC decision and payload.
            "smc_status": data["status"],
            "smc_execution_payload": data[
                "execution_payload"
            ],
            "smc_decision": data["smc_result"],
        }

        self.approved_setups += 1
        self.last_decision = result

        logger.info(
            "DECISION APPROVED | %s | %s | "
            "SMC Score=%s | SMC Authorization=True",
            data["symbol"],
            data["direction"],
            data["score"],
        )

        return result

    # =====================================================
    # REJECTION
    # =====================================================

    def reject(self, reason, score=None):

        self.rejected_setups += 1

        result = {
            "approved": False,
            "score": score,
            "reason": reason,
            "execution_authorized": False,
        }

        self.last_decision = result

        logger.warning(
            "DECISION REJECTED | %s",
            reason,
        )

        return result

    # =====================================================
    # STATUS
    # =====================================================

    def get_status(self):

        return {
            "module": "DECISION_ENGINE",
            "version": self.VERSION,

            "scoring_authority": "MASTER_SMC_ENGINE",
            "independent_scoring_enabled": False,
            "independent_score_threshold_enabled": False,
            "duplicate_risk_validation_enabled": False,

            "authorization_source": (
                "MASTER_SMC_ENGINE.execution_authorized"
            ),

            "total_evaluations": self.total_evaluations,
            "approved_setups": self.approved_setups,
            "rejected_setups": self.rejected_setups,

            "execution_authorized": (
                self.last_decision.get(
                    "execution_authorized",
                    False,
                )
                if isinstance(self.last_decision, dict)
                else False
            ),
        }


# =========================================================
# SINGLETON
# =========================================================

decision_engine = DecisionEngine()
