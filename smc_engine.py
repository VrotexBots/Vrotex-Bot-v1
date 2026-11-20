
"""
VROTEX BOT V1
Master Smart Money Concepts Engine

Flow:
H1 external structure
    -> M5 confirmation
        -> M1 entry
            -> Evidence validation
                -> A+ decision

This engine evaluates evidence only.
It does not place orders or authorize execution.
"""

from typing import Any, Dict, Optional

from smc_integration_adapter import SMCIntegrationAdapter


class SMCEngine:

    VERSION = "1.0"

    A_PLUS_THRESHOLD = 85

    CATEGORY_WEIGHTS = {
        "structure": 20,
        "poi": 15,
        "liquidity": 15,
        "entry_models": 20,
        "timeframe_alignment": 15,
        "fundamentals": 5,
        "trade_quality_risk": 10
    }

    def __init__(
        self,
        adapter: Optional[SMCIntegrationAdapter] = None
    ):
        self.adapter = adapter or SMCIntegrationAdapter()
        self.last_analysis: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        return SMCIntegrationAdapter.direction(value)

    # ---------------------------------------------------------
    # A+ SCORE
    # ---------------------------------------------------------

    def calculate_a_plus_score(
        self,
        category_scores: Any
    ) -> Dict[str, Any]:

        supplied = self._dict(category_scores)

        scores = {}
        weighted_total = 0.0
        missing_categories = []

        for category, weight in self.CATEGORY_WEIGHTS.items():

            if category not in supplied:
                score = 0.0
                missing_categories.append(category)
            else:
                score = self._number(supplied[category])

            score = max(0.0, min(100.0, score))

            scores[category] = {
                "score": score,
                "weight": weight,
                "weighted_score": score * weight / 100.0
            }

            weighted_total += score * weight / 100.0

        total = round(weighted_total, 2)

        return {
            "score": total,
            "threshold": self.A_PLUS_THRESHOLD,
            "is_a_plus": (
                total >= self.A_PLUS_THRESHOLD
                and not missing_categories
            ),
            "category_scores": scores,
            "missing_categories": missing_categories
        }

    # ---------------------------------------------------------
    # STRUCTURE DIRECTION
    # ---------------------------------------------------------

    def determine_h1_direction(
        self,
        h1_structure: Any
    ) -> Optional[str]:

        data = self._dict(h1_structure)
        nested = self._dict(data.get("structure"))

        direction = self._direction(
            data.get("direction", nested.get("direction"))
        )

        if direction not in {"BUY", "SELL"}:
            return None

        return direction

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyse(
        self,
        market_data: Dict[str, Any],
        current_price: float,
        entry_evidence: Dict[str, Any],
        poi_evidence: Dict[str, Any],
        displacement_evidence: Dict[str, Any],
        fvg_evidence: Dict[str, Any],
        risk_checks: Dict[str, Any],
        category_scores: Optional[Dict[str, Any]] = None,
        fundamentals: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        market_data = self._dict(market_data)
        entry_evidence = self._dict(entry_evidence)
        poi_evidence = self._dict(poi_evidence)
        displacement_evidence = self._dict(displacement_evidence)
        fvg_evidence = self._dict(fvg_evidence)
        risk_checks = self._dict(risk_checks)

        h1 = self._dict(market_data.get("H1"))
        m5 = self._dict(market_data.get("M5"))
        m1 = self._dict(market_data.get("M1"))

        # H1 determines the intended trade direction.
        direction = self.determine_h1_direction(h1)

        if direction is None:
            return self._reject(
                "H1_DIRECTION_NOT_CONFIRMED",
                current_price
            )

        # The lower timeframes must support the H1 direction.
        liquidity = self._dict(
            market_data.get("liquidity")
        )

        structure_evidence = {
            "H1": h1,
            "M5": m5,
            "M1": m1
        }

        evidence = self.adapter.build_evidence(
            trade_direction=direction,
            h1_structure=structure_evidence["H1"],
            m5_structure=structure_evidence["M5"],
            m1_structure=structure_evidence["M1"],
            liquidity=liquidity,
            fvg=fvg_evidence,
            poi=poi_evidence,
            displacement=displacement_evidence,
            entry_models=entry_evidence,
            risk_checks=risk_checks
        )

        # Evidence failure always rejects the setup.
        if not evidence.get("valid", False):
            result = {
                "status": "REJECTED",
                "reason": "SMC_EVIDENCE_INCOMPLETE",
                "direction": direction,
                "current_price": current_price,
                "evidence": evidence,
                "a_plus": None,
                "execution_authorized": False
            }

            self.last_analysis = result
            return result

        # Calculate the weighted A+ score.
        score_result = self.calculate_a_plus_score(
            category_scores or {}
        )

        if not score_result["is_a_plus"]:
            result = {
                "status": "REJECTED",
                "reason": "A_PLUS_THRESHOLD_NOT_MET",
                "direction": direction,
                "current_price": current_price,
                "evidence": evidence,
                "a_plus": score_result,
                "execution_authorized": False
            }

            self.last_analysis = result
            return result

        result = {
            "status": "A_PLUS_SETUP",
            "reason": "ALL_REQUIRED_CHECKS_PASSED",
            "direction": direction,
            "current_price": current_price,
            "evidence": evidence,
            "a_plus": score_result,
            "execution_authorized": False
        }

        self.last_analysis = result
        return result

    # ---------------------------------------------------------
    # REJECTION
    # ---------------------------------------------------------

    def _reject(
        self,
        reason: str,
        current_price: float
    ) -> Dict[str, Any]:

        result = {
            "status": "REJECTED",
            "reason": reason,
            "direction": None,
            "current_price": current_price,
            "evidence": None,
            "a_plus": None,
            "execution_authorized": False
        }

        self.last_analysis = result
        return result

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:

        return {
            "engine": "Vrotex SMC Engine",
            "version": self.VERSION,
            "strategy_timeframes": ["H1", "M5", "M1"],
            "a_plus_threshold": self.A_PLUS_THRESHOLD,
            "category_weights": dict(self.CATEGORY_WEIGHTS),
            "execution_authorized": False,
            "last_status": self.last_analysis.get(
                "status", "NOT_ANALYSED"
            )
        }

    def get_last_analysis(self) -> Dict[str, Any]:
        return dict(self.last_analysis)


smc_engine = SMCEngine()
