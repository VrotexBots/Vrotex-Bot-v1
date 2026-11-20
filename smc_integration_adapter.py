
"""
VROTEX BOT V1
SMC Integration Adapter
Version 2.0

Connects the individual SMC engines to the master SMC engine.

Approved strategy:
H1 = external directional narrative
M5 = confirmation
M1 = entry trigger

BOS and CHoCH require full candle-body close confirmation.
Wick-only movement is never a confirmed structure break.

Execution authorization is always disabled here.
"""

from typing import Any, Dict, Optional


class SMCIntegrationAdapter:

    VERSION = "2.0"

    BUY = "BUY"
    SELL = "SELL"

    def __init__(self):
        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # GENERAL HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _list(value: Any) -> list:
        return value if isinstance(value, list) else []

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
        timeframe: str,
        expected_direction: Optional[str] = None
    ) -> Dict[str, Any]:

        data = self._dict(raw)
        structure = self._dict(data.get("structure"))

        expected_direction = self.direction(expected_direction)

        raw_direction = self._first(
            data,
            "direction",
            "bias",
            default=self._first(
                structure,
                "direction",
                "bias"
            )
        )

        if raw_direction is None:
            raw_direction = structure.get("bias")

        actual_direction = self.direction(raw_direction)

        # The original structure engine stores events in "breaks".
        raw_breaks = self._list(data.get("breaks"))

        # Also support direct event fields from other SMC modules.
        direct_event = str(
            self._first(
                data,
                "event",
                "structure_event",
                default=""
            )
        ).upper()

        if direct_event in {"BOS", "CHOCH"}:
            raw_breaks.append({
                "type": direct_event,
                "direction": data.get("direction"),
                "confirmation": self._first(
                    data,
                    "confirmation",
                    "body_close_confirmation"
                )
            })

        confirmed_breaks = []

        for event in raw_breaks:
            event_data = self._dict(event)

            event_type = str(
                event_data.get("type", "")
            ).upper()

            event_direction = self.direction(
                event_data.get("direction")
            )

            confirmation = str(
                event_data.get("confirmation", "")
            ).upper()

            body_close = (
                confirmation in {
                    "BODY_CLOSE",
                    "FULL_BODY_CLOSE",
                    "BODY_CLOSE_CONFIRMED"
                }
                or event_data.get(
                    "body_close_confirmed"
                ) is True
            )

            valid_event = (
                event_type in {"BOS", "CHOCH"}
                and event_direction is not None
                and body_close
            )

            if valid_event:
                confirmed_breaks.append({
                    "type": event_type,
                    "direction": event_direction,
                    "body_close_confirmed": True,
                    "level": event_data.get("level"),
                    "candle_index": event_data.get(
                        "candle_index"
                    )
                })

        matching_breaks = [
            event for event in confirmed_breaks
            if (
                expected_direction is None
                or event["direction"] == expected_direction
            )
        ]

        # H1 directional narrative may be established by HH/HL
        # or LH/LL structure without a new break on the last candle.
        if timeframe == "H1":
            bullish_structure = (
                actual_direction == "BUY"
                or (
                    actual_direction is None
                    and structure.get("bias") == "BULLISH"
                )
            )

            bearish_structure = (
                actual_direction == "SELL"
                or (
                    actual_direction is None
                    and structure.get("bias") == "BEARISH"
                )
            )

            if expected_direction == "BUY":
                confirmed = bullish_structure

            elif expected_direction == "SELL":
                confirmed = bearish_structure

            else:
                confirmed = (
                    bullish_structure or bearish_structure
                )

        # M5 needs a confirmed directional structure event.
        elif timeframe == "M5":
            confirmed = bool(matching_breaks)

        # M1 is an entry timeframe. Its structure event is useful
        # evidence but is not required here when a separately
        # validated M1 entry model supplies the trigger.
        elif timeframe == "M1":
            confirmed = (
                actual_direction == expected_direction
                if actual_direction and expected_direction
                else bool(matching_breaks)
            )

        else:
            confirmed = bool(matching_breaks)

        return {
            "timeframe": timeframe,
            "direction": actual_direction,
            "expected_direction": expected_direction,
            "bias": structure.get("bias"),
            "confirmed_breaks": confirmed_breaks,
            "matching_breaks": matching_breaks,
            "confirmed": bool(confirmed),
            "valid": bool(confirmed),
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

        raw_sweeps = self._list(
            data.get("liquidity_sweeps")
        )

        if not raw_sweeps and data:
            raw_sweeps = [data]

        expected_sweep = (
            "SELL" if trade_direction == "BUY"
            else "BUY" if trade_direction == "SELL"
            else None
        )

        valid_sweeps = []

        for item in raw_sweeps:
            sweep = self._dict(item)

            sweep_type = str(
                sweep.get("type", "")
            ).upper()

            if sweep_type == "SELL_SIDE_SWEEP":
                sweep_direction = "SELL"

            elif sweep_type == "BUY_SIDE_SWEEP":
                sweep_direction = "BUY"

            else:
                sweep_direction = self.direction(
                    self._first(
                        sweep,
                        "sweep_direction",
                        "direction"
                    )
                )

            confirmation = str(
                sweep.get("confirmation", "")
            ).upper()

            close_back_inside = (
                confirmation in {
                    "WICK_THROUGH_CLOSE_BACK_INSIDE",
                    "CLOSE_BACK_INSIDE"
                }
                or sweep.get("close_back_inside") is True
            )

            if (
                sweep_direction == expected_sweep
                and close_back_inside
            ):
                valid_sweeps.append({
                    "type": sweep_type,
                    "sweep_direction": sweep_direction,
                    "level": sweep.get("level"),
                    "candle_index": sweep.get("candle_index"),
                    "close_back_inside": True
                })

        confirmed = bool(valid_sweeps)

        return {
            "trade_direction": trade_direction,
            "expected_sweep_direction": expected_sweep,
            "detected": bool(raw_sweeps),
            "confirmed": confirmed,
            "valid": confirmed,
            "sweeps": valid_sweeps,
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
            self._first(
                data,
                "detected",
                "fvg_detected",
                default=False
            )
        )

        valid = self._bool(
            self._first(
                data,
                "valid",
                "confirmed",
                default=False
            )
        )

        mitigated = self._bool(
            data.get("mitigated", False)
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

        direction_aligned = (
            fvg_direction == expected_direction
            and expected_direction is not None
        )

        confirmed = bool(
            detected
            and valid
            and clean
            and not mitigated
            and zone_valid
            and direction_aligned
        )

        return {
            "direction": fvg_direction,
            "expected_direction": expected_direction,
            "detected": detected,
            "valid": valid,
            "clean": clean,
            "mitigated": mitigated,
            "zone_valid": zone_valid,
            "direction_aligned": direction_aligned,
            "lower": self._first(
                data, "lower", "bottom", "low"
            ),
            "upper": self._first(
                data, "upper", "top", "high"
            ),
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
            self._first(
                data,
                "detected",
                "valid",
                default=False
            )
        )

        clean = self._bool(
            self._first(
                data,
                "clean",
                "valid_zone",
                default=False
            )
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

        direction_aligned = (
            poi_direction == expected_direction
            and expected_direction is not None
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
            "lower": self._first(
                data, "lower", "bottom", "low"
            ),
            "upper": self._first(
                data, "upper", "top", "high"
            ),
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

        aligned = (
            displacement_direction == expected_direction
            and expected_direction is not None
        )

        confirmed = bool(
            detected and body_close and aligned
        )

        return {
            "direction": displacement_direction,
            "expected_direction": expected_direction,
            "detected": detected,
            "body_close_confirmed": body_close,
            "direction_aligned": aligned,
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

        models = self._list(models)
        confirmed_models = []

        for model in models:
            if isinstance(model, str):
                # A string alone is not proof of confirmation.
                continue

            item = self._dict(model)

            model_direction = self.direction(
                self._first(item, "direction", "bias")
            )

            model_confirmed = self._bool(
                item.get("confirmed", False)
            )

            if (
                model_confirmed
                and model_direction == expected_direction
            ):
                confirmed_models.append({
                    "name": self._first(
                        item, "name", "model", "type"
                    ),
                    "direction": model_direction,
                    "confirmed": True
                })

        confirmed = bool(confirmed_models)

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

    def normalize_risk_checks(
        self,
        raw: Any
    ) -> Dict[str, Any]:

        data = self._dict(raw)

        checks = {
            "spread_valid": self._bool(
                data.get("spread_valid")
            ),
            "stop_loss_valid": self._bool(
                data.get("stop_loss_valid")
            ),
            "risk_within_limit": self._bool(
                data.get("risk_within_limit")
            ),
            "daily_limit_valid": self._bool(
                data.get("daily_limit_valid")
            ),
            "consecutive_loss_limit_valid": self._bool(
                data.get("consecutive_loss_limit_valid")
            ),
            "reward_risk_valid": self._bool(
                data.get("reward_risk_valid")
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

        h1 = self.normalize_structure(
            h1_structure, "H1", direction
        )

        m5 = self.normalize_structure(
            m5_structure, "M5", direction
        )

        m1 = self.normalize_structure(
            m1_structure, "M1", direction
        )

        liquidity_result = self.normalize_liquidity(
            liquidity, direction
        )

        fvg_result = self.normalize_fvg(
            fvg, direction
        )

        poi_result = self.normalize_poi(
            poi, direction
        )

        displacement_result = self.normalize_displacement(
            displacement, direction
        )

        entry_result = self.normalize_entry_models(
            entry_models, direction
        )

        risk_result = self.normalize_risk_checks(
            risk_checks
        )

        structure_aligned = bool(
            h1["confirmed"]
            and h1["direction"] == direction
            and m5["confirmed"]
            and m5["matching_breaks"]
            and m1["confirmed"]
            and m1["direction"] in {None, direction}
        )

        required_checks = {
            "h1_directional_narrative": h1["confirmed"],
            "m5_confirmed_structure": m5["confirmed"],
            "m1_entry_structure": m1["confirmed"],
            "timeframe_alignment": structure_aligned,
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

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "SMC_INTEGRATION_ADAPTER",
            "version": self.VERSION,
            "status": "ACTIVE",
            "execution_authorized": False
        }


smc_integration_adapter = SMCIntegrationAdapter()
