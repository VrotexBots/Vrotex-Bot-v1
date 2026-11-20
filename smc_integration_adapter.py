
"""
VROTEX BOT V1
SMC Integration Adapter

Purpose:
- Normalize evidence from individual SMC modules.
- Reconcile different module output formats.
- Enforce H1 -> M5 -> M1 strategy requirements.
- Reject unverified external CHoCH evidence.
- Preserve original evidence for auditing.
- Keep risk validation separate from execution.

Approved strategy:
H1 = External narrative
M5 = External CHoCH confirmation
M1 = Approved entry model

This module does not calculate A+ scores.
This module does not execute trades.
"""

from typing import Any, Dict, List, Optional
import math


class SMCIntegrationAdapter:

    VERSION = "3.0"

    VALID_DIRECTIONS = ("BULLISH", "BEARISH")

    REQUIRED_RISK_CHECKS = (
        "spread_valid",
        "stop_loss_valid",
        "risk_within_limit",
        "daily_limit_valid",
        "consecutive_loss_limit_valid",
        "reward_risk_valid",
    )

    def __init__(self):
        self.last_result: Dict[str, Any] = {}

    # --------------------------------------------------
    # BASIC NORMALIZATION
    # --------------------------------------------------

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        return []

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)

            if not math.isfinite(result):
                return None

            return result

        except (TypeError, ValueError):
            return None

    @staticmethod
    def direction(value: Any) -> Optional[str]:

        value = str(value or "").strip().upper()

        if value in (
            "BUY",
            "LONG",
            "BULL",
            "BULLISH",
        ):
            return "BULLISH"

        if value in (
            "SELL",
            "SHORT",
            "BEAR",
            "BEARISH",
        ):
            return "BEARISH"

        return None

    @staticmethod
    def _body_close(event: Dict[str, Any]) -> bool:

        confirmation = str(
            event.get("confirmation", "")
        ).upper()

        return (
            event.get("body_close_confirmed") is True
            or event.get("full_body_close") is True
            or confirmation == "BODY_CLOSE"
        )

    @staticmethod
    def _external_event(event: Dict[str, Any]) -> bool:

        scope = str(
            event.get(
                "structure_scope",
                event.get("scope", ""),
            )
        ).upper()

        return (
            event.get("external") is True
            or event.get("is_external") is True
            or scope in (
                "EXTERNAL",
                "EXTERNAL_STRUCTURE",
                "EXTERNAL_MARKET_STRUCTURE",
            )
        )

    # --------------------------------------------------
    # STRUCTURE NORMALIZATION
    # --------------------------------------------------

    def normalize_structure(
        self,
        raw: Any,
        timeframe: str,
        expected_direction: Optional[str] = None,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        timeframe = str(timeframe).upper()

        expected = self.direction(expected_direction)

        structure = self._as_dict(
            source.get("structure")
        )

        actual_direction = self.direction(
            source.get("direction")
            or source.get("bias")
            or structure.get("bias")
            or structure.get("direction")
        )

        breaks = self._as_list(
            source.get("breaks")
        )

        normalized_breaks = []

        for item in breaks:

            event = self._as_dict(item)

            event_type = str(
                event.get("type", "")
            ).upper()

            event_direction = self.direction(
                event.get("direction")
            )

            if event_type not in ("BOS", "CHOCH"):
                continue

            normalized_breaks.append({
                **event,
                "type": event_type,
                "direction": event_direction,
                "body_close_confirmed": self._body_close(
                    event
                ),
                "external": self._external_event(
                    event
                ),
            })

        aligned = (
            actual_direction is not None
            and (
                expected is None
                or actual_direction == expected
            )
        )

        if timeframe == "H1":

            confirmed = (
                aligned
                and source.get("confirmed") is not False
                and source.get("valid") is not False
            )

            return {
                "timeframe": "H1",
                "direction": actual_direction,
                "confirmed": confirmed,
                "valid": confirmed,
                "structure": structure,
                "breaks": normalized_breaks,
                "reason": (
                    "H1_DIRECTION_CONFIRMED"
                    if confirmed
                    else "H1_DIRECTION_MISSING_OR_CONFLICTING"
                ),
                "source_evidence": source,
            }

        if timeframe == "M5":

            matching_choch = [
                event
                for event in normalized_breaks
                if (
                    event["type"] == "CHOCH"
                    and event["direction"] == expected
                    and event["body_close_confirmed"]
                    and event["external"]
                )
            ]

            confirmed = (
                bool(matching_choch)
                and aligned
            )

            return {
                "timeframe": "M5",
                "direction": actual_direction,
                "confirmed": confirmed,
                "valid": confirmed,
                "breaks": normalized_breaks,
                "external_choch": (
                    matching_choch[-1]
                    if matching_choch
                    else None
                ),
                "reason": (
                    "M5_EXTERNAL_CHOCH_CONFIRMED"
                    if confirmed
                    else "M5_EXTERNAL_CHOCH_NOT_VERIFIED"
                ),
                "source_evidence": source,
            }

        if timeframe == "M1":

            # M1 direction is contextual.
            # Entry confirmation is validated separately.
            confirmed = (
                actual_direction is None
                or expected is None
                or actual_direction == expected
            )

            return {
                "timeframe": "M1",
                "direction": actual_direction,
                "confirmed": confirmed,
                "valid": confirmed,
                "breaks": normalized_breaks,
                "context_only": True,
                "reason": (
                    "M1_CONTEXT_ACCEPTED"
                    if confirmed
                    else "M1_DIRECTION_CONFLICT"
                ),
                "source_evidence": source,
            }

        return {
            "timeframe": timeframe,
            "direction": actual_direction,
            "confirmed": False,
            "valid": False,
            "reason": "UNSUPPORTED_TIMEFRAME",
            "source_evidence": source,
        }

    # --------------------------------------------------
    # LIQUIDITY NORMALIZATION
    # --------------------------------------------------

    def normalize_liquidity(
        self,
        raw: Any,
        trade_direction: str,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        expected = self.direction(trade_direction)

        required_type = (
            "SELL_SIDE_SWEEP"
            if expected == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        sweeps = source.get(
            "liquidity_sweeps",
            source.get("sweeps", []),
        )

        matching = []

        for item in self._as_list(sweeps):

            sweep = self._as_dict(item)

            sweep_type = str(
                sweep.get("type", "")
            ).upper()

            confirmation = str(
                sweep.get("confirmation", "")
            ).upper()

            # Technical-analysis sweep labels.
            if sweep_type == "LOW_SWEEP":
                sweep_type = "SELL_SIDE_SWEEP"

            elif sweep_type == "HIGH_SWEEP":
                sweep_type = "BUY_SIDE_SWEEP"

            valid = (
                sweep_type == required_type
                and confirmation
                == "WICK_THROUGH_CLOSE_BACK_INSIDE"
                and sweep.get("invalidated") is not True
            )

            if valid:
                matching.append({
                    **sweep,
                    "type": sweep_type,
                    "direction": expected,
                    "confirmed": True,
                })

        return {
            "detected": bool(matching),
            "confirmed": bool(matching),
            "valid": bool(matching),
            "direction": expected,
            "required_sweep": required_type,
            "matching_sweeps": matching,
            "source_evidence": source,
        }

    # --------------------------------------------------
    # FVG NORMALIZATION
    # --------------------------------------------------

    def normalize_fvg(
        self,
        raw: Any,
        expected_direction: str,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        expected = self.direction(expected_direction)

        candidates = source.get(
            "fvgs",
            source.get("clean_fvgs", []),
        )

        if not candidates and (
            "lower" in source or "upper" in source
        ):
            candidates = [source]

        matching = []

        for item in self._as_list(candidates):

            zone = self._as_dict(item)

            zone_direction = self.direction(
                zone.get("direction")
            )

            lower = self._number(
                zone.get("lower", zone.get("low"))
            )

            upper = self._number(
                zone.get("upper", zone.get("high"))
            )

            clean = zone.get("clean") is True

            unmitigated = (
                zone.get("unmitigated") is True
                and zone.get("mitigated") is not True
                and zone.get("fully_mitigated") is not True
            )

            valid_bounds = (
                lower is not None
                and upper is not None
                and lower < upper
            )

            valid = (
                zone_direction == expected
                and clean
                and unmitigated
                and valid_bounds
                and zone.get("invalidated") is not True
            )

            if valid:
                matching.append({
                    **zone,
                    "direction": zone_direction,
                    "lower": lower,
                    "upper": upper,
                    "clean": True,
                    "unmitigated": True,
                    "valid": True,
                })

        selected = (
            matching[-1]
            if matching
            else None
        )

        return {
            "detected": bool(selected),
            "confirmed": bool(selected),
            "valid": bool(selected),
            "direction": expected,
            "zone": selected,
            "matching_zones": matching,
            "source_evidence": source,
        }

    # --------------------------------------------------
    # POI NORMALIZATION
    # --------------------------------------------------

    def normalize_poi(
        self,
        raw: Any,
        expected_direction: str,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        expected = self.direction(expected_direction)

        # Supports the OB engine's get_poi_evidence output.
        if (
            "order_blocks" not in source
            and "zones" not in source
            and (
                "lower" in source
                or "upper" in source
            )
        ):
            candidates = [source]

        else:
            candidates = source.get(
                "clean_order_blocks",
                source.get(
                    "order_blocks",
                    source.get("zones", []),
                ),
            )

        matching = []

        for item in self._as_list(candidates):

            zone = self._as_dict(item)

            zone_direction = self.direction(
                zone.get("direction")
            )

            lower = self._number(
                zone.get("lower", zone.get("low"))
            )

            upper = self._number(
                zone.get("upper", zone.get("high"))
            )

            clean = zone.get("clean") is True

            unmitigated = (
                zone.get("unmitigated") is True
                and zone.get("mitigated") is not True
                and zone.get("invalidated") is not True
            )

            valid_bounds = (
                lower is not None
                and upper is not None
                and lower < upper
            )

            valid = (
                zone_direction == expected
                and clean
                and unmitigated
                and valid_bounds
            )

            if valid:
                matching.append({
                    **zone,
                    "direction": zone_direction,
                    "lower": lower,
                    "upper": upper,
                    "clean": True,
                    "unmitigated": True,
                    "valid": True,
                })

        selected = (
            matching[-1]
            if matching
            else None
        )

        return {
            "detected": bool(selected),
            "confirmed": bool(selected),
            "valid": bool(selected),
            "direction": expected,
            "zone": selected,
            "matching_zones": matching,
            "source_evidence": source,
        }

    # --------------------------------------------------
    # DISPLACEMENT NORMALIZATION
    # --------------------------------------------------

    def normalize_displacement(
        self,
        raw: Any,
        expected_direction: str,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        expected = self.direction(expected_direction)

        latest = self._as_dict(
            source.get("latest_displacement")
        )

        if not latest:
            events = self._as_list(
                source.get("displacements")
            )

            aligned_events = [
                self._as_dict(item)
                for item in events
                if (
                    self.direction(
                        self._as_dict(item).get("direction")
                    ) == expected
                    and self._as_dict(item).get("confirmed") is True
                )
            ]

            if aligned_events:
                latest = aligned_events[-1]

        direction = self.direction(
            latest.get("direction")
            or source.get("direction")
        )

        confirmed = (
            latest.get("confirmed") is True
            or (
                not latest
                and source.get("confirmed") is True
            )
        )

        # Freshness must be explicitly supplied by the caller
        # or verified against the current candle index.
        freshness_verified = (
            latest.get("fresh") is True
            or latest.get("is_fresh") is True
        )

        event_index = latest.get(
            "candle_index",
            latest.get("index"),
        )

        latest_index = source.get(
            "latest_candle_index"
        )

        if (
            event_index is not None
            and latest_index is not None
        ):
            try:
                freshness_verified = (
                    int(event_index) == int(latest_index)
                )
            except (TypeError, ValueError):
                freshness_verified = False

        valid = (
            confirmed
            and direction == expected
            and freshness_verified
            and latest.get("invalidated") is not True
        )

        return {
            "detected": bool(latest),
            "confirmed": confirmed,
            "valid": valid,
            "direction": direction,
            "fresh": freshness_verified,
            "latest_displacement": latest or None,
            "reason": (
                "FRESH_DISPLACEMENT_CONFIRMED"
                if valid
                else "DISPLACEMENT_MISSING_STALE_OR_UNCONFIRMED"
            ),
            "source_evidence": source,
        }

    # --------------------------------------------------
    # ENTRY MODEL NORMALIZATION
    # --------------------------------------------------

    def normalize_entry_models(
        self,
        raw: Any,
        expected_direction: str,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        expected = self.direction(expected_direction)

        models = source.get(
            "confirmed_models",
            source.get(
                "models",
                source.get("entry_models", []),
            ),
        )

        matching = []

        for item in self._as_list(models):

            model = self._as_dict(item)

            direction = self.direction(
                model.get("direction")
            )

            confirmed = (
                model.get("confirmed") is True
                or model.get("valid") is True
            )

            freshness_verified = (
                model.get("fresh") is True
                or model.get("is_fresh") is True
            )

            event_index = model.get(
                "candle_index",
                model.get("index"),
            )

            latest_index = source.get(
                "latest_candle_index"
            )

            if (
                event_index is not None
                and latest_index is not None
            ):
                try:
                    freshness_verified = (
                        int(event_index) == int(latest_index)
                    )
                except (TypeError, ValueError):
                    freshness_verified = False

            if (
                confirmed
                and direction == expected
                and freshness_verified
                and model.get("invalidated") is not True
            ):
                matching.append({
                    **model,
                    "direction": direction,
                    "confirmed": True,
                    "fresh": True,
                })

        return {
            "detected": bool(matching),
            "confirmed": bool(matching),
            "valid": bool(matching),
            "direction": expected,
            "confirmed_models": matching,
            "confirmed_model_count": len(matching),
            "source_evidence": source,
        }

    # --------------------------------------------------
    # RISK NORMALIZATION
    # --------------------------------------------------

    def normalize_risk_checks(
        self,
        raw: Any,
    ) -> Dict[str, Any]:

        source = self._as_dict(raw)

        checks_source = self._as_dict(
            source.get("checks")
        )

        checks = {}

        for name in self.REQUIRED_RISK_CHECKS:
            checks[name] = (
                checks_source.get(name) is True
                or (
                    not checks_source
                    and source.get(name) is True
                )
            )

        failed = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        return {
            "valid": not failed,
            "checks": checks,
            "failed_checks": failed,
            "risk_reward": source.get("risk_reward"),
            "stop_loss": source.get("stop_loss"),
            "take_profit": source.get("take_profit"),
            "source_evidence": source,
        }

    # --------------------------------------------------
    # UNIFIED EVIDENCE PACKAGE
    # --------------------------------------------------

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
        risk_checks: Any,
    ) -> Dict[str, Any]:

        direction = self.direction(trade_direction)

        if direction is None:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_TRADE_DIRECTION",
                "execution_authorized": False,
            }

        h1 = self.normalize_structure(
            h1_structure,
            "H1",
            direction,
        )

        m5 = self.normalize_structure(
            m5_structure,
            "M5",
            direction,
        )

        m1 = self.normalize_structure(
            m1_structure,
            "M1",
            direction,
        )

        normalized_liquidity = self.normalize_liquidity(
            liquidity,
            direction,
        )

        normalized_fvg = self.normalize_fvg(
            fvg,
            direction,
        )

        normalized_poi = self.normalize_poi(
            poi,
            direction,
        )

        normalized_displacement = (
            self.normalize_displacement(
                displacement,
                direction,
            )
        )

        normalized_entry = self.normalize_entry_models(
            entry_models,
            direction,
        )

        normalized_risk = self.normalize_risk_checks(
            risk_checks
        )

        checks = {
            "h1_external_narrative": h1["valid"],
            "m5_external_choch": m5["valid"],
            "m1_context": m1["valid"],
            "directional_liquidity": (
                normalized_liquidity["valid"]
            ),
            "clean_poi": normalized_poi["valid"],
            "clean_fvg": normalized_fvg["valid"],
            "fresh_displacement": (
                normalized_displacement["valid"]
            ),
            "fresh_entry_model": normalized_entry["valid"],
            "risk_checks": normalized_risk["valid"],
        }

        failed = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        valid = not failed

        result = {
            "status": (
                "EVIDENCE_CONFIRMED"
                if valid
                else "EVIDENCE_REJECTED"
            ),
            "version": self.VERSION,
            "valid": valid,
            "confirmed": valid,
            "direction": direction,
            "checks": checks,
            "failed_checks": failed,
            "passed_count": sum(checks.values()),
            "total_checks": len(checks),
            "H1": h1,
            "M5": m5,
            "M1": m1,
            "liquidity": normalized_liquidity,
            "fvg": normalized_fvg,
            "poi": normalized_poi,
            "displacement": normalized_displacement,
            "entry": normalized_entry,
            "risk": normalized_risk,
            "execution_authorized": False,
        }

        self.last_result = result

        return result

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "module": "SMCIntegrationAdapter",
            "version": self.VERSION,
            "status": "READY",
            "execution_authorized": False,
        }


smc_integration_adapter = SMCIntegrationAdapter()
