"""
Vrotex Bot V1
Master Smart Money Concepts Engine
Version: 3.2 - Execution Authorization Enabled

Four approved pathways:
1. H1-aligned continuation
2. H1 countertrend reversal
3. M5 internal countertrend reversal
4. Ranging-market opportunities

A+ threshold: 85/100
Adapter: SMC Integration Adapter V4.1

This engine authorizes qualifying trade decisions for the downstream
execution engine. It does not itself submit broker orders.
"""

from __future__ import annotations

import math
import logging
from copy import deepcopy

logger = logging.getLogger("vrotex.smc_engine")

try:
    from smc_integration_adapter import smc_integration_adapter
    ADAPTER_AVAILABLE = True
except ImportError:
    smc_integration_adapter = None
    ADAPTER_AVAILABLE = False
    logger.exception("SMC integration adapter import failed")


class SMCEngine:
    VERSION = "3.2"
    EXECUTION_ENABLED = True
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

    REQUIRED_RISK_CHECKS = (
        "spread_valid",
        "stop_loss_valid",
        "risk_within_limit",
        "daily_limit_valid",
        "consecutive_loss_limit_valid",
        "reward_risk_valid",
    )

    def __init__(self, adapter=None):
        self.adapter = (
            adapter
            if adapter is not None
            else smc_integration_adapter
        )
        self.last_analysis = {}
        self.adapter_errors = 0

    # ----------------------- Helpers -----------------------

    @staticmethod
    def _dict(value):
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _list(value):
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return []

    @staticmethod
    def _number(value):
        try:
            n = float(value)
            return n if math.isfinite(n) else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _direction(value):
        value = str(value or "").upper().strip()

        aliases = {
            "BULL": "BULLISH",
            "BUY": "BULLISH",
            "LONG": "BULLISH",
            "UP": "BULLISH",
            "BEAR": "BEARISH",
            "SELL": "BEARISH",
            "SHORT": "BEARISH",
            "DOWN": "BEARISH",
            "RANGE": "RANGING",
            "SIDEWAYS": "RANGING",
            "NEUTRAL": "RANGING",
        }

        value = aliases.get(value, value)

        return (
            value
            if value in ("BULLISH", "BEARISH", "RANGING")
            else None
        )

    @staticmethod
    def _event_type(event):
        event = SMCEngine._dict(event)

        raw = str(
            event.get(
                "type",
                event.get(
                    "event",
                    event.get("break_type", ""),
                ),
            )
        ).upper().strip()

        return {
            "CHANGE_OF_CHARACTER": "CHOCH",
            "CHANGE CHARACTER": "CHOCH",
            "BREAK_OF_STRUCTURE": "BOS",
            "BREAK STRUCTURE": "BOS",
        }.get(raw, raw)

    @staticmethod
    def _body_close(event):
        event = SMCEngine._dict(event)

        confirmation = str(
            event.get("confirmation", "")
        ).upper().strip()

        # Strict: generic confirmed=True is not a body-close confirmation.
        return (
            event.get("body_close_confirmed") is True
            or event.get("body_close") is True
            or event.get("close_confirmed") is True
            or confirmation == "BODY_CLOSE"
        )

    @staticmethod
    def _technical(data):
        data = SMCEngine._dict(data)

        return (
            data.get("technical")
            if isinstance(data.get("technical"), dict)
            else data
        )

    def _tf(self, market_data, timeframe):
        return self._technical(
            self._dict(market_data).get(timeframe)
        )

    @staticmethod
    def _price_inside_zone(price, zone):
        if price is None:
            return False

        zone = SMCEngine._dict(zone)

        low = SMCEngine._number(
            zone.get(
                "lower",
                zone.get(
                    "low",
                    zone.get("bottom"),
                ),
            )
        )

        high = SMCEngine._number(
            zone.get(
                "upper",
                zone.get(
                    "high",
                    zone.get("top"),
                ),
            )
        )

        return (
            low is not None
            and high is not None
            and low <= high
            and low <= price <= high
        )

    # ------------------- Strict break checks -------------------

    def _confirmed_break(
        self,
        event,
        direction,
        required_type=None,
        external_only=False,
    ):
        event = self._dict(event)

        event_direction = self._direction(
            event.get(
                "direction",
                event.get("bias"),
            )
        )

        event_type = self._event_type(event)

        if (
            event.get("invalidated") is True
            or not self._body_close(event)
        ):
            return False

        if event_direction != direction:
            return False

        if required_type and event_type != required_type.upper():
            return False

        if (
            external_only
            and str(
                event.get("structure_type", "")
            ).upper() != "EXTERNAL"
        ):
            return False

        return True

    def _find_break(
        self,
        structure,
        direction,
        required_type=None,
        external_only=False,
    ):
        structure = self._dict(structure)

        external = self._dict(
            structure.get("external_structure")
        )

        events = (
            self._list(external.get("breaks"))
            if external_only
            else []
        )

        if not events:
            events = self._list(
                structure.get("breaks")
            )

        for event in reversed(events):
            if self._confirmed_break(
                event,
                direction,
                required_type,
                external_only,
            ):
                return deepcopy(event)

        return None

    def determine_h1_direction(self, data):
        data = self._technical(data)

        direction = self._direction(
            data.get("direction")
        )

        if direction in self.DIRECTIONS:
            return direction

        structure = self._dict(
            data.get("structure")
        )

        direction = self._direction(
            structure.get("direction")
            or structure.get("bias")
        )

        if direction in self.DIRECTIONS:
            return direction

        return self._direction(
            data.get("bias")
        )

    def validate_m5_external_choch(
        self,
        data,
        expected_direction,
    ):
        data = self._technical(data)

        expected_direction = self._direction(
            expected_direction
        )

        if expected_direction not in self.DIRECTIONS:
            return {
                "valid": False,
                "reason": "INVALID_DIRECTION",
            }

        external = self._dict(
            data.get("external_structure")
        )

        # Only explicitly classified external breaks qualify.
        # No fallback to generic breaks.
        events = self._list(
            external.get("breaks")
        )

        for event in reversed(events):
            if self._confirmed_break(
                event,
                expected_direction,
                "CHOCH",
                external_only=True,
            ):
                return {
                    "valid": True,
                    "direction": expected_direction,
                    "event": deepcopy(event),
                    "reason": (
                        "EXTERNAL_CHOCH_BODY_CLOSE_CONFIRMED"
                    ),
                }

        return {
            "valid": False,
            "reason": "EXTERNAL_CHOCH_BODY_CLOSE_MISSING",
        }

    # ------------------------ Scoring ------------------------

    def calculate_a_plus_score(self, category_scores=None):
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

            raw = max(
                0.0,
                min(100.0, raw),
            )

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

    # ---------------- Adapter evidence ----------------

    def _build_adapter_evidence(
        self,
        direction,
        market_data,
        current_price,
        entry_evidence,
        poi_evidence,
        displacement_evidence,
        fvg_evidence,
        risk_checks,
    ):
        if self.adapter is None:
            return {
                "available": False,
                "error": "ADAPTER_NOT_CONNECTED",
            }

        try:
            h1, m5, m1 = (
                self._tf(market_data, tf)
                for tf in ("H1", "M5", "M1")
            )

            liquidity = self._dict(
                market_data.get("liquidity")
            )

            if not liquidity:
                liquidity = {
                    "H1": h1.get("liquidity", {}),
                    "M5": m5.get("liquidity", {}),
                    "M1": m1.get("liquidity", {}),
                }

            poi_items = []

            for timeframe, items in self._dict(
                poi_evidence
            ).items():

                source_items = (
                    [items]
                    if isinstance(items, dict)
                    else items
                    if isinstance(items, list)
                    else []
                )

                for item in source_items:
                    if isinstance(item, dict):
                        copied = deepcopy(item)
                        copied.setdefault(
                            "timeframe",
                            timeframe,
                        )
                        poi_items.append(copied)

            evidence = self.adapter.build_evidence(
                trade_direction=direction,
                h1_structure=h1,
                m5_structure=m5,
                m1_structure=m1,
                liquidity=liquidity,
                fvg=fvg_evidence,
                poi=poi_items,
                displacement=displacement_evidence,
                entry_models=entry_evidence,
                risk_checks=risk_checks,
                current_price=current_price,
            )

            return {
                "available": True,
                "evidence": evidence,
            }

        except Exception as exc:
            self.adapter_errors += 1

            logger.exception(
                "SMC adapter normalization failed"
            )

            return {
                "available": False,
                "error": str(exc),
            }

    # ------------------- POI / entry checks -------------------

    def _validate_poi(
        self,
        poi,
        direction,
        current_price,
        require_tap=True,
    ):
        candidates = (
            poi
            if isinstance(poi, list)
            else [poi]
        )

        selected = None

        for candidate in candidates:
            candidate = self._dict(candidate)

            if self._direction(
                candidate.get(
                    "direction",
                    candidate.get("bias"),
                )
            ) == direction:
                selected = candidate
                break

        if selected is None:
            return {
                "valid": False,
                "reason": (
                    "POI_EVIDENCE_MISSING_OR_DIRECTION_MISMATCH"
                ),
            }

        clean = (
            selected.get("clean") is True
            or selected.get("unmitigated") is True
        )

        if not clean:
            return {
                "valid": False,
                "reason": (
                    "POI_NOT_CLEAN_OR_UNMITIGATED"
                ),
            }

        if selected.get("invalidated") is True:
            return {
                "valid": False,
                "reason": "POI_INVALIDATED",
            }

        in_zone = self._price_inside_zone(
            current_price,
            selected,
        )

        tapped = (
            selected.get("tapped") is True
            or selected.get("tap_confirmed") is True
            or in_zone
        )

        if require_tap and not tapped:
            return {
                "valid": False,
                "reason": "PRICE_NOT_TAPPED_POI",
            }

        if not in_zone:
            return {
                "valid": False,
                "reason": "PRICE_OUTSIDE_POI_ZONE",
            }

        return {
            "valid": True,
            "reason": "VALID_POI_TAP",
            "poi": deepcopy(selected),
        }

    def _validate_entry(
        self,
        entry_evidence,
        direction,
    ):
        items = (
            entry_evidence
            if isinstance(entry_evidence, list)
            else None
        )

        valid_models = []

        if items is not None:
            for model in items:
                model = self._dict(model)

                if (
                    model.get("valid") is True
                    and model.get("retest_confirmed") is True
                    and model.get("invalidated") is not True
                    and self._direction(
                        model.get("direction")
                    ) == direction
                ):
                    valid_models.append(
                        model.get(
                            "model",
                            model.get("name", "ENTRY_MODEL"),
                        )
                    )

        else:
            entry = self._dict(entry_evidence)

            models = self._dict(
                entry.get("models")
            )

            confirmed_names = entry.get(
                "confirmed_models",
                [],
            )

            names = (
                confirmed_names
                if isinstance(confirmed_names, list)
                else []
            )

            for name, model in models.items():
                model = self._dict(model)

                if (
                    model.get("confirmed") is True
                    and model.get("retest_confirmed") is True
                    and model.get("invalidated") is not True
                    and self._direction(
                        model.get("direction")
                    ) == direction
                    and (not names or name in names)
                ):
                    valid_models.append(name)

            if (
                entry.get("confirmed") is True
                and entry.get("retest_confirmed") is True
                and entry.get("invalidated") is not True
                and self._direction(
                    entry.get("direction")
                ) == direction
            ):
                valid_models.append(
                    entry.get(
                        "model",
                        "ENTRY_CONFIRMED",
                    )
                )

        valid_models = list(
            dict.fromkeys(valid_models)
        )

        return {
            "valid": bool(valid_models),
            "models": valid_models,
            "reason": (
                "ENTRY_MODEL_AND_RETEST_CONFIRMED"
                if valid_models
                else "ENTRY_MODEL_RETEST_NOT_CONFIRMED"
            ),
        }

    def _validate_fvg(self, evidence, direction):
        items = self._list(
            self._dict(evidence).get("fvg")
        )

        valid = [
            deepcopy(item)
            for item in items
            if isinstance(item, dict)
            and item.get("valid_poi") is True
            and item.get("invalidated") is not True
            and self._direction(
                item.get("direction")
            ) == direction
        ]

        return {
            "valid": bool(valid),
            "reason": (
                "DIRECTIONAL_FVG_CONFIRMED"
                if valid
                else "VALID_DIRECTIONAL_FVG_MISSING"
            ),
            "fvg": valid,
        }

    def _validate_displacement(
        self,
        evidence,
        direction,
    ):
        items = self._list(
            self._dict(evidence).get("displacement")
        )

        valid = [
            deepcopy(item)
            for item in items
            if isinstance(item, dict)
            and item.get("valid") is True
            and item.get("invalidated") is not True
            and self._direction(
                item.get("direction")
            ) == direction
        ]

        return {
            "valid": bool(valid),
            "reason": (
                "DIRECTIONAL_DISPLACEMENT_CONFIRMED"
                if valid
                else "DIRECTIONAL_DISPLACEMENT_MISSING"
            ),
            "displacement": valid,
        }

    def _validate_confirmation(
        self,
        adapter_evidence,
        direction,
    ):
        fvg = self._validate_fvg(
            adapter_evidence,
            direction,
        )

        displacement = self._validate_displacement(
            adapter_evidence,
            direction,
        )

        return {
            "valid": (
                fvg["valid"]
                and displacement["valid"]
            ),
            "fvg": fvg,
            "displacement": displacement,
        }

    def _validate_risk(self, risk_checks):
        risk_checks = self._dict(risk_checks)

        failed = [
            name
            for name in self.REQUIRED_RISK_CHECKS
            if risk_checks.get(name) is not True
        ]

        return {
            "valid": not failed,
            "missing_or_failed": failed,
            "reason": (
                "RISK_VALIDATION_PASSED"
                if not failed
                else "RISK_CHECKS_FAILED"
            ),
        }

    # ---------------- Pathway helpers ----------------

    @staticmethod
    def _reject_pathway(
        name,
        direction,
        reason,
        evidence=None,
    ):
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

    def _pathway_continuation(
        self,
        market_data,
        price,
        direction,
        poi,
        entry,
        confirmation,
    ):
        h1 = self._tf(market_data, "H1")
        m5 = self._tf(market_data, "M5")

        if self.determine_h1_direction(h1) != direction:
            return self._reject_pathway(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "H1_DIRECTION_NOT_ALIGNED",
            )

        h1poi = self._validate_poi(
            self._dict(poi).get("H1"),
            direction,
            price,
        )

        if not h1poi["valid"]:
            return self._reject_pathway(
                "H1_ALIGNED_CONTINUATION",
                direction,
                h1poi["reason"],
            )

        br = self.validate_m5_external_choch(
            m5,
            direction,
        )

        if not br["valid"]:
            return self._reject_pathway(
                "H1_ALIGNED_CONTINUATION",
                direction,
                br["reason"],
            )

        m5poi = self._validate_poi(
            self._dict(poi).get("M5"),
            direction,
            price,
        )

        if not m5poi["valid"]:
            return self._reject_pathway(
                "H1_ALIGNED_CONTINUATION",
                direction,
                m5poi["reason"],
            )

        conf = self._validate_confirmation(
            confirmation,
            direction,
        )

        if not conf["valid"]:
            return self._reject_pathway(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "CONFIRMATION_EVIDENCE_FAILED",
                conf,
            )

        ent = self._validate_entry(
            entry,
            direction,
        )

        if not ent["valid"]:
            return self._reject_pathway(
                "H1_ALIGNED_CONTINUATION",
                direction,
                ent["reason"],
            )

        return {
            "pathway": "H1_ALIGNED_CONTINUATION",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "CONTINUATION_EVIDENCE_CONFIRMED",
            "evidence": {
                "h1_direction": direction,
                "h1_poi": h1poi,
                "m5_external_choch": br,
                "m5_poi": m5poi,
                "confirmation": conf,
                "entry": ent,
            },
        }

    def _pathway_h1_countertrend(
        self,
        market_data,
        price,
        direction,
        poi,
        entry,
        confirmation,
    ):
        h1 = self._tf(market_data, "H1")
        m5 = self._tf(market_data, "M5")

        h1dir = self.determine_h1_direction(h1)

        if h1dir not in self.DIRECTIONS:
            return self._reject_pathway(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "H1_DIRECTION_UNAVAILABLE",
            )

        if h1dir == direction:
            return self._reject_pathway(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "NOT_COUNTERTREND",
            )

        br = self.validate_m5_external_choch(
            m5,
            direction,
        )

        if not br["valid"]:
            return self._reject_pathway(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "M5_EXTERNAL_REVERSAL_NOT_CONFIRMED",
            )

        p = self._validate_poi(
            self._dict(poi).get("M5"),
            direction,
            price,
        )

        if not p["valid"]:
            return self._reject_pathway(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                p["reason"],
            )

        conf = self._validate_confirmation(
            confirmation,
            direction,
        )

        if not conf["valid"]:
            return self._reject_pathway(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "CONFIRMATION_EVIDENCE_FAILED",
                conf,
            )

        ent = self._validate_entry(
            entry,
            direction,
        )

        if not ent["valid"]:
            return self._reject_pathway(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                ent["reason"],
            )

        return {
            "pathway": "H1_COUNTERTREND_REVERSAL",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "COUNTERTREND_REVERSAL_CONFIRMED",
            "evidence": {
                "h1_direction": h1dir,
                "m5_external_choch": br,
                "m5_poi": p,
                "confirmation": conf,
                "entry": ent,
            },
        }

    def _pathway_internal(
        self,
        market_data,
        price,
        direction,
        poi,
        entry,
        confirmation,
    ):
        m5 = self._tf(market_data, "M5")

        external = self._dict(
            m5.get("external_structure")
        )

        internal = self._dict(
            m5.get("internal_structure")
        )

        extdir = self._direction(
            external.get(
                "direction",
                external.get("bias"),
            )
        )

        intdir = self._direction(
            internal.get(
                "direction",
                internal.get("bias"),
            )
        )

        if extdir not in self.DIRECTIONS:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "M5_EXTERNAL_STRUCTURE_UNAVAILABLE",
            )

        if intdir != direction:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "INTERNAL_DIRECTION_NOT_CONFIRMED",
            )

        if extdir == direction:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "NOT_COUNTERTREND_TO_EXTERNAL",
            )

        br = self._find_break(
            internal,
            direction,
        )

        if br is None:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "INTERNAL_BODY_CLOSE_BREAK_MISSING",
            )

        p = self._validate_poi(
            self._dict(poi).get("M5_INTERNAL"),
            direction,
            price,
        )

        if not p["valid"]:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                p["reason"],
            )

        conf = self._validate_confirmation(
            confirmation,
            direction,
        )

        if not conf["valid"]:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "CONFIRMATION_EVIDENCE_FAILED",
                conf,
            )

        ent = self._validate_entry(
            entry,
            direction,
        )

        if not ent["valid"]:
            return self._reject_pathway(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                ent["reason"],
            )

        return {
            "pathway": "M5_INTERNAL_COUNTERTREND",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "INTERNAL_COUNTERTREND_CONFIRMED",
            "evidence": {
                "external_direction": extdir,
                "internal_direction": intdir,
                "internal_break": br,
                "internal_poi": p,
                "confirmation": conf,
                "entry": ent,
            },
        }

    def _pathway_range(
        self,
        market_data,
        price,
        direction,
        poi,
        entry,
        confirmation,
    ):
        h1 = self._tf(market_data, "H1")

        range_data = (
            self._dict(h1.get("range"))
            or self._dict(h1.get("premium_discount"))
        )

        high = self._number(
            range_data.get(
                "range_high",
                range_data.get("high"),
            )
        )

        low = self._number(
            range_data.get(
                "range_low",
                range_data.get("low"),
            )
        )

        if high is None or low is None or high <= low:
            return self._reject_pathway(
                "RANGING_MARKET",
                direction,
                "RANGE_BOUNDARIES_MISSING_OR_INVALID",
            )

        if price is None or not low <= price <= high:
            return self._reject_pathway(
                "RANGING_MARKET",
                direction,
                "PRICE_OUTSIDE_RANGE_OR_MISSING",
            )

        eq = (high + low) / 2

        if (
            direction == "BULLISH"
            and price >= eq
        ) or (
            direction == "BEARISH"
            and price <= eq
        ):
            return self._reject_pathway(
                "RANGING_MARKET",
                direction,
                "WRONG_RANGE_HALF",
            )

        p = self._validate_poi(
            self._dict(poi).get("RANGE"),
            direction,
            price,
        )

        if not p["valid"]:
            return self._reject_pathway(
                "RANGING_MARKET",
                direction,
                p["reason"],
            )

        conf = self._validate_confirmation(
            confirmation,
            direction,
        )

        if not conf["valid"]:
            return self._reject_pathway(
                "RANGING_MARKET",
                direction,
                "RANGE_CONFIRMATION_FAILED",
                conf,
            )

        ent = self._validate_entry(
            entry,
            direction,
        )

        if not ent["valid"]:
            return self._reject_pathway(
                "RANGING_MARKET",
                direction,
                ent["reason"],
            )

        return {
            "pathway": "RANGING_MARKET",
            "direction": direction,
            "qualified": True,
            "status": "QUALIFIED_PENDING_SCORE",
            "reason": "RANGE_SETUP_CONFIRMED",
            "evidence": {
                "range_high": high,
                "range_low": low,
                "equilibrium": eq,
                "poi": p,
                "confirmation": conf,
                "entry": ent,
            },
        }

    # -------------------- Scoring and authorization --------------------

    def _pathway_scores(self, scores, name):
        scores = self._dict(scores)

        return (
            self._dict(scores.get(name))
            if name in scores
            else scores
        )

    def _evaluate_pathway(
        self,
        result,
        category_scores,
        risk_checks,
        fundamentals,
        adapter_ready,
    ):
        if not result.get("qualified"):
            return result

        name = result["pathway"]

        scores = self._pathway_scores(
            category_scores,
            name,
        )

        if (
            "fundamentals" not in scores
            and fundamentals.get("score") is not None
        ):
            scores = dict(scores)
            scores["fundamentals"] = fundamentals.get("score")

        scoring = self.calculate_a_plus_score(scores)
        risk = self._validate_risk(risk_checks)

        result = deepcopy(result)
        result["scoring"] = scoring
        result["risk"] = risk
        result["a_plus"] = False
        result["execution_authorized"] = False

        if not scoring["complete"]:
            result.update(
                status="INCOMPLETE_SCORE",
                reason="CATEGORY_SCORES_INCOMPLETE",
            )
            return result

        if scoring["score"] < self.A_PLUS_THRESHOLD:
            result.update(
                status="BELOW_A_PLUS_THRESHOLD",
                reason="SCORE_BELOW_85",
            )
            return result

        result["a_plus"] = True

        if not risk["valid"]:
            result.update(
                status="RISK_REJECTED",
                reason="RISK_VALIDATION_FAILED",
            )
            return result

        if not adapter_ready:
            result.update(
                status="ADAPTER_NOT_EXECUTION_READY",
                reason="ADAPTER_EVIDENCE_GATE_FAILED",
            )
            return result

        if not self.EXECUTION_ENABLED:
            result.update(
                status="EXECUTION_DISABLED",
                reason="ENGINE_EXECUTION_SWITCH_DISABLED",
            )
            return result

        result.update(
            status="A_PLUS_SETUP",
            reason="A_PLUS_SETUP_AUTHORIZED",
            execution_authorized=True,
        )

        return result

    # -------------------- Master analysis --------------------

    def analyse(
        self,
        market_data,
        current_price,
        entry_evidence,
        poi_evidence,
        displacement_evidence,
        fvg_evidence,
        risk_checks,
        category_scores=None,
        fundamentals=None,
    ):
        market_data = self._dict(market_data)
        price = self._number(current_price)
        poi_evidence = self._dict(poi_evidence)
        risk_checks = self._dict(risk_checks)
        category_scores = self._dict(category_scores)
        fundamentals = self._dict(fundamentals)

        h1_direction = self.determine_h1_direction(
            self._tf(market_data, "H1")
        )

        adapter_results = {}

        for direction in self.DIRECTIONS:
            adapter_results[direction] = (
                self._build_adapter_evidence(
                    direction,
                    market_data,
                    price,
                    entry_evidence,
                    poi_evidence,
                    displacement_evidence,
                    fvg_evidence,
                    risk_checks,
                )
            )

        pathways = {}

        for direction in self.DIRECTIONS:
            ar = adapter_results[direction]

            normalized = self._dict(
                ar.get("evidence")
            )

            adapter_available = (
                ar.get("available") is True
            )

            adapter_ready = (
                adapter_available
                and normalized.get("execution_ready") is True
            )

            confirmation_input = (
                normalized
                if adapter_available
                else {}
            )

            pathway_results = (
                self._pathway_continuation(
                    market_data,
                    price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    confirmation_input,
                ),
                self._pathway_h1_countertrend(
                    market_data,
                    price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    confirmation_input,
                ),
                self._pathway_internal(
                    market_data,
                    price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    confirmation_input,
                ),
                self._pathway_range(
                    market_data,
                    price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    confirmation_input,
                ),
            )

            for item in pathway_results:
                item = self._evaluate_pathway(
                    item,
                    category_scores,
                    risk_checks,
                    fundamentals,
                    adapter_ready,
                )

                key = (
                    item["pathway"]
                    + "_"
                    + direction
                )

                pathways[key] = item

        authorized = [
            item
            for item in pathways.values()
            if item.get("execution_authorized") is True
        ]

        qualified = [
            item
            for item in pathways.values()
            if (
                item.get("a_plus") is True
                and item.get("qualified") is True
            )
        ]

        best = (
            max(
                authorized,
                key=lambda x: x.get(
                    "scoring", {}
                ).get("score", 0),
            )
            if authorized
            else None
        )

        best_candidate = (
            max(
                qualified,
                key=lambda x: x.get(
                    "scoring", {}
                ).get("score", 0),
            )
            if qualified
            else None
        )

        if best:
            status = "EXECUTION_AUTHORIZED"

        elif best_candidate:
            status = best_candidate.get(
                "status",
                "NOT_AUTHORIZED",
            )

        elif any(
            x.get("status") == "INCOMPLETE_SCORE"
            for x in pathways.values()
        ):
            status = "INCOMPLETE_EVIDENCE"

        else:
            status = "NO_CONFIRMED_SETUP"

        # Execution payload is a decision handoff,
        # not a broker order submission.

        execution_payload = None

        if best:
            execution_payload = {
                "authorized": True,
                "symbol": market_data.get("symbol"),
                "direction": best.get("direction"),
                "pathway": best.get("pathway"),
                "score": best.get(
                    "scoring", {}
                ).get("score"),
                "current_price": price,
                "risk_checks": deepcopy(risk_checks),
                "trade_plan": deepcopy(
                    risk_checks.get(
                        "trade_plan",
                        risk_checks.get("execution_plan"),
                    )
                ),
                "evidence": deepcopy(
                    best.get("evidence")
                ),
            }

        result = {
            "success": True,
            "version": self.VERSION,
            "execution_enabled": self.EXECUTION_ENABLED,
            "status": status,
            "symbol": market_data.get("symbol"),
            "current_price": price,
            "h1_direction": h1_direction,

            "adapter": {
                "available": self.adapter is not None,
                "connected": all(
                    x.get("available") is True
                    for x in adapter_results.values()
                ),
                "errors": self.adapter_errors,
                "evidence": adapter_results,
            },

            "pathways": pathways,
            "qualified_pathways": qualified,
            "authorized_pathways": authorized,
            "qualified_pathway_count": len(qualified),
            "authorized_pathway_count": len(authorized),
            "best_setup": deepcopy(best),
            "best_candidate": deepcopy(best_candidate),

            "direction": (
                best.get("direction")
                if best
                else None
            ),

            "pathway": (
                best.get("pathway")
                if best
                else None
            ),

            "a_plus": (
                best.get("a_plus", False)
                if best
                else False
            ),

            "score": (
                best.get(
                    "scoring", {}
                ).get("score")
                if best
                else None
            ),

            "execution_authorized": bool(best),
            "execution_payload": execution_payload,
            "evidence_only": False,
            "trade_authorization_pending": bool(
                best_candidate and not best
            ),

            "reason": (
                "A_PLUS_SETUP_AUTHORIZED"
                if best
                else status
            ),
        }

        self.last_analysis = deepcopy(result)
        return result

    # ---------------- Compatibility / status ----------------

    def _reject(self, reason, **kwargs):
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

    def get_status(self):
        return {
            "version": self.VERSION,
            "execution_enabled": self.EXECUTION_ENABLED,
            "threshold": self.A_PLUS_THRESHOLD,
            "pathways": list(self.PATHWAYS),
            "adapter_connected": self.adapter is not None,
            "adapter_errors": self.adapter_errors,
            "last_analysis_status": self.last_analysis.get(
                "status",
                "NOT_ANALYZED",
            ),
        }

    def get_last_analysis(self):
        return deepcopy(self.last_analysis)


# =============================================================
# SHARED ENGINE INSTANCE
# =============================================================

smc_engine = SMCEngine()
