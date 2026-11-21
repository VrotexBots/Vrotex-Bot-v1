"""
Vrotex Bot V1
SMC Integration Adapter
Version: 4.0

Purpose:
    Normalize evidence from TA, structure, liquidity,
    OB, FVG, displacement, and entry-model engines.

    Preserve the four approved SMC pathways.

    Evidence only. No order execution.
"""

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional


logger = logging.getLogger("vrotex.smc_adapter")


class SMCIntegrationAdapter:

    VERSION = "4.0"

    DIRECTIONS = (
        "BULLISH",
        "BEARISH",
        "RANGING",
        "UNKNOWN",
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
    def _direction(value):

        if not value:
            return "UNKNOWN"

        value = str(value).upper().strip()

        aliases = {
            "BUY": "BULLISH",
            "LONG": "BULLISH",
            "UP": "BULLISH",
            "BULL": "BULLISH",

            "SELL": "BEARISH",
            "SHORT": "BEARISH",
            "DOWN": "BEARISH",
            "BEAR": "BEARISH",

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
    def _number(value):

        try:

            if value is None:
                return None

            return float(value)

        except (ValueError, TypeError):

            return None

    # =========================================================
    # STRUCTURE NORMALIZATION
    # =========================================================

    def normalize_structure(
        self,
        structure,
        timeframe=None,
    ):

        structure = self._dict(structure)

        # Support TA results wrapped inside a technical field.
        if "technical" in structure:

            structure = self._dict(
                structure.get("technical")
            )

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
                            "structure_bias"
                        ),
                    ),
                ),
            )
        )

        breaks = self._list(
            source.get(
                "breaks",
                structure.get(
                    "breaks",
                    [],
                ),
            )
        )

        normalized_breaks = []

        for event in breaks:

            if not isinstance(event, dict):
                continue

            event_type = str(
                event.get(
                    "type",
                    event.get(
                        "event",
                        event.get(
                            "break_type",
                            "",
                        ),
                    ),
                )
            ).upper()

            event_direction = self._direction(
                event.get(
                    "direction",
                    event.get(
                        "bias",
                    ),
                )
            )

            close_confirmed = (
                event.get(
                    "close_confirmed",
                    event.get(
                        "body_close",
                        event.get(
                            "confirmed",
                            False,
                        ),
                    ),
                )
                is True
            )

            normalized_breaks.append(
                {
                    **event,
                    "type": event_type,
                    "direction": event_direction,
                    "close_confirmed": (
                        close_confirmed
                    ),
                    "timeframe": (
                        event.get(
                            "timeframe",
                            timeframe,
                        )
                    ),
                }
            )

        return {
            "timeframe": timeframe,
            "direction": direction,
            "bias": direction,
            "breaks": normalized_breaks,
            "external_structure": (
                self._dict(
                    source.get(
                        "external_structure"
                    )
                )
            ),
            "internal_structure": (
                self._dict(
                    source.get(
                        "internal_structure"
                    )
                )
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
            "raw": deepcopy(structure),
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
            event.get("direction")
        )

        event_type = str(
            event.get(
                "type",
                event.get("event", ""),
            )
        ).upper()

        body_close = (
            event.get(
                "close_confirmed",
                event.get(
                    "body_close",
                    event.get(
                        "confirmed",
                        False,
                    ),
                ),
            )
            is True
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
                == str(
                    required_type
                ).upper()
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
            "event": event,
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
                "external_structure"
            )
        )

        events = self._list(
            external.get(
                "breaks",
                structure.get(
                    "breaks",
                    [],
                ),
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
                required_type="CHoCH",
            )

            if result["valid"]:

                return {
                    "confirmed": True,
                    "direction": (
                        expected_direction
                    ),
                    "event": event,
                    "body_close_confirmed": (
                        True
                    ),
                    "structure_type": (
                        "EXTERNAL"
                    ),
                }

        return {
            "confirmed": False,
            "direction": expected_direction,
            "body_close_confirmed": False,
            "structure_type": "EXTERNAL",
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
                "internal_structure"
            )
        )

        if not internal:

            return {
                "available": False,
                "direction": "UNKNOWN",
                "breaks": [],
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

        return {
            "available": True,
            "direction": direction,
            "breaks": breaks,
            "raw": deepcopy(internal),
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

        sweeps = self._list(
            liquidity.get(
                "sweeps",
                liquidity.get(
                    "liquidity_sweeps",
                ),
            )
        )

        equal_highs = self._list(
            liquidity.get(
                "equal_highs",
                liquidity.get(
                    "eqh",
                ),
            )
        )

        equal_lows = self._list(
            liquidity.get(
                "equal_lows",
                liquidity.get(
                    "eql",
                ),
            )
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
            ).upper()

            close_back_inside = (
                sweep.get(
                    "close_back_inside",
                    sweep.get(
                        "reclaimed",
                        False,
                    ),
                )
                is True
            )

            normalized_sweeps.append(
                {
                    **sweep,
                    "direction": direction,
                    "type": sweep_type,
                    "close_back_inside": (
                        close_back_inside
                    ),
                }
            )

        return {
            "sweeps": normalized_sweeps,
            "equal_highs": equal_highs,
            "equal_lows": equal_lows,
            "raw": deepcopy(liquidity),
        }

    # =========================================================
    # FVG
    # =========================================================

    def normalize_fvg(
        self,
        fvg,
        expected_direction=None,
    ):

        items = self._list(fvg)

        normalized = []

        for item in items:

            if not isinstance(item, dict):
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
                    item.get(
                        "unmitigated",
                        False,
                    ),
                )
                is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                    False,
                )
                is True
            )

            lower = self._number(
                item.get(
                    "lower",
                    item.get(
                        "bottom",
                    ),
                )
            )

            upper = self._number(
                item.get(
                    "upper",
                    item.get(
                        "top",
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
                    "valid_poi": (
                        clean
                        and not invalidated
                        and bounds_valid
                        and direction_valid
                    ),
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

        items = self._list(poi)

        normalized = []

        current_price = self._number(
            current_price
        )

        for item in items:

            if not isinstance(item, dict):
                continue

            direction = self._direction(
                item.get(
                    "direction",
                    item.get(
                        "bias",
                    ),
                )
            )

            lower = self._number(
                item.get(
                    "lower",
                    item.get(
                        "bottom",
                    ),
                )
            )

            upper = self._number(
                item.get(
                    "upper",
                    item.get(
                        "top",
                    ),
                )
            )

            clean = (
                item.get(
                    "clean",
                    item.get(
                        "unmitigated",
                        False,
                    ),
                )
                is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                    False,
                )
                is True
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
                    item.get(
                        "tap_confirmed",
                        False,
                    ),
                )
                is True
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
                        clean
                        and not invalidated
                        and bounds_valid
                        and direction_valid
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

        items = self._list(
            displacement
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
                    item.get(
                        "valid",
                        False,
                    ),
                )
                is True
            )

            direction_valid = True

            if expected_direction:

                direction_valid = (
                    direction
                    == self._direction(
                        expected_direction
                    )
                )

            normalized.append(
                {
                    **item,
                    "direction": direction,
                    "confirmed": confirmed,
                    "direction_valid": (
                        direction_valid
                    ),
                    "valid": (
                        confirmed
                        and direction_valid
                    ),
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

        items = self._list(
            entry_models
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
                    item.get(
                        "valid",
                        False,
                    ),
                )
                is True
            )

            invalidated = (
                item.get(
                    "invalidated",
                    False,
                )
                is True
            )

            retest_confirmed = (
                item.get(
                    "retest_confirmed",
                    item.get(
                        "retest",
                        False,
                    ),
                )
                is True
            )

            direction_valid = True

            if expected_direction:

                direction_valid = (
                    direction
                    == self._direction(
                        expected_direction
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
                    "valid": (
                        confirmed
                        and not invalidated
                        and direction_valid
                    ),
                }
            )

        return normalized

    # =========================================================
    # RISK CHECKS
    # =========================================================

    REQUIRED_RISK_CHECKS = (
        "spread_valid",
        "stop_loss_valid",
        "risk_within_limit",
        "daily_limit_valid",
        "consecutive_loss_limit_valid",
        "reward_risk_valid",
    )

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
            all(normalized.values())
            and not missing
        )

        return {
            "checks": normalized,
            "missing": missing,
            "passed": passed,
            "raw": deepcopy(
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

        fvg_data = self.normalize_fvg(
            fvg,
            expected_direction=(
                trade_direction
            ),
        )

        poi_data = self.normalize_poi(
            poi,
            expected_direction=(
                trade_direction
            ),
            current_price=current_price,
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

        evidence = {
            "version": self.VERSION,
            "direction": trade_direction,

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
                        liquidity_data["sweeps"]
                    )
                ),

                "valid_fvg_available": (
                    any(
                        item.get(
                            "valid_poi",
                            False,
                        )
                        for item in fvg_data
                    )
                ),

                "valid_poi_available": (
                    any(
                        item.get(
                            "valid_poi",
                            False,
                        )
                        for item in poi_data
                    )
                ),

                "displacement_confirmed": (
                    any(
                        item.get(
                            "valid",
                            False,
                        )
                        for item in (
                            displacement_data
                        )
                    )
                ),

                "entry_model_confirmed": (
                    any(
                        item.get(
                            "valid",
                            False,
                        )
                        for item in (
                            entry_data
                        )
                    )
                ),

                "risk_checks_passed": (
                    risk_data["passed"]
                ),
            },

            "execution_authorized": False,
        }

        self.last_evidence = deepcopy(
            evidence
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
            "last_evidence": deepcopy(
                self.last_evidence
            ),
        }

    def get_last_evidence(self):

        return deepcopy(
            self.last_evidence
        )


# =============================================================
# SINGLETON
# =============================================================

smc_integration_adapter = (
    SMCIntegrationAdapter()
)
