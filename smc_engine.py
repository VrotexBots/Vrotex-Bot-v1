
"""
VROTEX BOT V1
Master Smart Money Concepts Engine

Flow:
H1 external structure
    -> M5 external CHoCH confirmation
        -> M1 entry model
            -> Evidence validation
                -> A+ decision

Approved strategy:
- H1 = External narrative
- M5 = Confirmation
- M1 = Entry

A+ threshold: 85
A+ category weights:
- Structure: 20
- POI: 15
- Liquidity: 15
- Entry models: 20
- Timeframe alignment: 15
- Fundamentals: 5
- Trade quality and risk: 10

This engine evaluates evidence only.
It does not place orders or authorize execution.
"""

import math
from typing import Any, Dict, Optional

from smc_integration_adapter import SMCIntegrationAdapter


class SMCEngine:

    VERSION = "2.0"

    A_PLUS_THRESHOLD = 85

    CATEGORY_WEIGHTS = {
        "structure": 20,
        "poi": 15,
        "liquidity": 15,
        "entry_models": 20,
        "timeframe_alignment": 15,
        "fundamentals": 5,
        "trade_quality_risk": 10,
    }

    def __init__(
        self,
        adapter: Optional[SMCIntegrationAdapter] = None,
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
    def _list(value: Any) -> list:
        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            return [value]

        return []

    @staticmethod
    def _number(
        value: Any,
        default: Optional[float] = None,
    ) -> Optional[float]:

        try:
            result = float(value)

            if not math.isfinite(result):
                return default

            return result

        except (TypeError, ValueError):
            return default

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        return SMCIntegrationAdapter.direction(value)

    @staticmethod
    def _normalise_trade_direction(
        value: Any,
    ) -> Optional[str]:

        value = str(value or "").strip().upper()

        if value in ("BUY", "BULL", "BULLISH"):
            return "BUY"

        if value in ("SELL", "BEAR", "BEARISH"):
            return "SELL"

        return None

    # ---------------------------------------------------------
    # H1 DIRECTION
    # ---------------------------------------------------------

    def determine_h1_direction(
        self,
        h1_structure: Any,
    ) -> Optional[str]:

        data = self._dict(h1_structure)

        nested = self._dict(
            data.get("structure")
        )

        direction = (
            data.get("direction")
            or nested.get("direction")
            or nested.get("bias")
            or data.get("bias")
        )

        return self._normalise_trade_direction(
            direction
        )

    # ---------------------------------------------------------
    # M5 EXTERNAL CHOCH
    # ---------------------------------------------------------

    def validate_m5_external_choch(
        self,
        m5_structure: Any,
        trade_direction: str,
    ) -> Dict[str, Any]:

        data = self._dict(m5_structure)

        breaks = self._list(
            data.get("breaks")
        )

        matching_events = []

        expected_direction = (
            "BULLISH"
            if trade_direction == "BUY"
            else "BEARISH"
        )

        for item in breaks:

            event = self._dict(item)

            event_type = str(
                event.get("type", "")
            ).upper()

            event_direction = self._normalise_trade_direction(
                event.get("direction")
            )

            confirmation = str(
                event.get("confirmation", "")
            ).upper()

            body_close = (
                confirmation == "BODY_CLOSE"
                or event.get("body_close_confirmed") is True
            )

            if (
                event_type == "CHOCH"
                and event_direction == trade_direction
                and body_close
            ):
                matching_events.append(event)

        # Also support an explicitly supplied CHoCH object.
        explicit_choch = self._dict(
            data.get("choch")
        )

        if explicit_choch:

            explicit_direction = self._normalise_trade_direction(
                explicit_choch.get("direction")
            )

            explicit_confirmation = str(
                explicit_choch.get("confirmation", "")
            ).upper()

            explicit_body_close = (
                explicit_confirmation == "BODY_CLOSE"
                or explicit_choch.get(
                    "body_close_confirmed"
                ) is True
            )

            if (
                explicit_direction == trade_direction
                and explicit_body_close
                and explicit_choch.get("confirmed") is not False
            ):
                matching_events.append(explicit_choch)

        confirmed = bool(matching_events)

        return {
            "confirmed": confirmed,
            "required_event": "CHOCH",
            "required_confirmation": "BODY_CLOSE",
            "expected_direction": expected_direction,
            "matching_events": matching_events,
        }

    # ---------------------------------------------------------
    # A+ SCORE
    # ---------------------------------------------------------

    def calculate_a_plus_score(
        self,
        category_scores: Any,
    ) -> Dict[str, Any]:

        supplied = self._dict(category_scores)

        scores = {}
        weighted_total = 0.0
        missing_categories = []
        invalid_categories = []

        for category, weight in self.CATEGORY_WEIGHTS.items():

            if category not in supplied:
                missing_categories.append(category)
                score = 0.0

            else:
                score = self._number(
                    supplied[category]
                )

                if score is None:
                    invalid_categories.append(category)
                    score = 0.0

                elif not 0.0 <= score <= 100.0:
                    invalid_categories.append(category)
                    score = 0.0

            weighted_score = (
                score * weight / 100.0
            )

            scores[category] = {
                "score": round(score, 2),
                "weight": weight,
                "weighted_score": round(
                    weighted_score,
                    2,
                ),
            }

            weighted_total += weighted_score

        total = round(weighted_total, 2)

        complete = (
            not missing_categories
            and not invalid_categories
        )

        return {
            "score": total,
            "threshold": self.A_PLUS_THRESHOLD,
            "is_a_plus": (
                total >= self.A_PLUS_THRESHOLD
                and complete
            ),
            "category_scores": scores,
            "missing_categories": missing_categories,
            "invalid_categories": invalid_categories,
            "complete": complete,
        }

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
        fundamentals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        market_data = self._dict(market_data)
        entry_evidence = self._dict(entry_evidence)
        poi_evidence = self._dict(poi_evidence)
        displacement_evidence = self._dict(
            displacement_evidence
        )
        fvg_evidence = self._dict(fvg_evidence)
        risk_checks = self._dict(risk_checks)
        fundamentals = self._dict(fundamentals)

        price = self._number(current_price)

        if price is None or price <= 0:
            return self._reject(
                "INVALID_CURRENT_PRICE",
                current_price,
            )

        h1 = self._dict(
            market_data.get("H1")
        )

        m5 = self._dict(
            market_data.get("M5")
        )

        m1 = self._dict(
            market_data.get("M1")
        )

        # -----------------------------------------------------
        # 1. H1 EXTERNAL DIRECTION
        # -----------------------------------------------------

        direction = self.determine_h1_direction(h1)

        if direction is None:
            return self._reject(
                "H1_DIRECTION_NOT_CONFIRMED",
                price,
            )

        # -----------------------------------------------------
        # 2. M5 EXTERNAL CHOCH
        # -----------------------------------------------------

        m5_confirmation = self.validate_m5_external_choch(
            m5,
            direction,
        )

        if not m5_confirmation["confirmed"]:

            result = self._reject(
                "M5_EXTERNAL_CHOCH_NOT_CONFIRMED",
                price,
            )

            result["direction"] = direction
            result["m5_confirmation"] = m5_confirmation

            self.last_analysis = result
            return result

        # -----------------------------------------------------
        # 3. COLLECT MARKET EVIDENCE
        # -----------------------------------------------------

        liquidity = self._dict(
            market_data.get("liquidity")
        )

        structure_evidence = {
            "H1": h1,
            "M5": m5,
            "M1": m1,
        }

        # Preserve the existing adapter interface.
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
            risk_checks=risk_checks,
        )

        evidence = self._dict(evidence)

        # -----------------------------------------------------
        # 4. EVIDENCE VALIDATION
        # -----------------------------------------------------

        if evidence.get("valid") is not True:

            result = {
                "status": "REJECTED",
                "reason": "SMC_EVIDENCE_INCOMPLETE",
                "direction": direction,
                "current_price": price,
                "m5_confirmation": m5_confirmation,
                "evidence": evidence,
                "a_plus": None,
                "execution_authorized": False,
            }

            self.last_analysis = result
            return result

        # -----------------------------------------------------
        # 5. A+ SCORING
        # -----------------------------------------------------

        score_result = self.calculate_a_plus_score(
            category_scores or {}
        )

        if not score_result["is_a_plus"]:

            result = {
                "status": "REJECTED",
                "reason": "A_PLUS_THRESHOLD_NOT_MET",
                "direction": direction,
                "current_price": price,
                "m5_confirmation": m5_confirmation,
                "evidence": evidence,
                "a_plus": score_result,
                "execution_authorized": False,
            }

            self.last_analysis = result
            return result

        # -----------------------------------------------------
        # 6. A+ SETUP RESULT
        # -----------------------------------------------------

        result = {
            "status": "A_PLUS_SETUP",
            "reason": "ALL_REQUIRED_CHECKS_PASSED",
            "version": self.VERSION,
            "direction": direction,
            "current_price": price,
            "m5_confirmation": m5_confirmation,
            "evidence": evidence,
            "fundamentals": fundamentals,
            "a_plus": score_result,
            "execution_authorized": False,
        }

        self.last_analysis = result

        return result

    # ---------------------------------------------------------
    # REJECTION
    # ---------------------------------------------------------

    def _reject(
        self,
        reason: str,
        current_price: Any,
    ) -> Dict[str, Any]:

        result = {
            "status": "REJECTED",
            "reason": reason,
            "direction": None,
            "current_price": current_price,
            "evidence": None,
            "a_plus": None,
            "execution_authorized": False,
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
            "strategy_timeframes": [
                "H1",
                "M5",
                "M1",
            ],
            "a_plus_threshold": self.A_PLUS_THRESHOLD,
            "category_weights": dict(
                self.CATEGORY_WEIGHTS
            ),
            "execution_authorized": False,
            "last_status": self.last_analysis.get(
                "status",
                "NOT_ANALYSED",
            ),
        }

    def get_last_analysis(self) -> Dict[str, Any]:
        return dict(self.last_analysis)


smc_engine = SMCEngine()
