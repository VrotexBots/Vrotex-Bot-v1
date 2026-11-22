"""
Vrotex Bot V1
SMC Integration Adapter
Version: 4.1

Purpose:
    Normalize evidence from TA, structure, liquidity,
    OB, FVG, displacement, and entry-model engines.

    Preserve the four approved SMC pathways.

    Strict body-close validation.
    Strict external CHoCH validation.
    Strict entry retest validation.
    Risk validation.

    Execution integration readiness.
    No broker order placement in this adapter.
"""

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional


logger = logging.getLogger("vrotex.smc_adapter")


class SMCIntegrationAdapter:

    VERSION = "4.1"

    DIRECTIONS = (
        "BULLISH",
        "BEARISH",
        "RANGING",
        "UNKNOWN",
    )

    REQUIRED_RISK_CHECKS = (
        "spread_valid",
        "stop_loss_valid",
        "risk_within_limit",
        "daily_limit_valid",
        "consecutive_loss_limit_valid",
        "reward_risk_valid",
    )

    def __init__(self):
        self.last_evidence = {}

    # =========================================================
    # GENERAL NORMALIZATION
    # =========================================================

    @staticmethod
    def _dict(value):
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _list(value):

        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        if isinstance(value, dict):
            return [value]

        return []

    @staticmethod
    def _bool(value):
        return value is True

    @staticmethod
    def _number(value):

        try:
            if value is None:
                return None

            return float(value)

        except (ValueError, TypeError):
            return None

    @staticmethod
    def _direction(value):

        if not value:
            return "UNKNOWN"

        value = str(value).upper().strip()

        aliases = {
            "BUY": "BULLISH",
            "LONG": "BULLISH",
            "UP": "BULLISH",
            "BULL": "BULLISH",
            "BULLISH_FVG": "BULLISH",
            "BULLISH_GAP": "BULLISH",

            "SELL": "BEARISH",
            "SHORT": "BEARISH",
            "DOWN": "BEARISH",
            "BEAR": "BEARISH",
            "BEARISH_FVG": "BEARISH",
            "BEARISH_GAP": "BEARISH",

            "SIDEWAYS": "RANGING",
            "RANGE": "RANGING",
            "NEUTRAL": "RANGING",
        }

        value = aliases.get(value, value)

        if value in (
            "BULLISH",
            "BEARISH",
            "RANGING",
        ):
            return value

        return "UNKNOWN"

    @staticmethod
    def _event_type(event):

        event = SMCIntegrationAdapter._dict(event)

        value = event.get(
            "type",
            event.get(
                "event",
                event.get(
                    "break_type",
                    "",
                ),
            ),
        )

        value = str(value).upper().strip()

        aliases = {
            "CHANGE_OF_CHARACTER": "CHOCH",
            "CHANGE CHARACTER": "CHOCH",
            "CHoCH": "CHOCH",
            "BREAK_OF_STRUCTURE": "BOS",
            "BREAK STRUCTURE": "BOS",
        }

        return aliases.get(value, value)

    @staticmethod
    def _body_close_confirmed(event):

        event = SMCIntegrationAdapter._dict(event)

        confirmation = str(
            event.get(
                "confirmation",
                "",
            )
        ).upper().strip()

        # STRICT:
        # Generic confirmed=True is NOT sufficient.
        # Wick-only breaks must never qualify.

        return (
            event.get(
                "body_close_confirmed"
            ) is True

            or event.get(
                "body_close"
            ) is True

            or event.get(
                "close_confirmed"
            ) is True

            or confirmation == "BODY_CLOSE"
        )

    @staticmethod
    def _extract_items(value, keys=None):

        if isinstance(value, (list, tuple)):
            return list(value)

        if isinstance(value, dict):

            if keys:

                for key in keys:

                    candidate = value.get(key)

                    if isinstance(
                        candidate,
                        (list, tuple),
                    ):
                        return list(candidate)

            return [value]

        return []

    @staticmethod
    def _deepcopy(value):

        try:
            return deepcopy(value)

        except Exception:
            return value

    # =========================================================
    # STRUCTURE NORMALIZATION
    # =========================================================

    def _normalize_breaks(
        self,
        breaks,
        timeframe=None,
        structure_type=None,
    ):

        normalized = []

        for event in self._list(breaks):

            if not isinstance(event, dict):
                continue

            event_type = self._event_type(event)

            direction = self._direction(
                event.get(
                    "direction",
                    event.get(
                        "bias",
                    ),
                )
            )

            body_close = (
                self._body_close_confirmed(
                    event
                )
            )

            normalized_event = {
                **event,
                "type": event_type,
                "direction": direction,
                "body_close_confirmed": (
                    body_close
                ),
                "close_confirmed": (
                    body_close
                ),
                "timeframe": (
                    event.get(
                        "timeframe",
                        timeframe,
                    )
                ),
            }

            if structure_type:
                normalized_event[
                    "structure_type"
                ] = structure_type

            normalized.append(
                normalized_event
            )

        return normalized

    def normalize_structure(
        self,
        structure,
        timeframe=None,
    ):

        structure = self._dict(structure)

        original = self._deepcopy(
            structure
        )

        # Support TA output wrapped in technical.
        if isinstance(
            structure.get("technical"),
            dict,
        ):

            structure = structure[
                "technical"
            ]

        nested = structure.get(
            "structure",
            {},
        )

        if isinstance(nested, dict):
            source = nested

        else:
            source = structure

        direction = self._direction(
            source.get(
                "direction",
                source.get(
                    "bias",
                    source.get(
                        "trend",
                        source.get(
                            "structure_bias",
                        ),
                    ),
                ),
            )
        )

        breaks = self._normalize_breaks(
            source.get(
                "breaks",
                structure.get(
                    "breaks",
                    [],
                ),
            ),
            timeframe=timeframe,
        )

        external = self._dict(
            source.get(
                "external_structure",
            )
        )

        internal = self._dict(
            source.get(
                "internal_structure",
            )
        )

        external_breaks = (
            self._normalize_breaks(
                external.get(
                    "breaks",
                    [],
                ),
                timeframe=timeframe,
                structure_type="EXTERNAL",
            )
        )

        internal_breaks = (
            self._normalize_breaks(
                internal.get(
                    "breaks",
                    [],
                ),
                timeframe=timeframe,
                structure_type="INTERNAL",
            )
        )

        normalized_external = {
            **external,
            "breaks": external_breaks,
        }

        normalized_internal = {
            **internal,
            "breaks": internal_breaks,
            "direction": self._direction(
                internal.get(
                    "direction",
                    internal.get(
                        "bias",
                    ),
                )
            ),
        }

        return {
            "timeframe": timeframe,
            "direction": direction,
            "bias": direction,
            "breaks": breaks,
            "external_structure": (
                normalized_external
            ),
            "internal_structure": (
                normalized_internal
            ),
            "swing_highs": self._list(
                source.get(
                    "swing_highs",
                    structure.get(
                        "swing_highs",
                    ),
                )
            ),
            "swing_lows": self._list(
                source.get(
                    "swing_lows",
                    structure.get(
                        "swing_lows",
                    ),
                )
            ),
            "raw": original,
        }

    # =========================================================
    # BREAK VALIDATION
    # =========================================================

    def validate_break(
        self,
        event,
        expected_direction=None,
        required_type=None,
    ):

        event = self._dict(event)

        direction = self._direction(
            event.get(
                "direction",
                event.get(
                    "bias",
                ),
            )
        )

        event_type = self._event_type(
            event
        )

        body_close = (
            self._body_close_confirmed(
                event
            )
        )

        direction_valid = True

        if expected_direction:

            direction_valid = (
                direction
                == self._direction(
                    expected_direction
                )
            )

        type_valid = True

        if required_type:

            type_valid = (
                event_type
                == self._event_type(
                    {
                        "type": required_type
                    }
                )
            )

        valid = (
            body_close
            and direction_valid
            and type_valid
        )

        return {
            "valid": valid,
            "direction": direction,
            "event_type": event_type,
            "body_close_confirmed": (
                body_close
            ),
            "direction_valid": (
                direction_valid
            ),
            "type_valid": type_valid,
            "event": self._deepcopy(
                event
            ),
        }

    # =========================================================
    # EXTERNAL CHOCH
    # =========================================================

    def validate_m5_external_choch(
        self,
        m5_structure,
        expected_direction,
    ):

        structure = self._dict(
            m5_structure
        )

        external = self._dict(
            structure.get(
                "external_structure",
            )
        )

        # IMPORTANT:
        # No fallback to unclassified structure breaks.
        # Only breaks explicitly belonging to the
        # external structure may qualify.

        events = self._list(
            external.get(
                "breaks",
                [],
            )
        )

        expected_direction = (
            self._direction(
                expected_direction
            )
        )

        for event in events:

            result = self.validate_break(
                event,
                expected_direction=(
                    expected_direction
                ),
                required_type="CHOCH",
            )

            if result["valid"]:

                return {
                    "confirmed": True,
                    "direction": (
                        expected_direction
                    ),
                    "event": (
                        result["event"]
                    ),
                    "body_close_confirmed": (
                        True
                    ),
                    "structure_type": (
                        "EXTERNAL"
                    ),
                }

        return {
            "confirmed": False,
            "direction": (
                expected_direction
            ),
            "body_close_confirmed": (
                False
            ),
            "structure_type": (
                "EXTERNAL"
            ),
            "reason": (
                "No qualifying external "
                "CHoCH body-close found"
            ),
        }

    # =========================================================
    # INTERNAL STRUCTURE
    # =========================================================

    def normalize_internal_structure(
        self,
        structure,
    ):

        structure = self._dict(
            structure
        )

        internal = self._dict(
            structure.get(
                "internal_structure",
            )
        )

        if not internal:

            return {
                "available": False,
                "direction": "UNKNOWN",
                "breaks": [],
                "validated_breaks": [],
            }

        direction = self._direction(
            internal.get(
                "direction",
                internal.get(
                    "bias",
                ),
            )
        )

        breaks = self._list(
            internal.get(
                "breaks",
                [],
            )
        )

        validated = []

        for event in breaks:

            validated.append(
                self.validate_break(
                    event,
                )
            )

        return {
            "available": True,
            "direction": direction,
            "breaks": breaks,
            "validated_breaks": (
                validated
            ),
            "raw": self._deepcopy(
                internal
            ),
        }

    # =========================================================
    # LIQUIDITY
    # =========================================================

    def normalize_liquidity(
        self,
        liquidity,
    ):

        liquidity = self._dict(
            liquidity
        )

        sweeps = self._extract_items(
            liquidity.get(
                "sweeps",
                liquidity.get(
                    "liquidity_sweeps",
                ),
            ),
            keys=(
                "sweeps",
                "liquidity_sweeps",
            ),
        )

        equal_highs = self._extract_items(
            liquidity.get(
                "equal_highs",
                liquidity.get(
                    "eqh",
                ),
            ),
            keys=(
                "equal_highs",
                "eqh",
            ),
        )

        equal_lows = self._extract_items(
            liquidity.get(
                "equal_lows",
                liquidity.get(
                    "eql",
                ),
            ),
            keys=(
                "equal_lows",
                "eql",
            ),
        )

        normalized_sweeps = []

        for sweep in sweeps:

            if not isinstance(
                sweep,
                dict,
            ):
                continue

            direction = self._direction(
                sweep.get(
                    "direction",
                )
            )

            sweep_type = str(
                sweep.get(
                    "type",
                    sweep.get(
                        "sweep_type",
                        "",
                    ),
                )
            ).upper().strip()

            close_back_inside = (
                sweep.get(
                    "close_back_inside",
                ) is True

                or sweep.get(
                    "reclaimed",
                ) is True
            )

            normalized_sweeps.append(
                {
                    **sweep,
                    "direction": direction,
                    "type": sweep_type,
                    "close_back_inside": (
                        close_back_inside
                    ),
                    "valid": (
                        direction
                        in (
                            "BULLISH",
                            "BEARISH",
                        )
                        and bool(sweep_type)
                    ),
                }
            )

        return {
            "sweeps": (
                normalized_sweeps
            ),
            "equal_highs": (
                equal_highs
            ),
            "equal_lows": (
                equal_lows
            ),
            "raw": self._deepcopy(
                liquidity
            ),
        }

    # =========================================================
    # FVG
    # =========================================================

    def normalize_fvg(
        self,
        fvg,
        expected_direction=None,
    ):

        items = self._extract_items(
            fvg,
            keys=(
                "fvg",
                "fvgs",
                "gaps",
                "fair_value_gaps",
            ),
        )

        normalized = []

        for item in items:

            if not isinstance(
                item,
                dict,
            ):
                continue

            direction = self._direction(
                item.get(
                    "direction",
                    item.get(
                        "type",
                    ),
                )
            )

            clean = (
                item.get(
                    "clean",
                ) is True

                or item.get(
                    "unmitigated",
                ) is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                ) is True
            )

            lower = self._number(
                item.get(
                    "lower",
                    item.get(
                        "bottom",
                        item.get(
                            "low",
                        ),
                    ),
                )
            )

            upper = self._number(
                item.get(
                    "upper",
                    item.get(
                        "top",
                        item.get(
                            "high",
                        ),
                    ),
                )
            )

            direction_valid = True

            if expected_direction:

                direction_valid = (
                    direction
                    == self._direction(
                        expected_direction
                    )
                )

            bounds_valid = (
                lower is not None
                and upper is not None
                and lower < upper
            )

            valid = (
                direction
                in (
                    "BULLISH",
                    "BEARISH",
                )
                and clean
                and not invalidated
                and bounds_valid
                and direction_valid
            )

            normalized.append(
                {
                    **item,
                    "direction": direction,
                    "lower": lower,
                    "upper": upper,
                    "clean": clean,
                    "invalidated": (
                        invalidated
                    ),
                    "bounds_valid": (
                        bounds_valid
                    ),
                    "direction_valid": (
                        direction_valid
                    ),
                    "valid_poi": valid,
                }
            )

        return normalized

    # =========================================================
    # POI
    # =========================================================

    def normalize_poi(
        self,
        poi,
        expected_direction=None,
        current_price=None,
    ):

        items = self._extract_items(
            poi,
            keys=(
                "poi",
                "pois",
                "order_blocks",
                "obs",
                "blocks",
            ),
        )

        normalized = []

        current_price = self._number(
            current_price
        )

        for item in items:

            if not isinstance(
                item,
                dict,
            ):
                continue

            direction = self._direction(
                item.get(
                    "direction",
                    item.get(
                        "bias",
                        item.get(
                            "type",
                        ),
                    ),
                )
            )

            lower = self._number(
                item.get(
                    "lower",
                    item.get(
                        "bottom",
                        item.get(
                            "low",
                        ),
                    ),
                )
            )

            upper = self._number(
                item.get(
                    "upper",
                    item.get(
                        "top",
                        item.get(
                            "high",
                        ),
                    ),
                )
            )

            clean = (
                item.get(
                    "clean",
                ) is True

                or item.get(
                    "unmitigated",
                ) is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                ) is True
            )

            bounds_valid = (
                lower is not None
                and upper is not None
                and lower < upper
            )

            direction_valid = True

            if expected_direction:

                direction_valid = (
                    direction
                    == self._direction(
                        expected_direction
                    )
                )

            tapped = (
                item.get(
                    "tapped",
                ) is True

                or item.get(
                    "tap_confirmed",
                ) is True
            )

            if (
                not tapped
                and bounds_valid
                and current_price is not None
            ):

                tapped = (
                    lower
                    <= current_price
                    <= upper
                )

            valid_poi = (
                direction
                in (
                    "BULLISH",
                    "BEARISH",
                )
                and clean
                and not invalidated
                and bounds_valid
                and direction_valid
            )

            normalized.append(
                {
                    **item,
                    "direction": direction,
                    "lower": lower,
                    "upper": upper,
                    "clean": clean,
                    "invalidated": (
                        invalidated
                    ),
                    "bounds_valid": (
                        bounds_valid
                    ),
                    "direction_valid": (
                        direction_valid
                    ),
                    "tapped": tapped,
                    "valid_poi": (
                        valid_poi
                    ),
                    "valid_poi_tapped": (
                        valid_poi
                        and tapped
                    ),
                }
            )

        return normalized

    # =========================================================
    # DISPLACEMENT
    # =========================================================

    def normalize_displacement(
        self,
        displacement,
        expected_direction=None,
    ):

        items = self._extract_items(
            displacement,
            keys=(
                "displacement",
                "displacements",
                "events",
            ),
        )

        normalized = []

        for item in items:

            if not isinstance(
                item,
                dict,
            ):
                continue

            direction = self._direction(
                item.get(
                    "direction",
                )
            )

            confirmed = (
                item.get(
                    "confirmed",
                ) is True

                or item.get(
                    "displacement_confirmed",
                ) is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                ) is True
            )

            direction_valid = True

            if expected_direction:

                direction_valid = (
                    direction
                    == self._direction(
                        expected_direction
                    )
                )

            valid = (
                confirmed
                and not invalidated
                and direction_valid
                and direction
                in (
                    "BULLISH",
                    "BEARISH",
                )
            )

            normalized.append(
                {
                    **item,
                    "direction": direction,
                    "confirmed": confirmed,
                    "invalidated": (
                        invalidated
                    ),
                    "direction_valid": (
                        direction_valid
                    ),
                    "valid": valid,
                }
            )

        return normalized

    # =========================================================
    # ENTRY MODELS
    # =========================================================

    def normalize_entry_models(
        self,
        entry_models,
        expected_direction=None,
    ):

        items = self._extract_items(
            entry_models,
            keys=(
                "entry_models",
                "models",
                "entries",
                "signals",
            ),
        )

        normalized = []

        for item in items:

            if not isinstance(
                item,
                dict,
            ):
                continue

            direction = self._direction(
                item.get(
                    "direction",
                )
            )

            confirmed = (
                item.get(
                    "confirmed",
                ) is True

                or item.get(
                    "model_confirmed",
                ) is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                ) is True
            )

            retest_confirmed = (
                item.get(
                    "retest_confirmed",
                ) is True

                or item.get(
                    "retest",
                ) is True
            )

            direction_valid = True

            if expected_direction:

                direction_valid = (
                    direction
                    == self._direction(
                        expected_direction
                    )
                )

            # Approved entry confirmation:
            # Model confirmation + retest +
            # valid direction + not invalidated.

            valid = (
                confirmed
                and retest_confirmed
                and not invalidated
                and direction_valid
                and direction
                in (
                    "BULLISH",
                    "BEARISH",
                )
            )

            normalized.append(
                {
                    **item,
                    "direction": direction,
                    "confirmed": confirmed,
                    "invalidated": (
                        invalidated
                    ),
                    "retest_confirmed": (
                        retest_confirmed
                    ),
                    "direction_valid": (
                        direction_valid
                    ),
                    "valid": valid,
                }
            )

        return normalized

    # =========================================================
    # RISK CHECKS
    # =========================================================

    def normalize_risk_checks(
        self,
        risk_checks,
    ):

        risk_checks = self._dict(
            risk_checks
        )

        normalized = {}

        for key in self.REQUIRED_RISK_CHECKS:

            normalized[key] = (
                risk_checks.get(key)
                is True
            )

        missing = [
            key
            for key in self.REQUIRED_RISK_CHECKS
            if key not in risk_checks
        ]

        passed = (
            all(
                normalized.values()
            )
            and not missing
        )

        return {
            "checks": normalized,
            "missing": missing,
            "passed": passed,
            "raw": self._deepcopy(
                risk_checks
            ),
        }

    # =========================================================
    # MASTER EVIDENCE BUILDER
    # =========================================================

    def build_evidence(
        self,
        trade_direction,
        h1_structure,
        m5_structure,
        m1_structure,
        liquidity,
        fvg,
        poi,
        displacement,
        entry_models,
        risk_checks,
        current_price=None,
    ):

        trade_direction = (
            self._direction(
                trade_direction
            )
        )

        h1 = self.normalize_structure(
            h1_structure,
            "H1",
        )

        m5 = self.normalize_structure(
            m5_structure,
            "M5",
        )

        m1 = self.normalize_structure(
            m1_structure,
            "M1",
        )

        liquidity_data = (
            self.normalize_liquidity(
                liquidity
            )
        )

        fvg_data = (
            self.normalize_fvg(
                fvg,
                expected_direction=(
                    trade_direction
                ),
            )
        )

        poi_data = (
            self.normalize_poi(
                poi,
                expected_direction=(
                    trade_direction
                ),
                current_price=current_price,
            )
        )

        displacement_data = (
            self.normalize_displacement(
                displacement,
                expected_direction=(
                    trade_direction
                ),
            )
        )

        entry_data = (
            self.normalize_entry_models(
                entry_models,
                expected_direction=(
                    trade_direction
                ),
            )
        )

        risk_data = (
            self.normalize_risk_checks(
                risk_checks
            )
        )

        m5_choch = (
            self.validate_m5_external_choch(
                m5,
                trade_direction,
            )
        )

        internal = (
            self.normalize_internal_structure(
                m5
            )
        )

        valid_fvg = any(
            item.get(
                "valid_poi",
                False,
            )
            for item in fvg_data
        )

        valid_poi = any(
            item.get(
                "valid_poi",
                False,
            )
            for item in poi_data
        )

        valid_tapped_poi = any(
            item.get(
                "valid_poi_tapped",
                False,
            )
            for item in poi_data
        )

        displacement_confirmed = any(
            item.get(
                "valid",
                False,
            )
            for item in displacement_data
        )

        entry_model_confirmed = any(
            item.get(
                "valid",
                False,
            )
            for item in entry_data
        )

        evidence = {
            "version": self.VERSION,

            "direction": (
                trade_direction
            ),

            "structure": {
                "H1": h1,
                "M5": m5,
                "M1": m1,
            },

            "h1_direction": (
                h1["direction"]
            ),

            "m5_direction": (
                m5["direction"]
            ),

            "m1_direction": (
                m1["direction"]
            ),

            "m5_external_choch": (
                m5_choch
            ),

            "m5_internal_structure": (
                internal
            ),

            "liquidity": (
                liquidity_data
            ),

            "fvg": (
                fvg_data
            ),

            "poi": (
                poi_data
            ),

            "displacement": (
                displacement_data
            ),

            "entry_models": (
                entry_data
            ),

            "risk": (
                risk_data
            ),

            "current_price": (
                current_price
            ),

            "evidence_summary": {
                "h1_structure_available": (
                    h1["direction"]
                    != "UNKNOWN"
                ),

                "m5_structure_available": (
                    m5["direction"]
                    != "UNKNOWN"
                ),

                "m1_structure_available": (
                    m1["direction"]
                    != "UNKNOWN"
                ),

                "m5_external_choch_confirmed": (
                    m5_choch["confirmed"]
                ),

                "internal_structure_available": (
                    internal["available"]
                ),

                "liquidity_available": (
                    bool(
                        liquidity_data[
                            "sweeps"
                        ]
                    )
                ),

                "valid_fvg_available": (
                    valid_fvg
                ),

                "valid_poi_available": (
                    valid_poi
                ),

                "valid_tapped_poi_available": (
                    valid_tapped_poi
                ),

                "displacement_confirmed": (
                    displacement_confirmed
                ),

                "entry_model_confirmed": (
                    entry_model_confirmed
                ),

                "risk_checks_passed": (
                    risk_data["passed"]
                ),
            },

            # This adapter produces evidence.
            # Final execution authorization belongs
            # to the master decision/risk/execution pipeline.

            "execution_ready": (
                risk_data["passed"]
                and valid_tapped_poi
                and displacement_confirmed
                and entry_model_confirmed
                and trade_direction
                in (
                    "BULLISH",
                    "BEARISH",
                )
            ),

            "execution_authorized": False,
        }

        self.last_evidence = (
            self._deepcopy(
                evidence
            )
        )

        return evidence

    # =========================================================
    # STATUS
    # =========================================================

    def get_status(self):

        return {
            "version": self.VERSION,
            "status": "READY",
            "execution_authorized": False,
            "last_evidence": (
                self._deepcopy(
                    self.last_evidence
                )
            ),
        }

    def get_last_evidence(self):

        return self._deepcopy(
            self.last_evidence
        )


# =============================================================
# SINGLETON
# =============================================================

smc_integration_adapter = (
    SMCIntegrationAdapter()
)
