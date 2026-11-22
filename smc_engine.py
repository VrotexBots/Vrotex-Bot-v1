"""
Vrotex Bot V1
Master Smart Money Concepts Engine
Version: 3.1

Four independent setup pathways:
1. H1-aligned continuation
2. H1 countertrend reversal
3. M5 internal countertrend reversal
4. Ranging-market opportunities

A+ threshold: 85/100

Evidence is normalized through SMCIntegrationAdapter.
Execution authorization remains downstream.

Existing public interfaces preserved.
"""

from __future__ import annotations

import math
import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vrotex.smc_engine")


# =============================================================
# ADAPTER CONNECTION
# =============================================================

try:
    from smc_integration_adapter import (
        smc_integration_adapter,
    )

    ADAPTER_AVAILABLE = True

except ImportError:

    smc_integration_adapter = None
    ADAPTER_AVAILABLE = False

    logger.exception(
        "SMC integration adapter import failed"
    )


# =============================================================
# MASTER ENGINE
# =============================================================

class SMCEngine:

    VERSION = "3.1"

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

    DIRECTIONS = (
        "BULLISH",
        "BEARISH",
    )

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

    # =========================================================
    # SAFE HELPERS
    # =========================================================

    @staticmethod
    def _dict(value):

        return (
            value
            if isinstance(value, dict)
            else {}
        )

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

            number = float(value)

            if not math.isfinite(number):
                return None

            return number

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):

            return None

    @staticmethod
    def _direction(value):

        value = str(
            value or ""
        ).upper().strip()

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

        value = aliases.get(
            value,
            value,
        )

        if value in (
            "BULLISH",
            "BEARISH",
            "RANGING",
        ):

            return value

        return None

    @staticmethod
    def _normalise_trade_direction(value):

        return SMCEngine._direction(
            value
        )

    @staticmethod
    def _opposite(direction):

        if direction == "BULLISH":
            return "BEARISH"

        return "BULLISH"

    @staticmethod
    def _technical(data):

        data = SMCEngine._dict(data)

        if isinstance(
            data.get("technical"),
            dict,
        ):

            return data["technical"]

        return data

    def _tf(
        self,
        market_data,
        timeframe,
    ):

        market_data = self._dict(
            market_data
        )

        return self._technical(
            market_data.get(
                timeframe
            )
        )

    @staticmethod
    def _price_inside_zone(
        price,
        zone,
    ):

        if price is None:
            return False

        zone = SMCEngine._dict(
            zone
        )

        lower = SMCEngine._number(
            zone.get(
                "lower",
                zone.get(
                    "low",
                    zone.get(
                        "bottom"
                    )
                ),
            )
        )

        upper = SMCEngine._number(
            zone.get(
                "upper",
                zone.get(
                    "high",
                    zone.get(
                        "top"
                    ),
                ),
            )
        )

        if (
            lower is None
            or upper is None
        ):

            return False

        if lower > upper:
            return False

        return (
            lower
            <= price
            <= upper
        )

    # =========================================================
    # BREAK VALIDATION
    # =========================================================

    @staticmethod
    def _confirmed_break(
        event,
        direction,
    ):

        event = SMCEngine._dict(
            event
        )

        event_direction = (
            SMCEngine._direction(
                event.get(
                    "direction"
                )
            )
        )

        confirmed = (
            event.get(
                "confirmed"
            ) is True
            or event.get(
                "body_close_confirmed"
            ) is True
            or event.get(
                "close_confirmed"
            ) is True
        )

        body_close = (
            event.get(
                "confirmation"
            ) == "BODY_CLOSE"
            or event.get(
                "body_close_confirmed"
            ) is True
            or event.get(
                "close_confirmed"
            ) is True
            or event.get(
                "body_close"
            ) is True
        )

        invalidated = (
            event.get(
                "invalidated"
            ) is True
        )

        return (
            event_direction == direction
            and confirmed
            and body_close
            and not invalidated
        )

    def _find_break(
        self,
        technical,
        direction,
    ):

        technical = self._dict(
            technical
        )

        # Prefer external structure when
        # explicitly supplied.

        external = self._dict(
            technical.get(
                "external_structure"
            )
        )

        events = self._list(
            external.get(
                "breaks"
            )
        )

        if not events:

            events = self._list(
                technical.get(
                    "breaks"
                )
            )

        for event in reversed(
            events
        ):

            if not isinstance(
                event,
                dict,
            ):
                continue

            if self._confirmed_break(
                event,
                direction,
            ):

                return deepcopy(
                    event
                )

        return None

    # =========================================================
    # H1 DIRECTION
    # =========================================================

    def determine_h1_direction(
        self,
        data,
    ):

        data = self._technical(
            data
        )

        direction = self._direction(
            data.get(
                "direction"
            )
        )

        if direction in self.DIRECTIONS:
            return direction

        structure = self._dict(
            data.get(
                "structure"
            )
        )

        direction = self._direction(
            structure.get(
                "direction"
            )
            or structure.get(
                "bias"
            )
        )

        if direction in self.DIRECTIONS:
            return direction

        return self._direction(
            data.get(
                "bias"
            )
        )

    # =========================================================
    # M5 EXTERNAL BREAK VALIDATION
    # =========================================================

    def validate_m5_external_choch(
        self,
        data,
        expected_direction,
    ):

        data = self._technical(
            data
        )

        expected_direction = (
            self._direction(
                expected_direction
            )
        )

        if (
            expected_direction
            not in self.DIRECTIONS
        ):

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
                "reason": (
                    "BODY_CLOSE_EXTERNAL_BREAK_MISSING"
                ),
            }

        return {
            "valid": True,
            "direction": expected_direction,
            "event": event,
            "reason": (
                "EXTERNAL_BREAK_CONFIRMED"
            ),
        }

    # =========================================================
    # SCORE CALCULATION
    # =========================================================

    def calculate_a_plus_score(
        self,
        category_scores=None,
    ):

        category_scores = self._dict(
            category_scores
        )

        total = 0.0
        details = {}
        complete = True

        for category, weight in (
            self.CATEGORY_WEIGHTS.items()
        ):

            raw = self._number(
                category_scores.get(
                    category
                )
            )

            if raw is None:

                complete = False
                raw = 0.0

            raw = max(
                0.0,
                min(
                    100.0,
                    raw,
                ),
            )

            weighted = (
                raw
                * weight
                / 100.0
            )

            total += weighted

            details[category] = {
                "score": raw,
                "weight": weight,
                "weighted_score": round(
                    weighted,
                    4,
                ),
            }

        total = round(
            total,
            2,
        )

        return {
            "score": total,
            "threshold": self.A_PLUS_THRESHOLD,
            "a_plus": (
                total
                >= self.A_PLUS_THRESHOLD
            ),
            "complete": complete,
            "categories": details,
        }

    # =========================================================
    # ADAPTER EVIDENCE NORMALIZATION
    # =========================================================

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

            h1 = self._tf(
                market_data,
                "H1",
            )

            m5 = self._tf(
                market_data,
                "M5",
            )

            m1 = self._tf(
                market_data,
                "M1",
            )

            liquidity = (
                market_data.get(
                    "liquidity",
                    {},
                )
            )

            if not liquidity:

                liquidity = {
                    "H1": h1.get(
                        "liquidity",
                        {},
                    ),
                    "M5": m5.get(
                        "liquidity",
                        {},
                    ),
                    "M1": m1.get(
                        "liquidity",
                        {},
                    ),
                }

            # Flatten POIs for adapter normalization.
            # Original timeframe mapping is retained
            # separately for pathway evaluation.

            poi_items = []

            for timeframe, items in (
                self._dict(
                    poi_evidence
                ).items()
            ):

                if isinstance(
                    items,
                    dict,
                ):

                    item = deepcopy(
                        items
                    )

                    item.setdefault(
                        "timeframe",
                        timeframe,
                    )

                    poi_items.append(
                        item
                    )

                elif isinstance(
                    items,
                    list,
                ):

                    for item in items:

                        if isinstance(
                            item,
                            dict,
                        ):

                            item = deepcopy(
                                item
                            )

                            item.setdefault(
                                "timeframe",
                                timeframe,
                            )

                            poi_items.append(
                                item
                            )

            evidence = (
                self.adapter.build_evidence(
                    trade_direction=direction,
                    h1_structure=h1,
                    m5_structure=m5,
                    m1_structure=m1,
                    liquidity=liquidity,
                    fvg=fvg_evidence,
                    poi=poi_items,
                    displacement=(
                        displacement_evidence
                    ),
                    entry_models=(
                        entry_evidence
                    ),
                    risk_checks=risk_checks,
                    current_price=current_price,
                )
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

    # =========================================================
    # POI VALIDATION
    # =========================================================

    def _validate_poi(
        self,
        poi,
        direction,
        current_price,
        require_tap=True,
    ):

        if isinstance(
            poi,
            list,
        ):

            candidates = poi

            poi = None

            for candidate in candidates:

                candidate = self._dict(
                    candidate
                )

                if (
                    self._direction(
                        candidate.get(
                            "direction"
                        )
                    )
                    == direction
                ):

                    poi = candidate
                    break

        if not isinstance(
            poi,
            dict,
        ):

            return {
                "valid": False,
                "reason": (
                    "POI_EVIDENCE_MISSING"
                ),
            }

        poi = self._dict(
            poi
        )

        poi_direction = (
            self._direction(
                poi.get(
                    "direction"
                )
            )
        )

        if poi_direction != direction:

            return {
                "valid": False,
                "reason": (
                    "POI_DIRECTION_MISMATCH"
                ),
            }

        clean = (
            poi.get(
                "clean"
            ) is True
            or (
                poi.get(
                    "valid_poi"
                ) is True
            )
        )

        if not clean:

            return {
                "valid": False,
                "reason": (
                    "POI_NOT_CLEAN"
                ),
            }

        unmitigated = (
            poi.get(
                "unmitigated"
            ) is True
            or (
                poi.get(
                    "valid_poi"
                ) is True
            )
        )

        if not unmitigated:

            return {
                "valid": False,
                "reason": (
                    "POI_ALREADY_MITIGATED"
                ),
            }

        if poi.get(
            "invalidated"
        ) is True:

            return {
                "valid": False,
                "reason": (
                    "POI_INVALIDATED"
                ),
            }

        bounds_valid = (
            self._price_inside_zone(
                current_price,
                poi,
            )
        )

        tapped = (
            poi.get(
                "tapped"
            ) is True
            or poi.get(
                "tap_confirmed"
            ) is True
            or (
                bounds_valid
            )
        )

        if require_tap and not tapped:

            return {
                "valid": False,
                "reason": (
                    "PRICE_NOT_TAPPED_POI"
                ),
            }

        if not bounds_valid:

            return {
                "valid": False,
                "reason": (
                    "POI_ZONE_INVALID"
                ),
            }

        return {
            "valid": True,
            "reason": "VALID_POI_TAP",
            "poi": deepcopy(
                poi
            ),
        }

    # =========================================================
    # ENTRY VALIDATION
    # =========================================================

    def _validate_entry(
        self,
        entry_evidence,
        direction,
    ):

        # Adapter-normalized list format.

        if isinstance(
            entry_evidence,
            list,
        ):

            valid_models = []

            for model in (
                entry_evidence
            ):

                model = self._dict(
                    model
                )

                if (
                    model.get(
                        "valid"
                    ) is True
                    and model.get(
                        "invalidated"
                    ) is not True
                    and self._direction(
                        model.get(
                            "direction"
                        )
                    ) == direction
                ):

                    valid_models.append(
                        model.get(
                            "model",
                            model.get(
                                "name",
                                "ENTRY_MODEL",
                            ),
                        )
                    )

            if valid_models:

                return {
                    "valid": True,
                    "models": list(
                        dict.fromkeys(
                            valid_models
                        )
                    ),
                    "reason": (
                        "ENTRY_MODEL_CONFIRMED"
                    ),
                }

            return {
                "valid": False,
                "reason": (
                    "NO_VALID_DIRECTIONAL_ENTRY_MODEL"
                ),
            }

        entry_evidence = self._dict(
            entry_evidence
        )

        confirmed_models = (
            entry_evidence.get(
                "confirmed_models"
            )
        )

        models = self._dict(
            entry_evidence.get(
                "models"
            )
        )

        valid_models = []

        if isinstance(
            confirmed_models,
            list,
        ):

            for name in (
                confirmed_models
            ):

                model = self._dict(
                    models.get(
                        name
                    )
                )

                if (
                    model.get(
                        "confirmed"
                    ) is True
                    and self._direction(
                        model.get(
                            "direction"
                        )
                    ) == direction
                    and model.get(
                        "invalidated"
                    ) is not True
                ):

                    valid_models.append(
                        name
                    )

        if not valid_models:

            for name, model in (
                models.items()
            ):

                model = self._dict(
                    model
                )

                if (
                    model.get(
                        "confirmed"
                    ) is True
                    and self._direction(
                        model.get(
                            "direction"
                        )
                    ) == direction
                    and model.get(
                        "invalidated"
                    ) is not True
                ):

                    valid_models.append(
                        name
                    )

        if (
            entry_evidence.get(
                "confirmed"
            ) is True
            and self._direction(
                entry_evidence.get(
                    "direction"
                )
            ) == direction
        ):

            valid_models.append(
                entry_evidence.get(
                    "model",
                    "ENTRY_CONFIRMED",
                )
            )

        valid_models = list(
            dict.fromkeys(
                valid_models
            )
        )

        if not valid_models:

            return {
                "valid": False,
                "reason": (
                    "NO_VALID_DIRECTIONAL_ENTRY_MODEL"
                ),
            }

        return {
            "valid": True,
            "models": valid_models,
            "reason": (
                "ENTRY_MODEL_CONFIRMED"
            ),
        }

    # =========================================================
    # FVG VALIDATION
    # =========================================================

    def _validate_fvg(
        self,
        evidence,
        direction,
    ):

        evidence = self._dict(
            evidence
        )

        fvg_items = self._list(
            evidence.get(
                "fvg"
            )
        )

        if not fvg_items:

            return {
                "valid": False,
                "reason": (
                    "FVG_EVIDENCE_MISSING"
                ),
            }

        valid_items = []

        for item in (
            fvg_items
        ):

            item = self._dict(
                item
            )

            if (
                item.get(
                    "valid_poi"
                ) is True
                and item.get(
                    "invalidated"
                ) is not True
                and self._direction(
                    item.get(
                        "direction"
                    )
                ) == direction
            ):

                valid_items.append(
                    deepcopy(
                        item
                    )
                )

        if not valid_items:

            return {
                "valid": False,
                "reason": (
                    "NO_VALID_DIRECTIONAL_FVG"
                ),
            }

        return {
            "valid": True,
            "reason": (
                "DIRECTIONAL_FVG_CONFIRMED"
            ),
            "fvg": valid_items,
        }

    # =========================================================
    # DISPLACEMENT VALIDATION
    # =========================================================

    def _validate_displacement(
        self,
        evidence,
        direction,
    ):

        evidence = self._dict(
            evidence
        )

        items = self._list(
            evidence.get(
                "displacement"
            )
        )

        if not items:

            return {
                "valid": False,
                "reason": (
                    "DISPLACEMENT_EVIDENCE_MISSING"
                ),
            }

        valid_items = []

        for item in (
            items
        ):

            item = self._dict(
                item
            )

            if (
                item.get(
                    "valid"
                ) is True
                and self._direction(
                    item.get(
                        "direction"
                    )
                ) == direction
            ):

                valid_items.append(
                    deepcopy(
                        item
                    )
                )

        if not valid_items:

            return {
                "valid": False,
                "reason": (
                    "DIRECTIONAL_DISPLACEMENT_NOT_CONFIRMED"
                ),
            }

        return {
            "valid": True,
            "reason": (
                "DIRECTIONAL_DISPLACEMENT_CONFIRMED"
            ),
            "displacement": valid_items,
        }

    # =========================================================
    # CONFIRMATION EVIDENCE
    # =========================================================

    def _validate_confirmation(
        self,
        adapter_evidence,
        direction,
    ):

        fvg = self._validate_fvg(
            adapter_evidence,
            direction,
        )

        displacement = (
            self._validate_displacement(
                adapter_evidence,
                direction,
            )
        )

        return {
            "valid": (
                fvg["valid"]
                and displacement["valid"]
            ),
            "fvg": fvg,
            "displacement": displacement,
        }

    # =========================================================
    # RISK VALIDATION
    # =========================================================

    @staticmethod
    def _validate_risk(
        risk_checks,
    ):

        risk_checks = (
            SMCEngine._dict(
                risk_checks
            )
        )

        missing = [
            name
            for name in (
                SMCEngine.REQUIRED_RISK_CHECKS
            )
            if risk_checks.get(
                name
            ) is not True
        ]

        return {
            "valid": (
                not missing
            ),
            "missing_or_failed": missing,
            "reason": (
                "RISK_VALIDATION_PASSED"
                if not missing
                else "RISK_CHECKS_FAILED"
            ),
        }

    # =========================================================
    # PATHWAY REJECTION
    # =========================================================

    @staticmethod
    def _pathway_reject(
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
            "evidence": (
                evidence or {}
            ),
        }

    # =========================================================
    # PATHWAY 1: H1 ALIGNED CONTINUATION
    # =========================================================

    def _pathway_continuation(
        self,
        market_data,
        current_price,
        direction,
        poi_evidence,
        entry_evidence,
        confirmation_evidence,
    ):

        h1 = self._tf(
            market_data,
            "H1",
        )

        m5 = self._tf(
            market_data,
            "M5",
        )

        h1_direction = (
            self.determine_h1_direction(
                h1
            )
        )

        if h1_direction != direction:

            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "H1_DIRECTION_NOT_ALIGNED",
            )

        h1_poi = self._dict(
            self._dict(
                poi_evidence
            ).get(
                "H1"
            )
        )

        h1_validation = (
            self._validate_poi(
                h1_poi,
                direction,
                current_price,
                True,
            )
        )

        if not h1_validation["valid"]:

            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                h1_validation["reason"],
            )

        m5_break = (
            self.validate_m5_external_choch(
                m5,
                direction,
            )
        )

        if not m5_break["valid"]:

            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                m5_break["reason"],
            )

        m5_poi = self._dict(
            self._dict(
                poi_evidence
            ).get(
                "M5"
            )
        )

        m5_validation = (
            self._validate_poi(
                m5_poi,
                direction,
                current_price,
                True,
            )
        )

        if not m5_validation["valid"]:

            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "M5_POI_TAP_REQUIRED",
                {
                    "m5_poi": m5_validation,
                },
            )

        confirmation = (
            self._validate_confirmation(
                confirmation_evidence,
                direction,
            )
        )

        if not confirmation["valid"]:

            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                "M5_CONFIRMATION_EVIDENCE_FAILED",
                confirmation,
            )

        entry = (
            self._validate_entry(
                entry_evidence,
                direction,
            )
        )

        if not entry["valid"]:

            return self._pathway_reject(
                "H1_ALIGNED_CONTINUATION",
                direction,
                entry["reason"],
            )

        return {
            "pathway": (
                "H1_ALIGNED_CONTINUATION"
            ),
            "direction": direction,
            "qualified": True,
            "status": (
                "QUALIFIED_PENDING_SCORE"
            ),
            "reason": (
                "CONTINUATION_EVIDENCE_CONFIRMED"
            ),
            "evidence": {
                "h1_direction": h1_direction,
                "h1_poi": h1_validation,
                "m5_external_break": m5_break,
                "m5_poi": m5_validation,
                "confirmation": confirmation,
                "entry": entry,
            },
        }

    # =========================================================
    # PATHWAY 2: H1 COUNTERTREND REVERSAL
    # =========================================================

    def _pathway_h1_countertrend(
        self,
        market_data,
        current_price,
        direction,
        poi_evidence,
        entry_evidence,
        confirmation_evidence,
    ):

        h1 = self._tf(
            market_data,
            "H1",
        )

        m5 = self._tf(
            market_data,
            "M5",
        )

        h1_direction = (
            self.determine_h1_direction(
                h1
            )
        )

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

        m5_break = (
            self.validate_m5_external_choch(
                m5,
                direction,
            )
        )

        if not m5_break["valid"]:

            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "M5_EXTERNAL_REVERSAL_NOT_CONFIRMED",
            )

        m5_poi = self._dict(
            self._dict(
                poi_evidence
            ).get(
                "M5"
            )
        )

        poi_validation = (
            self._validate_poi(
                m5_poi,
                direction,
                current_price,
                True,
            )
        )

        if not poi_validation["valid"]:

            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                poi_validation["reason"],
            )

        confirmation = (
            self._validate_confirmation(
                confirmation_evidence,
                direction,
            )
        )

        if not confirmation["valid"]:

            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                "M5_CONFIRMATION_EVIDENCE_FAILED",
                confirmation,
            )

        entry = (
            self._validate_entry(
                entry_evidence,
                direction,
            )
        )

        if not entry["valid"]:

            return self._pathway_reject(
                "H1_COUNTERTREND_REVERSAL",
                direction,
                entry["reason"],
            )

        return {
            "pathway": (
                "H1_COUNTERTREND_REVERSAL"
            ),
            "direction": direction,
            "qualified": True,
            "status": (
                "QUALIFIED_PENDING_SCORE"
            ),
            "reason": (
                "COUNTERTREND_REVERSAL_CONFIRMED"
            ),
            "evidence": {
                "h1_direction": h1_direction,
                "m5_external_break": m5_break,
                "m5_poi": poi_validation,
                "confirmation": confirmation,
                "entry": entry,
            },
        }

    # =========================================================
    # PATHWAY 3: M5 INTERNAL COUNTERTREND
    # =========================================================

    def _pathway_internal(
        self,
        market_data,
        current_price,
        direction,
        poi_evidence,
        entry_evidence,
        confirmation_evidence,
    ):

        m5 = self._tf(
            market_data,
            "M5",
        )

        external = self._dict(
            m5.get(
                "external_structure"
            )
        )

        internal = self._dict(
            m5.get(
                "internal_structure"
            )
        )

        external_direction = (
            self._direction(
                external.get(
                    "direction"
                )
                or external.get(
                    "bias"
                )
            )
        )

        internal_direction = (
            self._direction(
                internal.get(
                    "direction"
                )
                or internal.get(
                    "bias"
                )
            )
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

        internal_break = (
            self._find_break(
                internal,
                direction,
            )
        )

        if internal_break is None:

            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "INTERNAL_BODY_CLOSE_BREAK_MISSING",
            )

        internal_poi = self._dict(
            self._dict(
                poi_evidence
            ).get(
                "M5_INTERNAL"
            )
        )

        poi_validation = (
            self._validate_poi(
                internal_poi,
                direction,
                current_price,
                True,
            )
        )

        if not poi_validation["valid"]:

            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                poi_validation["reason"],
            )

        confirmation = (
            self._validate_confirmation(
                confirmation_evidence,
                direction,
            )
        )

        if not confirmation["valid"]:

            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                "M5_CONFIRMATION_EVIDENCE_FAILED",
                confirmation,
            )

        entry = (
            self._validate_entry(
                entry_evidence,
                direction,
            )
        )

        if not entry["valid"]:

            return self._pathway_reject(
                "M5_INTERNAL_COUNTERTREND",
                direction,
                entry["reason"],
            )

        return {
            "pathway": (
                "M5_INTERNAL_COUNTERTREND"
            ),
            "direction": direction,
            "qualified": True,
            "status": (
                "QUALIFIED_PENDING_SCORE"
            ),
            "reason": (
                "INTERNAL_COUNTERTREND_CONFIRMED"
            ),
            "evidence": {
                "external_direction": external_direction,
                "internal_direction": internal_direction,
                "internal_break": internal_break,
                "internal_poi": poi_validation,
                "confirmation": confirmation,
                "entry": entry,
            },
        }

    # =========================================================
    # PATHWAY 4: RANGING MARKET
    # =========================================================

    def _pathway_range(
        self,
        market_data,
        current_price,
        direction,
        poi_evidence,
        entry_evidence,
        confirmation_evidence,
    ):

        h1 = self._tf(
            market_data,
            "H1",
        )

        h1_direction = (
            self.determine_h1_direction(
                h1
            )
        )

        range_data = self._dict(
            h1.get(
                "range"
            )
        )

        if not range_data:

            range_data = self._dict(
                h1.get(
                    "premium_discount"
                )
            )

        range_high = self._number(
            range_data.get(
                "range_high",
                range_data.get(
                    "high"
                ),
            )
        )

        range_low = self._number(
            range_data.get(
                "range_low",
                range_data.get(
                    "low"
                ),
            )
        )

        if (
            range_high is None
            or range_low is None
        ):

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
            range_low
            <= current_price
            <= range_high
        ):

            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                "PRICE_OUTSIDE_RANGE",
            )

        equilibrium = (
            range_high
            + range_low
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
            self._dict(
                poi_evidence
            ).get(
                "RANGE"
            )
        )

        poi_validation = (
            self._validate_poi(
                range_poi,
                direction,
                current_price,
                True,
            )
        )

        if not poi_validation["valid"]:

            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                poi_validation["reason"],
            )

        confirmation = (
            self._validate_confirmation(
                confirmation_evidence,
                direction,
            )
        )

        if not confirmation["valid"]:

            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                "RANGE_CONFIRMATION_EVIDENCE_FAILED",
                confirmation,
            )

        entry = (
            self._validate_entry(
                entry_evidence,
                direction,
            )
        )

        if not entry["valid"]:

            return self._pathway_reject(
                "RANGING_MARKET",
                direction,
                entry["reason"],
            )

        return {
            "pathway": (
                "RANGING_MARKET"
            ),
            "direction": direction,
            "qualified": True,
            "status": (
                "QUALIFIED_PENDING_SCORE"
            ),
            "reason": (
                "RANGE_SETUP_CONFIRMED"
            ),
            "evidence": {
                "range_high": range_high,
                "range_low": range_low,
                "equilibrium": equilibrium,
                "h1_direction": h1_direction,
                "poi": poi_validation,
                "confirmation": confirmation,
                "entry": entry,
            },
        }

    # =========================================================
    # PATHWAY SCORING
    # =========================================================

    def _pathway_scores(
        self,
        category_scores,
        pathway_name,
    ):

        scores = self._dict(
            category_scores
        )

        if pathway_name in scores:

            return self._dict(
                scores.get(
                    pathway_name
                )
            )

        return scores

    # =========================================================
    # COMPLETE PATHWAY EVALUATION
    # =========================================================

    def _evaluate_pathway(
        self,
        pathway_result,
        category_scores,
        risk_checks,
        fundamentals,
    ):

        if not pathway_result.get(
            "qualified"
        ):

            return pathway_result

        name = pathway_result.get(
            "pathway"
        )

        scores = (
            self._pathway_scores(
                category_scores,
                name,
            )
        )

        if (
            "fundamentals" not in scores
            and fundamentals.get(
                "score"
            ) is not None
        ):

            scores = dict(
                scores
            )

            scores["fundamentals"] = (
                fundamentals.get(
                    "score"
                )
            )

        scoring = (
            self.calculate_a_plus_score(
                scores
            )
        )

        risk = (
            self._validate_risk(
                risk_checks
            )
        )

        result = deepcopy(
            pathway_result
        )

        result["scoring"] = scoring
        result["risk"] = risk

        result["execution_authorized"] = False

        if not scoring["complete"]:

            result["status"] = (
                "INCOMPLETE_SCORE"
            )

            result["a_plus"] = False

            result["reason"] = (
                "CATEGORY_SCORES_INCOMPLETE"
            )

            return result

        if (
            scoring["score"]
            < self.A_PLUS_THRESHOLD
        ):

            result["status"] = (
                "BELOW_A_PLUS_THRESHOLD"
            )

            result["a_plus"] = False

            result["reason"] = (
                "SCORE_BELOW_85"
            )

            return result

        if not risk["valid"]:

            result["status"] = (
                "RISK_REJECTED"
            )

            result["a_plus"] = True

            result["reason"] = (
                "RISK_VALIDATION_FAILED"
            )

            return result

        result["status"] = (
            "A_PLUS_SETUP"
        )

        result["a_plus"] = True

        result["reason"] = (
            "A_PLUS_SETUP_QUALIFIED"
        )

        # Authorization deliberately remains
        # downstream.

        result["execution_authorized"] = False

        return result

    # =========================================================
    # MASTER ANALYSIS
    # =========================================================

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

        market_data = self._dict(
            market_data
        )

        current_price = self._number(
            current_price
        )

        entry_evidence = (
            entry_evidence
        )

        poi_evidence = self._dict(
            poi_evidence
        )

        displacement_evidence = (
            displacement_evidence
        )

        fvg_evidence = (
            fvg_evidence
        )

        risk_checks = self._dict(
            risk_checks
        )

        category_scores = (
            self._dict(
                category_scores
            )
        )

        fundamentals = (
            self._dict(
                fundamentals
            )
        )

        h1 = self._tf(
            market_data,
            "H1",
        )

        h1_direction = (
            self.determine_h1_direction(
                h1
            )
        )

        # -----------------------------------------------------
        # CONNECT ADAPTER
        # -----------------------------------------------------

        adapter_results = {}

        for direction in (
            self.DIRECTIONS
        ):

            adapter_results[
                direction
            ] = (
                self._build_adapter_evidence(
                    direction=direction,
                    market_data=market_data,
                    current_price=current_price,
                    entry_evidence=entry_evidence,
                    poi_evidence=poi_evidence,
                    displacement_evidence=(
                        displacement_evidence
                    ),
                    fvg_evidence=fvg_evidence,
                    risk_checks=risk_checks,
                )
            )

        pathways = {}

        # -----------------------------------------------------
        # EVALUATE ALL FOUR PATHWAYS
        # INDEPENDENTLY FOR BOTH DIRECTIONS
        # -----------------------------------------------------

        for direction in (
            self.DIRECTIONS
        ):

            adapter_result = (
                adapter_results.get(
                    direction,
                    {},
                )
            )

            normalized = (
                self._dict(
                    adapter_result.get(
                        "evidence"
                    )
                )
            )

            adapter_available = (
                adapter_result.get(
                    "available"
                ) is True
            )

            # No fabricated evidence.
            # If adapter fails, pathway confirmation
            # evidence remains unavailable and pathways
            # fail closed.

            continuation = (
                self._pathway_continuation(
                    market_data,
                    current_price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    normalized,
                )
            )

            countertrend = (
                self._pathway_h1_countertrend(
                    market_data,
                    current_price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    normalized,
                )
            )

            internal = (
                self._pathway_internal(
                    market_data,
                    current_price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    normalized,
                )
            )

            ranging = (
                self._pathway_range(
                    market_data,
                    current_price,
                    direction,
                    poi_evidence,
                    entry_evidence,
                    normalized,
                )
            )

            for pathway in (
                continuation,
                countertrend,
                internal,
                ranging,
            ):

                pathway = (
                    self._evaluate_pathway(
                        pathway,
                        category_scores,
                        risk_checks,
                        fundamentals,
                    )
                )

                pathway_key = (
                    pathway["pathway"]
                    + "_"
                    + direction
                )

                pathways[
                    pathway_key
                ] = pathway

        # -----------------------------------------------------
        # QUALIFIED SETUPS
        # -----------------------------------------------------

        qualified = [
            result
            for result in pathways.values()
            if (
                result.get(
                    "status"
                ) == "A_PLUS_SETUP"
                and result.get(
                    "a_plus"
                ) is True
            )
        ]

        # Keep every qualified setup.
        # Do not discard simultaneous pathways.

        best = None

        if qualified:

            best = max(
                qualified,
                key=lambda item: (
                    item.get(
                        "scoring",
                        {},
                    ).get(
                        "score",
                        0,
                    )
                ),
            )

        if best:

            overall_status = (
                "A_PLUS_SETUP"
            )

        elif any(
            item.get(
                "status"
            ) == "INCOMPLETE_SCORE"
            for item in pathways.values()
        ):

            overall_status = (
                "INCOMPLETE_EVIDENCE"
            )

        else:

            overall_status = (
                "NO_CONFIRMED_SETUP"
            )

        # -----------------------------------------------------
        # RESULT
        # -----------------------------------------------------

        result = {
            "success": True,

            "version": self.VERSION,

            "status": overall_status,

            "symbol": (
                market_data.get(
                    "symbol"
                )
            ),

            "current_price": (
                current_price
            ),

            "h1_direction": (
                h1_direction
            ),

            "adapter": {
                "available": (
                    self.adapter
                    is not None
                ),

                "connected": (
                    all(
                        item.get(
                            "available"
                        ) is True
                        for item in (
                            adapter_results.values()
                        )
                    )
                ),

                "errors": (
                    self.adapter_errors
                ),

                "evidence": (
                    adapter_results
                ),
            },

            "pathways": (
                pathways
            ),

            "qualified_pathways": (
                qualified
            ),

            "qualified_pathway_count": (
                len(qualified)
            ),

            "best_setup": (
                deepcopy(best)
            ),

            "direction": (
                best.get(
                    "direction"
                )
                if best
                else None
            ),

            "pathway": (
                best.get(
                    "pathway"
                )
                if best
                else None
            ),

            "a_plus": (
                best.get(
                    "a_plus",
                    False,
                )
                if best
                else False
            ),

            "score": (
                best.get(
                    "scoring",
                    {},
                ).get(
                    "score"
                )
                if best
                else None
            ),

            "execution_authorized": False,

            "evidence_only": True,

            "trade_authorization_pending": (
                bool(best)
            ),

            "reason": (
                "A_PLUS_SETUP_QUALIFIED"
                if best
                else overall_status
            ),
        }

        self.last_analysis = (
            deepcopy(
                result
            )
        )

        return result

    # =========================================================
    # REJECTION COMPATIBILITY
    # =========================================================

    def _reject(
        self,
        reason,
        **kwargs,
    ):

        result = {
            "success": False,
            "version": self.VERSION,
            "status": "REJECTED",
            "a_plus": False,
            "execution_authorized": False,
            "reason": reason,
        }

        result.update(
            kwargs
        )

        self.last_analysis = (
            deepcopy(
                result
            )
        )

        return result

    # =========================================================
    # STATUS
    # =========================================================

    def get_status(self):

        return {
            "version": self.VERSION,

            "threshold": (
                self.A_PLUS_THRESHOLD
            ),

            "pathways": (
                list(
                    self.PATHWAYS
                )
            ),

            "adapter_connected": (
                self.adapter
                is not None
            ),

            "adapter_errors": (
                self.adapter_errors
            ),

            "last_analysis_status": (
                self.last_analysis.get(
                    "status"
                )
                if self.last_analysis
                else "NOT_ANALYZED"
            ),
        }

    def get_last_analysis(self):

        return deepcopy(
            self.last_analysis
        )


# =============================================================
# SHARED ENGINE INSTANCE
# =============================================================

smc_engine = SMCEngine()
