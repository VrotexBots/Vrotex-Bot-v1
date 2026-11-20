"""
VROTEX BOT V1
SMC Setup Validator

Purpose:
- Validate H1 -> M5 -> M1 setup requirements.
- Check structure, liquidity, POI, FVG and displacement evidence.
- Validate directional consistency.
- Reject incomplete or contradictory setups.
- Keep setup validation separate from order execution.

Approved strategy:
H1 = External narrative
M5 = Confirmation
M1 = Entry

A+ score threshold is handled by the master SMC engine.
This module does not execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCSetupValidator:
    VERSION = "2.0"

    VALID_DIRECTIONS = {"BULLISH", "BEARISH"}

    def __init__(self):
        pass

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    @staticmethod
    def _is_confirmed(evidence: Any) -> bool:
        if not isinstance(evidence, dict):
            return False

        return (
            evidence.get("confirmed") is True
            or evidence.get("valid") is True
        )

    def _validate_direction(
        self,
        evidence: Any,
        expected_direction: str,
    ) -> bool:
        if not isinstance(evidence, dict):
            return False

        direction = self._direction(
            evidence.get("direction")
        )

        if direction is None:
            return False

        return direction == expected_direction

    def _validate_h1(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        structure = evidence.get("structure", {})

        if not isinstance(structure, dict):
            structure = {}

        h1_direction = self._direction(
            evidence.get("direction")
            or structure.get("bias")
            or structure.get("direction")
        )

        valid = h1_direction == direction

        return {
            "valid": valid,
            "direction": h1_direction,
            "reason": (
                "H1_DIRECTION_CONFIRMED"
                if valid
                else "H1_DIRECTION_MISSING_OR_CONFLICTING"
            ),
        }

    def _validate_m5(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        breaks = evidence.get("breaks", [])

        if not isinstance(breaks, list):
            breaks = []

        matching_breaks = []

        for item in breaks:
            if not isinstance(item, dict):
                continue

            break_direction = self._direction(
                item.get("direction")
            )

            confirmation = str(
                item.get("confirmation", "")
            ).upper()

            body_close = (
                item.get("body_close_confirmed") is True
                or confirmation == "BODY_CLOSE"
            )

            break_type = str(
                item.get("type", "")
            ).upper()

            if (
                break_direction == direction
                and body_close
                and break_type in (
                    "CHOCH",
                    "BOS",
                    "BULLISH_BREAK",
                    "BEARISH_BREAK",
                )
            ):
                matching_breaks.append(item)

        explicit = (
            evidence.get("confirmed") is True
            and self._direction(evidence.get("direction")) == direction
            and evidence.get("body_close_confirmed") is True
        )

        valid = bool(matching_breaks) or explicit

        return {
            "valid": valid,
            "matching_breaks": matching_breaks,
            "reason": (
                "M5_BODY_CLOSE_CONFIRMED"
                if valid
                else "M5_CONFIRMATION_NOT_CONFIRMED"
            ),
        }

    def _validate_liquidity(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        sweeps = evidence.get(
            "liquidity_sweeps",
            evidence.get("sweeps", []),
        )

        if isinstance(sweeps, dict):
            sweeps = [sweeps]

        if not isinstance(sweeps, list):
            sweeps = []

        required_type = (
            "SELL_SIDE_SWEEP"
            if direction == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        matching = []

        for sweep in sweeps:
            if not isinstance(sweep, dict):
                continue

            sweep_type = str(
                sweep.get("type", "")
            ).upper()

            confirmation = str(
                sweep.get("confirmation", "")
            ).upper()

            if (
                sweep_type == required_type
                and confirmation == "WICK_THROUGH_CLOSE_BACK_INSIDE"
            ):
                matching.append(sweep)

        return {
            "valid": bool(matching),
            "matching_sweeps": matching,
            "reason": (
                "DIRECTIONAL_LIQUIDITY_SWEEP_CONFIRMED"
                if matching
                else "REQUIRED_LIQUIDITY_SWEEP_MISSING"
            ),
        }

    def _validate_zone(
        self,
        evidence: Any,
        direction: str,
        name: str,
    ) -> Dict[str, Any]:
        if not isinstance(evidence, dict):
            return {
                "valid": False,
                "reason": f"{name}_EVIDENCE_MISSING",
            }

        zone_direction = self._direction(
            evidence.get("direction")
        )

        clean = (
            evidence.get("clean") is True
            or evidence.get("unmitigated") is True
        )

        lower = evidence.get(
            "lower",
            evidence.get("low"),
        )

        upper = evidence.get(
            "upper",
            evidence.get("high"),
        )

        try:
            lower = float(lower)
            upper = float(upper)
            valid_bounds = lower < upper
        except (TypeError, ValueError):
            valid_bounds = False

        valid = (
            zone_direction == direction
            and clean
            and valid_bounds
            and evidence.get("invalidated") is not True
        )

        return {
            "valid": valid,
            "direction": zone_direction,
            "clean": clean,
            "valid_bounds": valid_bounds,
            "reason": (
                f"{name}_VALID"
                if valid
                else f"{name}_MISSING_DIRTY_OR_INVALID"
            ),
        }

    def _validate_displacement(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        detected = evidence.get(
            "latest_displacement",
            evidence,
        )

        if not isinstance(detected, dict):
            detected = {}

        confirmed = (
            detected.get("confirmed") is True
            or detected.get("detected") is True
        )

        displacement_direction = self._direction(
            detected.get("direction")
        )

        valid = (
            confirmed
            and displacement_direction == direction
        )

        return {
            "valid": valid,
            "direction": displacement_direction,
            "reason": (
                "DIRECTIONAL_DISPLACEMENT_CONFIRMED"
                if valid
                else "DIRECTIONAL_DISPLACEMENT_MISSING"
            ),
        }

    def _validate_entry(
        self,
        evidence: Any,
        direction: str,
    ) -> Dict[str, Any]:
        if not isinstance(evidence, dict):
            return {
                "valid": False,
                "reason": "ENTRY_MODEL_EVIDENCE_MISSING",
            }

        models = evidence.get(
            "confirmed_models",
            evidence.get("entry_models", []),
        )

        if isinstance(models, dict):
            models = [models]

        if not isinstance(models, list):
            models = []

        matching = []

        for model in models:
            if not isinstance(model, dict):
                continue

            model_direction = self._direction(
                model.get("direction")
            )

            if (
                model.get("confirmed") is True
                and model_direction == direction
            ):
                matching.append(model)

        direct_confirmation = (
            evidence.get("confirmed") is True
            and self._direction(evidence.get("direction")) == direction
        )

        valid = bool(matching) or direct_confirmation

        return {
            "valid": valid,
            "matching_models": matching,
            "reason": (
                "ENTRY_MODEL_CONFIRMED"
                if valid
                else "NO_DIRECTIONAL_ENTRY_MODEL_CONFIRMED"
            ),
        }

    def validate(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        if not isinstance(evidence, dict):
            return self._error("INVALID_EVIDENCE_INPUT")

        expected_direction = self._direction(direction)

        if expected_direction is None:
            return self._error("INVALID_EXPECTED_DIRECTION")

        h1 = evidence.get("H1", {})
        m5 = evidence.get("M5", {})

        if not isinstance(h1, dict):
            h1 = {}

        if not isinstance(m5, dict):
            m5 = {}

        checks = {
            "h1_structure": self._validate_h1(
                h1,
                expected_direction,
            ),
            "m5_confirmation": self._validate_m5(
                m5,
                expected_direction,
            ),
            "liquidity": self._validate_liquidity(
                evidence.get("liquidity", {}),
                expected_direction,
            ),
            "poi": self._validate_zone(
                evidence.get("poi"),
                expected_direction,
                "POI",
            ),
            "fvg": self._validate_zone(
                evidence.get("fvg"),
                expected_direction,
                "FVG",
            ),
            "displacement": self._validate_displacement(
                evidence.get("displacement", {}),
                expected_direction,
            ),
            "entry_model": self._validate_entry(
                evidence.get("entry"),
                expected_direction,
            ),
        }

        failed = [
            name
            for name, result in checks.items()
            if not result["valid"]
        ]

        valid = not failed

        return {
            "status": (
                "SETUP_VALID"
                if valid
                else "SETUP_REJECTED"
            ),
            "version": self.VERSION,
            "valid": valid,
            "confirmed": valid,
            "direction": expected_direction,
            "checks": checks,
            "failed_checks": failed,
            "passed_count": sum(
                1 for item in checks.values()
                if item["valid"]
            ),
            "total_checks": len(checks),
            "execution_authorized": False,
        }

    @staticmethod
    def _error(reason: str) -> Dict[str, Any]:
        return {
            "status": "ERROR",
            "version": "2.0",
            "valid": False,
            "confirmed": False,
            "reason": reason,
            "execution_authorized": False,
        }


smc_setup_validator = SMCSetupValidator()
