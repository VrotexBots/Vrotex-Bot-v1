
"""
VROTEX BOT V1
SMC INTEGRATION ADAPTER

Purpose:
- Standardize SMC module outputs.
- Normalize bullish/bearish direction values.
- Convert structure, liquidity, FVG and POI evidence
  into a consistent format.
- Prevent missing evidence from being treated as confirmed.
- Prepare standardized inputs for the evidence aggregator.

This module does not execute trades or authorize orders.
"""

from typing import Any, Dict, Optional


class SMCIntegrationAdapter:

    DIRECTIONS = ("BULLISH", "BEARISH")

    def __init__(self):
        self.last_output: Dict[str, Any] = {}

    @staticmethod
    def direction(value: Any) -> str:
        value = str(value or "").strip().upper()

        aliases = {
            "BUY": "BULLISH",
            "LONG": "BULLISH",
            "BULL": "BULLISH",
            "SELL": "BEARISH",
            "SHORT": "BEARISH",
            "BEAR": "BEARISH",
        }

        value = aliases.get(value, value)

        return value if value in (
            "BULLISH", "BEARISH"
        ) else "NONE"

    @staticmethod
    def truth(value: Any) -> bool:
        return value is True

    @staticmethod
    def number(value: Any) -> Optional[float]:
        try:
            result = float(value)

            if result != result:
                return None

            if result in (
                float("inf"),
                float("-inf")
            ):
                return None

            return result

        except (TypeError, ValueError):
            return None

    def normalize_structure(
        self,
        raw: Dict[str, Any],
        timeframe: str,
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        structure = raw.get("structure", {})

        if not isinstance(structure, dict):
            structure = {}

        direction = self.direction(
            raw.get("direction")
            or structure.get("direction")
            or raw.get("bias")
        )

        body_close = (
            raw.get("body_close_confirmed") is True
            or structure.get("body_close_confirmed") is True
        )

        bos_confirmed = (
            raw.get("bos_confirmed") is True
            or structure.get("bos_confirmed") is True
        )

        choch_confirmed = (
            raw.get("choch_confirmed") is True
            or structure.get("choch_confirmed") is True
        )

        return {
            "timeframe": str(timeframe).upper(),
            "direction": direction,
            "confirmed": (
                direction != "NONE"
                and (
                    bos_confirmed
                    or choch_confirmed
                )
                and body_close
            ),
            "body_close_confirmed": body_close,
            "bos_confirmed": bos_confirmed,
            "choch_confirmed": choch_confirmed,
            "higher_high": raw.get("higher_high") is True,
            "higher_low": raw.get("higher_low") is True,
            "lower_high": raw.get("lower_high") is True,
            "lower_low": raw.get("lower_low") is True,
            "source_valid": raw.get("valid") is True,
        }

    def normalize_liquidity(
        self,
        raw: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        expected_direction = self.direction(
            expected_direction
        )

        sweep = raw.get("sweep", raw)

        if not isinstance(sweep, dict):
            sweep = {}

        direction = self.direction(
            sweep.get("direction")
        )

        detected = (
            sweep.get("detected") is True
            or sweep.get("swept") is True
            or sweep.get("confirmed") is True
        )

        confirmed = (
            detected
            and direction == expected_direction
            and sweep.get("valid", True) is True
        )

        target = raw.get(
            "opposing_target",
            raw.get("target", {})
        )

        if not isinstance(target, dict):
            target = {}

        target_price = self.number(
            target.get("price")
        )

        return {
            "direction": direction,
            "detected": detected,
            "confirmed": confirmed,
            "valid": sweep.get("valid", True) is True,
            "approved": confirmed,
            "opposing_target": {
                "price": target_price,
                "type": target.get("type"),
                "status": target.get("status"),
                "valid": target_price is not None,
            },
        }

    def normalize_fvg(
        self,
        raw: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        expected_direction = self.direction(
            expected_direction
        )

        direction = self.direction(
            raw.get("direction")
        )

        lower = self.number(
            raw.get("lower", raw.get("bottom"))
        )

        upper = self.number(
            raw.get("upper", raw.get("top"))
        )

        detected = (
            raw.get("detected") is True
            or raw.get("valid") is True
        )

        zone_valid = (
            lower is not None
            and upper is not None
            and lower < upper
        )

        unmitigated = (
            raw.get("mitigated") is not True
            and raw.get("fully_mitigated") is not True
            and raw.get("status") != "FULLY_MITIGATED"
        )

        confirmed = (
            detected
            and zone_valid
            and direction == expected_direction
            and unmitigated
        )

        return {
            "detected": detected,
            "direction": direction,
            "lower": lower,
            "upper": upper,
            "valid": zone_valid,
            "confirmed": confirmed,
            "clean": raw.get("clean", False) is True,
            "unmitigated": unmitigated,
            "mitigated": not unmitigated,
        }

    def normalize_poi(
        self,
        raw: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        expected_direction = self.direction(
            expected_direction
        )

        direction = self.direction(
            raw.get("direction")
        )

        lower = self.number(raw.get("lower"))
        upper = self.number(raw.get("upper"))

        detected = raw.get("detected") is True

        zone_valid = (
            lower is not None
            and upper is not None
            and lower < upper
        )

        clean = raw.get("clean", False) is True

        unmitigated = (
            raw.get("unmitigated", False) is True
            and raw.get("mitigated", False) is not True
        )

        confirmed = (
            detected
            and zone_valid
            and direction == expected_direction
            and clean
            and unmitigated
        )

        return {
            "detected": detected,
            "direction": direction,
            "lower": lower,
            "upper": upper,
            "valid": zone_valid,
            "confirmed": confirmed,
            "approved": confirmed,
            "clean": clean,
            "unmitigated": unmitigated,
        }

    def normalize_displacement(
        self,
        raw: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        expected_direction = self.direction(
            expected_direction
        )

        direction = self.direction(
            raw.get("direction")
        )

        detected = (
            raw.get("detected") is True
            or raw.get("confirmed") is True
        )

        confirmed = (
            detected
            and direction == expected_direction
            and raw.get("valid", True) is True
        )

        return {
            "detected": detected,
            "direction": direction,
            "confirmed": confirmed,
            "valid": raw.get("valid", True) is True,
            "body_ratio": self.number(
                raw.get("body_ratio")
            ),
            "body_multiple": self.number(
                raw.get("body_multiple")
            ),
        }

    def normalize_entry_models(
        self,
        raw: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        expected_direction = self.direction(
            expected_direction
        )

        models = raw.get("models", {})

        if not isinstance(models, dict):
            models = {}

        normalized = {}

        for name, result in models.items():

            if not isinstance(result, dict):
                continue

            model_direction = self.direction(
                result.get("direction")
            )

            confirmed = (
                result.get("confirmed") is True
                and model_direction == expected_direction
            )

            normalized[str(name)] = {
                "direction": model_direction,
                "confirmed": confirmed,
                "evidence": (
                    result.get("evidence", {})
                    if isinstance(
                        result.get("evidence", {}),
                        dict
                    )
                    else {}
                ),
            }

        confirmed_models = [
            name
            for name, result in normalized.items()
            if result["confirmed"]
        ]

        return {
            "valid": raw.get("valid") is True,
            "models": normalized,
            "confirmed_models": confirmed_models,
            "confirmed_count": len(confirmed_models),
            "entry_model_confirmed": bool(
                confirmed_models
            ),
            "execution_authorized": False,
        }

    def normalize_risk_checks(
        self,
        raw: Dict[str, Any],
    ) -> Dict[str, Any]:

        raw = raw if isinstance(raw, dict) else {}

        return {
            "risk_acceptable": (
                raw.get("risk_acceptable") is True
            ),
            "spread_acceptable": (
                raw.get("spread_acceptable") is True
            ),
            "daily_limit_acceptable": (
                raw.get("daily_limit_acceptable") is True
            ),
            "consecutive_loss_limit_acceptable": (
                raw.get(
                    "consecutive_loss_limit_acceptable"
                ) is True
            ),
            "position_limit_acceptable": (
                raw.get("position_limit_acceptable") is True
            ),
            "checks_complete": (
                raw.get("checks_complete") is True
            ),
        }

    def build_evidence(
        self,
        direction: str,
        h1: Dict[str, Any],
        m5: Dict[str, Any],
        m1: Dict[str, Any],
        liquidity: Dict[str, Any],
        poi: Dict[str, Any],
        displacement: Dict[str, Any],
        fvg: Dict[str, Any],
        entry_models: Dict[str, Any],
        risk_checks: Dict[str, Any],
    ) -> Dict[str, Any]:

        direction = self.direction(direction)

        if direction == "NONE":
            return {
                "valid": False,
                "status": "INVALID_DIRECTION",
                "execution_authorized": False,
            }

        normalized = {
            "h1": self.normalize_structure(h1, "H1"),
            "m5": self.normalize_structure(m5, "M5"),
            "m1": self.normalize_structure(m1, "M1"),
            "liquidity": self.normalize_liquidity(
                liquidity, direction
            ),
            "poi": self.normalize_poi(
                poi, direction
            ),
            "displacement": self.normalize_displacement(
                displacement, direction
            ),
            "fvg": self.normalize_fvg(
                fvg, direction
            ),
            "entry_model": self.normalize_entry_models(
                entry_models, direction
            ),
            "risk_checks": self.normalize_risk_checks(
                risk_checks
            ),
        }

        directions = [
            normalized["h1"]["direction"],
            normalized["m5"]["direction"],
            normalized["m1"]["direction"],
        ]

        alignment = (
            all(item == direction for item in directions)
            and all(
                normalized[key]["confirmed"]
                for key in ("h1", "m5", "m1")
            )
        )

        normalized["alignment"] = {
            "aligned": alignment,
            "direction": direction,
            "timeframes": {
                "H1": normalized["h1"],
                "M5": normalized["m5"],
                "M1": normalized["m1"],
            },
        }

        normalized["valid"] = (
            alignment
            and normalized["entry_model"][
                "entry_model_confirmed"
            ]
        )

        normalized["status"] = (
            "EVIDENCE_READY"
            if normalized["valid"]
            else "EVIDENCE_INCOMPLETE"
        )

        normalized["execution_authorized"] = False

        self.last_output = normalized

        return normalized

    def get_status(self) -> Dict[str, Any]:

        return {
            "module": "SMCIntegrationAdapter",
            "ready": True,
            "last_output": self.last_output,
            "execution_authorized": False,
        }


smc_integration_adapter = SMCIntegrationAdapter()
