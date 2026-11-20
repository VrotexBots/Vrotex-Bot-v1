
"""
VROTEX BOT V1
SMC Integration Adapter

Purpose:
- Normalize outputs from individual SMC engines.
- Keep trade direction separate from liquidity sweep direction.
- Validate H1 -> M5 -> M1 alignment.
- Produce a consistent evidence contract for the master SMC engine.
- Fail closed when required evidence is missing.

This module does not authorize order execution.
"""

from typing import Any, Dict, Optional


class SMCIntegrationAdapter:

    BUY = "BUY"
    SELL = "SELL"

    def __init__(self):
        self.last_result = {}

    # ---------------------------------------------------------
    # GENERAL HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _bool(value: Any) -> bool:
        return value is True

    @staticmethod
    def _first(data: Dict[str, Any], *keys, default=None):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return default

    @staticmethod
    def direction(value: Any) -> Optional[str]:
        if value is None:
            return None

        value = str(value).strip().upper()

        if value in {
            "BUY", "LONG", "BULL", "BULLISH",
            "BUY_SIDE_SETUP"
        }:
            return "BUY"

        if value in {
            "SELL", "SHORT", "BEAR", "BEARISH",
            "SELL_SIDE_SETUP"
        }:
            return "SELL"

        return None

    @staticmethod
    def _valid_zone(data: Dict[str, Any]) -> bool:
        lower = SMCIntegrationAdapter._first(
            data, "lower", "bottom", "low"
        )
        upper = SMCIntegrationAdapter._first(
            data, "upper", "top", "high"
        )

        try:
            return (
                lower is not None
                and upper is not None
                and float(lower) < float(upper)
            )
        except (TypeError, ValueError):
            return False

    # ---------------------------------------------------------
    # STRUCTURE NORMALIZATION
    # ---------------------------------------------------------

    def normalize_structure(
        self,
        raw: Any,
        timeframe: str
    ) -> Dict[str, Any]:

        data = self._dict(raw)
        structure = self._dict(
            self._first(data, "structure", "result", default={})
        )

        trade_direction = self.direction(
            self._first(
                data,
                "direction",
                default=self._first(structure, "direction")
            )
        )

        event = str(
            self._first(
                data,
                "event",
                "structure_event",
                default=self._first(
                    structure, "event", "structure_event", default=""
                )
            )
        ).upper()

        bos = self._bool(
            self._first(
                data,
                "bos",
                "bos_confirmed",
                default=self._first(
                    structure, "bos", "bos_confirmed", default=False
                )
            )
        )

        choch = self._bool(
            self._first(
                data,
                "choch",
                "choch_confirmed",
                default=self._first(
                    structure, "choch", "choch_confirmed", default=False
                )
            )
        )

        if event == "BOS":
            bos = True
        elif event in {"CHOCH", "CHoCH"}:
            choch = True

        body_close = self._bool(
            self._first(
                data,
                "body_close_confirmed",
                "full_body_close",
                "close_confirmed",
                default=self._first(
                    structure,
                    "body_close_confirmed",
                    "full_body_close",
                    "close_confirmed",
                    default=False
                )
            )
        )

        confirmed = bool(
            trade_direction
            and body_close
            and (bos or choch)
        )

        return {
            "timeframe": timeframe,
            "direction": trade_direction,
            "event": "CHOCH" if choch else "BOS" if bos else None,
            "bos": bos,
            "choch": choch,
            "body_close_confirmed": body_close,
            "confirmed": confirmed,
            "valid": confirmed,
            "raw": data
        }

    # ---------------------------------------------------------
    # LIQUIDITY NORMALIZATION
    # ---------------------------------------------------------

    def normalize_liquidity(
        self,
        raw: Any,
        trade_direction: Optional[str] = None
    ) -> Dict[str, Any]:

        data = self._dict(raw)
        trade_direction = self.direction(trade_direction)

        detected = self._bool(
            self._first(
                data,
                "detected",
                "sweep_detected",
                "swept",
                "confirmed",
                default=False
            )
        )

        sweep_direction = self.direction(
            self._first(
                data,
                "sweep_direction",
                "direction",
                "liquidity_direction"
            )
        )

        side = str(
            self._first(
                data,
                "side",
                "liquidity_side",
                "target_side",
                default=""
            )
        ).upper()

        if not sweep_direction:
            if side in {"SELL_SIDE", "SSL", "LOW", "LOWS"}:
                sweep_direction = "SELL"
            elif side in {"BUY_SIDE", "BSL", "HIGH", "HIGHS"}:
                sweep_direction = "BUY"

        wick_sweep = self._bool(
            self._first(
                data,
                "wick_sweep",
                "wick_beyond_level",
                "sweep_confirmed",
                default=detected
            )
        )

        close_back_inside = self._bool(
            self._first(
                data,
                "close_back_inside",
                "rejection_close",
                "closed_back_inside",
                default=False
            )
        )

        # A bullish setup generally needs a sell-side sweep.
        # A bearish setup generally needs a buy-side sweep.
        expected_sweep = (
            "SELL" if trade_direction == "BUY"
            else "BUY" if trade_direction == "SELL"
            else None
        )

        correct_sweep_side = bool(
            expected_sweep
            and sweep_direction == expected_sweep
        )

        confirmed = bool(
            detected
            and wick_sweep
            and correct_sweep_side
            and close_back_inside
        )

        return {
            "trade_direction": trade_direction,
            "sweep_direction": sweep_direction,
            "expected_sweep_direction": expected_sweep,
            "side": side or (
                "SELL_SIDE" if sweep_direction == "SELL"
                else "BUY_SIDE" if sweep_direction == "BUY"
                else None
            ),
            "detected": detected,
            "wick_sweep": wick_sweep,
            "close_back_inside": close_back_inside,
            "correct_sweep_side": correct_sweep_side,
            "confirmed": confirmed,
            "valid": confirmed,
            "target": self._first(
                data, "target", "level", "price_level"
            ),
            "raw": data
        }

    # ---------------------------------------------------------
    # FAIR VALUE GAP NORMALIZATION
    # ---------------------------------------------------------

    def normalize_fvg(
        self,
        raw: Any,
        expected_direction: Optional[str] = None
    ) -> Dict[str, Any]:

        data = self._dict(raw)

        expected_direction = self.direction(expected_direction)
        fvg_direction = self.direction(
            self._first(data, "direction", "bias")
        )

        detected = self._bool(
            self._first(data, "detected", "fvg_detected", default=False)
        )

        valid = self._bool(
            self._first(data, "valid", "confirmed", default=False)
        )

        mitigated = self._bool(
            self._first(data, "mitigated", default=False)
        )

        clean = self._bool(
            self._first(
                data,
                "clean",
                "unmitigated",
                default=not mitigated
            )
        )

        zone_valid = self._valid_zone(data)

        direction_aligned = bool(
            expected_direction
            and fvg_direction == expected_direction
        )

        confirmed = bool(
            detected
            and valid
            and clean
            and zone_valid
            and direction_aligned
        )

        return {
            "direction": fvg_direction,
            "expected_direction": expected_direction,
            "detected": detected,
            "valid": valid,
            "mitigated": mitigated,
            "clean": clean,
            "zone_valid": zone_valid,
            "direction_aligned": direction_aligned,
            "lower": self._first(data, "lower", "bottom", "low"),
            "upper": self._first(data, "upper", "top", "high"),
            "confirmed": confirmed,
            "valid_for_setup": confirmed,
            "raw": data
        }

    # ---------------------------------------------------------
    # POINT OF INTEREST NORMALIZATION
    # ---------------------------------------------------------

    def normalize_poi(
        self,
        raw: Any,
        expected_direction: Optional[str] = None
    ) -> Dict[str, Any]:

        data = self._dict(raw)
        expected_direction = self.direction(expected_direction)

        poi_direction = self.direction(
            self._first(data, "direction", "bias")
        )

        detected = self._bool(
            self._first(data, "detected", "valid", default=False)
        )

        clean = self._bool(
            self._first(data, "clean", "valid_zone", default=False)
        )

        unmitigated = self._bool(
            self._first(
                data,
                "unmitigated",
                "not_mitigated",
                default=False
            )
        )

        zone_valid = self._valid_zone(data)

        direction_aligned = bool(
            expected_direction
            and poi_direction == expected_direction
        )

        confirmed = bool(
            detected
            and clean
            and unmitigated
            and zone_valid
            and direction_aligned
        )

        return {
            "direction": poi_direction,
            "expected_direction": expected_direction,
            "detected": detected,
            "clean": clean,
            "unmitigated": unmitigated,
            "zone_valid": zone_valid,
            "direction_aligned": direction_aligned,
            "lower": self._first(data, "lower", "bottom", "low"),
            "upper": self._first(data, "upper", "top", "high"),
            "confirmed": confirmed,
            "valid_for_setup": confirmed,
            "raw": data
        }

    # ---------------------------------------------------------
    # DISPLACEMENT NORMALIZATION
    # ---------------------------------------------------------

    def normalize_displacement(
        self,
        raw: Any,
        expected_direction: Optional[str] = None
    ) -> Dict[str, Any]:

        data = self._dict(raw)
        expected_direction = self.direction(expected_direction)

        displacement_direction = self.direction(
            self._first(data, "direction", "bias")
        )

        detected = self._bool(
            self._first(
                data,
                "detected",
                "confirmed",
                "displacement_detected",
                default=False
            )
        )

        body_close = self._bool(
            self._first(
                data,
                "body_close_confirmed",
                "full_body_close",
                default=False
            )
        )

        direction_aligned = bool(
            expected_direction
            and displacement_direction == expected_direction
        )

        confirmed = bool(
            detected and body_close and direction_aligned
        )

        return {
            "direction": displacement_direction,
            "expected_direction": expected_direction,
            "detected": detected,
            "body_close_confirmed": body_close,
            "direction_aligned": direction_aligned,
            "confirmed": confirmed,
            "raw": data
        }

    # ---------------------------------------------------------
    # ENTRY MODEL NORMALIZATION
    # ---------------------------------------------------------

    def normalize_entry_models(
        self,
        raw: Any,
        expected_direction: Optional[str] = None
    ) -> Dict[str, Any]:

        data = self._dict(raw)
        expected_direction = self.direction(expected_direction)

        models = self._first(
            data,
            "confirmed_models",
            "models",
            "entry_models",
            default=[]
        )

        if not isinstance(models, list):
            models = []

        confirmed_models = []

        for model in models:
            if isinstance(model, str):
                confirmed_models.append({
                    "name": model,
                    "direction": expected_direction,
                    "confirmed": True
                })
                continue

            model_data = self._dict(model)

            model_direction = self.direction(
                self._first(model_data, "direction", "bias")
            )

            confirmed = self._bool(
                self._first(
                    model_data,
                    "confirmed",
                    "valid",
                    default=False
                )
            )

            if (
                confirmed
                and model_direction == expected_direction
            ):
                confirmed_models.append({
                    "name": self._first(
                        model_data, "name", "model", "type"
                    ),
                    "direction": model_direction,
                    "confirmed": True
                })

        top_level_confirmed = self._bool(
            self._first(
                data,
                "entry_model_confirmed",
                "confirmed",
                default=False
            )
        )

        confirmed = bool(
            confirmed_models or (
                top_level_confirmed
                and self.direction(
                    self._first(data, "direction", "bias")
                ) == expected_direction
            )
        )

        return {
            "direction": expected_direction,
            "confirmed": confirmed,
            "confirmed_models": confirmed_models,
            "count": len(confirmed_models),
            "raw": data
        }

    # ---------------------------------------------------------
    # RISK CHECK NORMALIZATION
    # ---------------------------------------------------------

    def normalize_risk_checks(self, raw: Any) -> Dict[str, Any]:

        data = self._dict(raw)

        checks = {
            "spread_valid": self._bool(
                self._first(data, "spread_valid", default=False)
            ),
            "stop_loss_valid": self._bool(
                self._first(data, "stop_loss_valid", default=False)
            ),
            "risk_within_limit": self._bool(
                self._first(data, "risk_within_limit", default=False)
            ),
            "daily_limit_valid": self._bool(
                self._first(data, "daily_limit_valid", default=False)
            ),
            "consecutive_loss_limit_valid": self._bool(
                self._first(
                    data,
                    "consecutive_loss_limit_valid",
                    default=False
                )
            ),
            "reward_risk_valid": self._bool(
                self._first(data, "reward_risk_valid", default=False)
            )
        }

        return {
            "checks": checks,
            "all_passed": all(checks.values()),
            "raw": data
        }

    # ---------------------------------------------------------
    # MASTER EVIDENCE CONTRACT
    # ---------------------------------------------------------

    def build_evidence(
        self,
        trade_direction: str,
        h1_structure: Any,
        m5_structure: Any,
        m1_structure: Any,
        liquidity: Any,
        fvg: Any,
        poi: Any,
        displacement: Any,
        entry_models: Any,
        risk_checks: Any
    ) -> Dict[str, Any]:

        direction = self.direction(trade_direction)

        if direction is None:
            result = {
                "valid": False,
                "execution_authorized": False,
                "reason": "INVALID_TRADE_DIRECTION"
            }
            self.last_result = result
            return result

        h1 = self.normalize_structure(h1_structure, "H1")
        m5 = self.normalize_structure(m5_structure, "M5")
        m1 = self.normalize_structure(m1_structure, "M1")

        liquidity_result = self.normalize_liquidity(
            liquidity, direction
        )

        fvg_result = self.normalize_fvg(fvg, direction)
        poi_result = self.normalize_poi(poi, direction)

        displacement_result = self.normalize_displacement(
            displacement, direction
        )

        entry_result = self.normalize_entry_models(
            entry_models, direction
        )

        risk_result = self.normalize_risk_checks(risk_checks)

        structure_aligned = all(
            item["confirmed"]
            and item["direction"] == direction
            for item in (h1, m5, m1)
        )

        required_checks = {
            "h1_structure": h1["confirmed"],
            "m5_structure": m5["confirmed"],
            "m1_structure": m1["confirmed"],
            "structure_direction_alignment": structure_aligned,
            "correct_liquidity_sweep": liquidity_result["confirmed"],
            "clean_directional_fvg": fvg_result["confirmed"],
            "clean_unmitigated_poi": poi_result["confirmed"],
            "directional_displacement": displacement_result["confirmed"],
            "confirmed_entry_model": entry_result["confirmed"],
            "risk_checks": risk_result["all_passed"]
        }

        valid = all(required_checks.values())

        result = {
            "valid": valid,
            "trade_direction": direction,
            "execution_authorized": False,
            "required_checks": required_checks,
            "structure": {
                "H1": h1,
                "M5": m5,
                "M1": m1,
                "aligned": structure_aligned
            },
            "liquidity": liquidity_result,
            "fvg": fvg_result,
            "poi": poi_result,
            "displacement": displacement_result,
            "entry_models": entry_result,
            "risk": risk_result,
            "failed_checks": [
                name
                for name, passed in required_checks.items()
                if not passed
            ]
        }

        self.last_result = result
        return result

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)


smc_integration_adapter = SMCIntegrationAdapter()
