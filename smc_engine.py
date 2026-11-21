
"""
Vrotex Bot V1
Master Smart Money Concepts Engine V3.0

Four independent setup pathways:
1. H1-aligned continuation
2. H1 countertrend reversal
3. M5 internal countertrend reversal
4. Ranging-market opportunities

A+ threshold: 85/100

This engine evaluates evidence and setup quality.
Execution authorization requires the complete setup and
risk validation. Order execution is handled downstream.

Existing public interfaces are preserved.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Dict, List, Optional


class SMCEngine:
    VERSION = "3.0"

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

    PATHWAYS = (
        "H1_ALIGNED_CONTINUATION",
        "H1_COUNTERTREND_REVERSAL",
        "M5_INTERNAL_COUNTERTREND",
        "RANGING_MARKET",
    )

    DIRECTIONS = ("BULLISH", "BEARISH")

    def __init__(self, adapter=None):
        self.adapter = adapter
        self.last_analysis: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # SAFE HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)

            if not math.isfinite(number):
                return None

            return number

        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        if value in ("RANGING", "RANGE", "NEUTRAL"):
            return "RANGING"

        return None

    @staticmethod
    def _normalise_trade_direction(
        value: Any,
    ) -> Optional[str]:
        return SMCEngine._direction(value)

    @staticmethod
    def _opposite(direction: str) -> str:
        return (
            "BEARISH"
            if direction == "BULLISH"
            else "BULLISH"
        )

    @staticmethod
    def _technical(data: Any) -> Dict[str, Any]:
        data = SMCEngine._dict(data)

        if isinstance(data.get("technical"), dict):
            return data["technical"]

        return data

    def _tf(
        self,
        market_data: Dict[str, Any],
        timeframe: str,
    ) -> Dict[str, Any]:

        return self._technical(
            market_data.get(timeframe)
        )

    @staticmethod
    def _price_inside_zone(
        price: Optional[float],
        zone: Dict[str, Any],
    ) -> bool:

        if price is None:
            return False

        lower = SMCEngine._number(
            zone.get("lower", zone.get("low"))
        )

        upper = SMCEngine._number(
            zone.get("upper", zone.get("high"))
        )

        if lower is None or upper is None:
            return False

        if lower > upper:
            return False

        return lower <= price <= upper

    @staticmethod
    def _confirmed_break(
        event: Dict[str, Any],
        direction: str,
    ) -> bool:

        event_direction = SMCEngine._direction(
            event.get("direction")
        )

        confirmed = (
            event.get("confirmed") is True
            or event.get("body_close_confirmed") is True
        )

        body_close = (
            event.get("confirmation") == "BODY_CLOSE"
            or event.get("body_close_confirmed") is True
        )

        return (
            event_direction == direction
            and confirmed
            and body_close
            and event.get("invalidated") is not True
        )

    def _find_break(
        self,
        technical: Dict[str, Any],
        direction: str,
    ) -> Optional[Dict[str, Any]]:

        for event in reversed(
            self._list(technical.get("breaks"))
        ):
            if not isinstance(event, dict):
                continue

            if self._confirmed_break(event, direction):
                return event

        return None

    # ---------------------------------------------------------
    # H1 DIRECTION
    # ---------------------------------------------------------

    def determine_h1_direction(
        self,
        data: Dict[str, Any],
    ) -> Optional[str]:

        data = self._technical(data)

        direction = self._direction(
            data.get("direction")
        )

        if direction in ("BULLISH", "BEARISH"):
            return direction

        structure = self._dict(
            data.get("structure")
        )

        direction = self._direction(
            structure.get("direction")
            or structure.get("bias")
        )

        if direction in ("BULLISH", "BEARISH"):
            return direction

        return self._direction(data.get("bias"))

    # ---------------------------------------------------------
    # M5 EXTERNAL CHoCH / BREAK VALIDATION
    # ---------------------------------------------------------

    def validate_m5_external_choch(
        self,
        data: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:

        data = self._technical(data)

        expected_direction = self._direction(
            expected_direction
        )

        if expected_direction not in self.DIRECTIONS:
            return {
                "valid": False,
                "reason": "INVALID_DIRECTION",
            }

        event = self._find_break(
            data,
            expected_direction,
        )

        if event is None:
            return {
                "valid": False,
                "reason": "BODY_CLOSE_EXTERNAL_BREAK_MISSING",
            }

        return {
            "valid": True,
            "direction": expected_direction,
            "event": deepcopy(event),
            "reason": "EXTERNAL_BREAK_CONFIRMED",
        }

    # ---------------------------------------------------------
    # CATEGORY SCORING
    # ---------------------------------------------------------

    def calculate_a_plus_score(
        self,
        category_scores: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        category_scores = self._dict(category_scores)

        total = 0.0
        details = {}
        complete = True

        for category, weight in self.CATEGORY_WEIGHTS.items():
            raw = self._number(
                category_scores.get(category)
            )

            if raw is None:
                complete = False
                raw = 0.0

            raw = max(0.0, min(100.0, raw))

            weighted = raw * weight / 100.0

            total += weighted

            details[category] = {
                "score": raw,
                "weight": weight,
                "weighted_score": round(weighted, 4),
            }

        total = round(total, 2)

        return {
            "score": total,
            "threshold": self.A_PLUS_THRESHOLD,
            "a_plus": total >= self.A_PLUS_THRESHOLD,
            "complete": complete,
            "categories": details,
        }

    # ---------------------------------------------------------
    # POI VALIDATION
    # ---------------------------------------------------------

    def _validate_poi(
        self,
        poi: Any,
        direction: str,
        current_price: Optional[float],
        require_tap: bool = True,
    ) -> Dict[str, Any]:

        if not isinstance(poi, dict):
            return {
                "valid": False,
                "reason": "POI_EVIDENCE_MISSING",
            }

        poi_direction = self._direction(
            poi.get("direction")
        )

        if poi_direction != direction:
            return {
                "valid": False,
                "reason": "POI_DIRECTION_MISMATCH",
            }

        if poi.get("clean") is not True:
            return {
                "valid": False,
                "reason": "POI_NOT_CLEAN",
            }

        if poi.get("unmitigated") is not True:
            return {
                "valid": False,
                "reason": "POI_ALREADY_MITIGATED",
            }

        if poi.get("invalidated") is True:
            return {
                "valid": False,
                "reason": "POI_INVALIDATED",
            }

        if not self._price_inside_zone(
            current_price,
            poi,
        ):
            return {
                "valid": False,
                "reason": (
                    "PRICE_NOT_TAPPED_POI"
                    if require_tap
                    else "POI_ZONE_INVALID"
                ),
            }

        return {
            "valid": True,
            "reason": "VALID_POI_TAP",
            "poi": deepcopy(poi),
        }

    # ---------------------------------------------------------
    # ENTRY VALIDATION
    # ---------------------------------------------------------

    def _validate_entry(
        self,
        entry_evidence: Any,
        direction: str,
    ) -> Dict[str, Any]:

        if not isinstance(entry_evidence, dict):
            return {
                "valid": False,
                "reason": "ENTRY_EVIDENCE_MISSING",
            }

        confirmed_models = (
            entry_evidence.get("confirmed_models")
        )

        models = self._dict(
            entry_evidence.get("models")
        )

        valid_models = []

        if isinstance(confirmed_models, list):
            for name in confirmed_models:
                model = self._dict(models.get(name))

                if (
                    model.get("confirmed") is True
                    and self._direction(
                        model.get("direction")
                    ) == direction
                ):
                    valid_models.append(name)

        if not valid_models:
            for name, model in models.items():
                model = self._dict(model)

                if (
                    model.get("confirmed") is True
                    and self._direction(
                        model.get("direction")
                    ) == direction
                ):
                    valid_models.append(name)

        if (
            entry_evidence.get("confirmed") is True
            and self._direction(
                entry_evidence.get("direction")
            ) == direction
        ):
            valid_models.append(
                entry_evidence.get("model", "ENTRY_CONFIRMED")
            )

        valid_models = list(dict.fromkeys(valid_models))

        if not valid_models:
            return {
                "valid": False,
                "reason": "NO_VALID_DIRECTIONAL_ENTRY_MODEL",
            }

        return {
            "valid": True,
            "models": valid_models,
            "reason": "ENTRY_MODEL_CONFIRMED",
        }

    # ---------------------------------------------------------
    # RISK VALIDATION
    # ---------------------------------------------------------

    @staticmethod
    def _validate_risk(
        risk_checks: Any,
    ) -> Dict[str, Any]:

        if not isinstance(risk_checks, dict):
            return {
                "valid": False,
                "reason": "RISK_CHECKS_MISSING",
            }

        required = (
            "spread_valid",
            "stop_loss_valid",
            "risk_within_limit",
            "daily_limit_valid",
            "consecutive_loss_limit_valid",
            "reward_risk_valid",
        )

        missing = [
            name for name in required
            if risk_checks.get(name) is not True
        ]

        return {
            "valid": not missing,
            "missing_or_failed": missing,
            "reason": (
                "RISK_VALIDATION_PASSED"
                if not missing
                else "RISK_CHECKS_FAILED"
            ),
        }

    # ---------------------------------------------------------
    # PATHWAY RESULT
    # ---------------------------------------------------------

    @staticmethod
    def _pathway_reject(
        name: str,
        direction: str,
        reason: str,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        return {
            "pathway": name,
            "direction": direction,
            "qualified": False,
            "a_plus": False,
            "execution_authorized": False,
            "status": "REJECTED",
            "reason": reason,
            "evidence": evidence or {},
        }

    # ---------------------------------------------------------
    # PATHWAY 1: H1-ALIGNED CONTINUATION
    # ---------------------------------------------------------

    def _pathway_continuation(
        self,
        market_data: Dict[str, Any],
        current_price: Optional[float],
        direction: str,
        poi_evidence: Any,
        entry_evidence: Any,
    ) -> Dict[str, Any]:

        h1 = self._tf(market_data, "H1")
        m5 = self._tf(market_data, "M5")

        h1_direction = self.determine_h1_direction(h1)

        if h1_direction != direction:
            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "H1_DIRECTION_NOT_ALIGNED",
            )

        h1_poi = self._dict(
            self._dict(poi_evidence).get("H1")
        )

        h1_poi_validation = self._validate_poi(
            h1_poi,
            direction,
            current_price,
            require_tap=True,
        )

        if not h1_poi_validation["valid"]:
            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                h1_poi_validation["reason"],
            )

        m5_break = self.validate_m5_external_choch(
            m5,
            direction,
        )

        if not m5_break["valid"]:
            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                m5_break["reason"],
            )

        m5_poi = self._dict(
            self._dict(poi_evidence).get("M5")
        )

        m5_poi_validation = self._validate_poi(
            m5_poi,
            direction,
            current_price,
            require_tap=True,
        )

        if not m5_poi_validation["valid"]:
            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "M5_POI_TAP_REQUIRED",
                {
                    "m5_poi": m5_poi_validation,
                },
            )

        entry_validation = self._validate_entry(
            entry_evidence,
            direction,
        )

        if not entry_validation["valid"]:
            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                entry_validation["reason"],
            )

        return {
            "pathway": "H1_ALIGNED_CONTINUATION",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "CONTINUATION_EVIDENCE_CONFIRMED",
            "evidence": {
                "h1_direction": h1_direction,
                "h1_poi": h1_poi_validation,
                "m5_external_break": m5_break,
                "m5_poi": m5_poi_validation,
                "entry": entry_validation,
            },
        }

    # ---------------------------------------------------------
    # PATHWAY 2: H1 COUNTERTREND REVERSAL
    # ---------------------------------------------------------

    def _pathway_h1_countertrend(
        self,
        market_data: Dict[str, Any],
        current_price: Optional[float],
        direction: str,
        poi_evidence: Any,
        entry_evidence: Any,
    ) -> Dict[str, Any]:

        h1 = self._tf(market_data, "H1")
        m5 = self._tf(market_data, "M5")

        h1_direction = self.determine_h1_direction(h1)

        if h1_direction not in self.DIRECTIONS:
            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "H1_DIRECTION_UNAVAILABLE",
            )

        if h1_direction == direction:
            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "NOT_COUNTERTREND",
            )

        # A countertrend setup requires the M5 external
        # structure to break in the reversal direction.

        m5_break = self.validate_m5_external_choch(
            m5,
            direction,
        )

        if not m5_break["valid"]:
            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "M5_EXTERNAL_REVERSAL_NOT_CONFIRMED",
            )

        m5_poi = self._dict(
            self._dict(poi_evidence).get("M5")
        )

        poi_validation = self._validate_poi(
            m5_poi,
            direction,
            current_price,
            require_tap=True,
        )

        if not poi_validation["valid"]:
            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                poi_validation["reason"],
            )

        entry_validation = self._validate_entry(
            entry_evidence,
            direction,
        )

        if not entry_validation["valid"]:
            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                entry_validation["reason"],
            )

        return {
            "pathway": "H1_COUNTERTREND_REVERSAL",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "COUNTERTREND_REVERSAL_CONFIRMED",
            "evidence": {
                "h1_direction": h1_direction,
                "m5_external_break": m5_break,
                "m5_poi": poi_validation,
                "entry": entry_validation,
            },
        }

    # ---------------------------------------------------------
    # PATHWAY 3: M5 INTERNAL COUNTERTREND
    # ---------------------------------------------------------

    def _pathway_internal(
        self,
        market_data: Dict[str, Any],
        current_price: Optional[float],
        direction: str,
        poi_evidence: Any,
        entry_evidence: Any,
    ) -> Dict[str, Any]:

        m5 = self._tf(market_data, "M5")

        external = self._dict(
            m5.get("external_structure")
        )

        internal = self._dict(
            m5.get("internal_structure")
        )

        external_direction = self._direction(
            external.get("direction")
            or external.get("bias")
        )

        internal_direction = self._direction(
            internal.get("direction")
            or internal.get("bias")
        )

        if external_direction not in self.DIRECTIONS:
            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "M5_EXTERNAL_STRUCTURE_UNAVAILABLE",
            )

        if internal_direction != direction:
            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "INTERNAL_DIRECTION_NOT_CONFIRMED",
            )

        if external_direction == direction:
            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "NOT_COUNTERTREND_TO_EXTERNAL",
            )

        internal_break = self._find_break(
            internal,
            direction,
        )

        if internal_break is None:
            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "INTERNAL_BODY_CLOSE_BREAK_MISSING",
            )

        internal_poi = self._dict(
            self._dict(poi_evidence).get("M5_INTERNAL")
        )

        poi_validation = self._validate_poi(
            internal_poi,
            direction,
            current_price,
            require_tap=True,
        )

        if not poi_validation["valid"]:
            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                poi_validation["reason"],
            )

        entry_validation = self._validate_entry(
            entry_evidence,
            direction,
        )

        if not entry_validation["valid"]:
            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                entry_validation["reason"],
            )

        return {
            "pathway": "M5_INTERNAL_COUNTERTREND",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "INTERNAL_COUNTERTREND_CONFIRMED",
            "evidence": {
                "external_direction": external_direction,
                "internal_direction": internal_direction,
                "internal_break": deepcopy(internal_break),
                "internal_poi": poi_validation,
                "entry": entry_validation,
            },
        }

    # ---------------------------------------------------------
    # PATHWAY 4: RANGING MARKET
    # ---------------------------------------------------------

    def _pathway_range(
        self,
        market_data: Dict[str, Any],
        current_price: Optional[float],
        direction: str,
        poi_evidence: Any,
        entry_evidence: Any,
    ) -> Dict[str, Any]:

        h1 = self._tf(market_data, "H1")
        m5 = self._tf(market_data, "M5")

        h1_direction = self.determine_h1_direction(h1)

        range_data = self._dict(
            h1.get("range")
        )

        if not range_data:
            range_data = self._dict(
                h1.get("premium_discount")
            )

        range_high = self._number(
            range_data.get("range_high")
            or range_data.get("high")
        )

        range_low = self._number(
            range_data.get("range_low")
            or range_data.get("low")
        )

        if range_high is None or range_low is None:
            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                "RANGE_BOUNDARIES_MISSING",
            )

        if range_high <= range_low:
            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                "INVALID_RANGE_BOUNDARIES",
            )

        if current_price is None:
            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                "CURRENT_PRICE_MISSING",
            )

        if not (
            range_low <= current_price <= range_high
        ):
            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                "PRICE_OUTSIDE_RANGE",
            )

        equilibrium = (
            range_high + range_low
        ) / 2

        if direction == "BULLISH":
            if current_price >= equilibrium:
                return self._pathway_reject(
                    "RANGING_MARKET",
                    direction,
                    "BULLISH_SETUP_NOT_IN_DISCOUNT",
                )
        else:
            if current_price <= equilibrium:
                return self._pathway_reject(
                    "RANGING_MARKET",
                    direction,
                    "BEARISH_SETUP_NOT_IN_PREMIUM",
                )

        range_poi = self._dict(
            self._dict(poi_evidence).get("RANGE")
        )

        poi_validation = self._validate_poi(
            range_poi,
            direction,
            current_price,
            require_tap=True,
        )

        if not poi_validation["valid"]:
            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                poi_validation["reason"],
            )

        entry_validation = self._validate_entry(
            entry_evidence,
            direction,
        )

        if not entry_validation["valid"]:
            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                entry_validation["reason"],
            )

        return {
            "pathway": "RANGING_MARKET",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "RANGE_SETUP_CONFIRMED",
            "evidence": {
                "range_high": range_high,
                "range_low": range_low,
                "equilibrium": equilibrium,
                "h1_direction": h1_direction,
                "poi": poi_validation,
                "entry": entry_validation,
            },
        }

    # ---------------------------------------------------------
    # PATHWAY SCORE INPUT
    # ---------------------------------------------------------

    def _pathway_scores(
        self,
        category_scores: Any,
        pathway_name: str,
    ) -> Dict[str, Any]:

        scores = self._dict(category_scores)

        if pathway_name in scores:
            pathway_scores = self._dict(
                scores.get(pathway_name)
            )

            return pathway_scores

        return scores

    # ---------------------------------------------------------
    # COMPLETE PATHWAY EVALUATION
    # ---------------------------------------------------------

    def _evaluate_pathway(
        self,
        pathway_result: Dict[str, Any],
        category_scores: Any,
        risk_checks: Any,
        fundamentals: Any,
    ) -> Dict[str, Any]:

        if not pathway_result.get("qualified"):
            return pathway_result

        name = pathway_result["pathway"]

        scores = self._pathway_scores(
            category_scores,
            name,
        )

        # Fundamentals are optional context. If a score was
        # not supplied, the category remains incomplete.
        if (
            "fundamentals" not in scores
            and isinstance(fundamentals, dict)
            and fundamentals.get("score") is not None
        ):
            scores = dict(scores)
            scores["fundamentals"] = fundamentals["score"]

        scoring = self.calculate_a_plus_score(
            scores
        )

        risk = self._validate_risk(
            risk_checks
        )

        result = deepcopy(pathway_result)

        result["scoring"] = scoring
        result["risk"] = risk

        if not scoring["complete"]:
            result["status"] = "INCOMPLETE_SCORE"
            result["a_plus"] = False
            result["execution_authorized"] = False
            result["reason"] = "CATEGORY_SCORES_INCOMPLETE"
            return result

        if scoring["score"] < self.A_PLUS_THRESHOLD:
            result["status"] = "BELOW_A_PLUS_THRESHOLD"
            result["a_plus"] = False
            result["execution_authorized"] = False
            result["reason"] = "SCORE_BELOW_85"
            return result

        if not risk["valid"]:
            result["status"] = "RISK_REJECTED"
            result["a_plus"] = True
            result["execution_authorized"] = False
            result["reason"] = "RISK_VALIDATION_FAILED"
            return result

        result["status"] = "A_PLUS_SETUP"
        result["a_plus"] = True
        result["execution_authorized"] = False
        result["reason"] = "A_PLUS_SETUP_QUALIFIED"

        return result

    # ---------------------------------------------------------
    # MASTER ANALYSIS
    # ---------------------------------------------------------

    def analyse(
        self,
        market_data: Dict[str, Any],
        current_price: float,
        entry_evidence: Any,
        poi_evidence: Any,
        displacement_evidence: Any,
        fvg_evidence: Any,
        risk_checks: Any,
        category_scores: Optional[Dict[str, Any]] = None,
        fundamentals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        market_data = self._dict(market_data)

        current_price = self._number(
            current_price
        )

        entry_evidence = self._dict(
            entry_evidence
        )

        poi_evidence = self._dict(
            poi_evidence
        )

        risk_checks = self._dict(
            risk_checks
        )

        category_scores = self._dict(
            category_scores
        )

        fundamentals = self._dict(
            fundamentals
        )

        h1 = self._tf(market_data, "H1")

        h1_direction = self.determine_h1_direction(
            h1
        )

        pathways = {}

        # Each pathway is evaluated independently.
        # A rejection in one pathway does not stop others.

        for direction in self.DIRECTIONS:

            continuation = (
                self._pathway_continuation(
                    market_data,
                    current_price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                )
            )

            countertrend = (
                self._pathway_h1_countertrend(
                    market_data,
                    current_price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                )
            )

            internal = self._pathway_internal(
                market_data,
                current_price,
                direction,
                poi_evidence,
                entry_evidence,
            )

            ranging = self._pathway_range(
                market_data,
                current_price,
                direction,
                poi_evidence,
                entry_evidence,
            )

            for pathway in (
                continuation,
                countertrend,
                internal,
                ranging,
            ):
                pathway = self._evaluate_pathway(
                    pathway,
                    category_scores,
                    risk_checks,
                    fundamentals,
                )

                pathways[
                    pathway["pathway"] + "_" + direction
                ] = pathway

        qualified = [
            result
            for result in pathways.values()
            if (
                result.get("status") == "A_PLUS_SETUP"
                and result.get("a_plus") is True
            )
        ]

        # Keep all qualifying pathways. Do not collapse
        # simultaneous valid setups into a single pathway.

        best = None

        if qualified:
            best = max(
                qualified,
                key=lambda item: item.get(
                    "scoring", {}
                ).get("score", 0),
            )

        if best:
            overall_status = "A_PLUS_SETUP"
        elif any(
            item.get("status") == "INCOMPLETE_SCORE"
            for item in pathways.values()
        ):
            overall_status = "INCOMPLETE_EVIDENCE"
        else:
            overall_status = "NO_CONFIRMED_SETUP"

        result = {
            "success": True,
            "version": self.VERSION,
            "status": overall_status,
            "symbol": market_data.get("symbol"),
            "current_price": current_price,
            "h1_direction": h1_direction,

            "pathways": pathways,
            "qualified_pathways": qualified,
            "qualified_pathway_count": len(qualified),

            "best_setup": deepcopy(best),
            "direction": (
                best.get("direction") if best else None
            ),
            "pathway": (
                best.get("pathway") if best else None
            ),

            "a_plus": (
                best.get("a_plus", False)
                if best
                else False
            ),

            "score": (
                best.get("scoring", {}).get("score")
                if best
                else None
            ),

            "execution_authorized": False,
            "evidence_only": True,
            "trade_authorization_pending": bool(best),

            "reason": (
                "A_PLUS_SETUP_QUALIFIED"
                if best
                else overall_status
            ),
        }

        self.last_analysis = deepcopy(result)
        return result

    # ---------------------------------------------------------
    # REJECTION COMPATIBILITY
    # ---------------------------------------------------------

    def _reject(
        self,
        reason: str,
        **kwargs,
    ) -> Dict[str, Any]:

        result = {
            "success": False,
            "version": self.VERSION,
            "status": "REJECTED",
            "a_plus": False,
            "execution_authorized": False,
            "reason": reason,
        }

        result.update(kwargs)

        self.last_analysis = deepcopy(result)

        return result

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "threshold": self.A_PLUS_THRESHOLD,
            "pathways": list(self.PATHWAYS),
            "last_analysis_status": (
                self.last_analysis.get("status")
                if self.last_analysis
                else "NOT_ANALYZED"
            ),
        }

    def get_last_analysis(self) -> Dict[str, Any]:
        return deepcopy(self.last_analysis)


# ---------------------------------------------------------
# SHARED ENGINE INSTANCE
# ---------------------------------------------------------

smc_engine = SMCEngine()
