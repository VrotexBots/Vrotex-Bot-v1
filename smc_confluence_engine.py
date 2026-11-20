
"""
VROTEX BOT V1
SMC Confluence Engine

Purpose:
- Evaluate agreement between H1, M5 and M1 evidence.
- Check directional consistency across SMC components.
- Identify missing and contradictory confluences.
- Produce structured confluence evidence for the master SMC engine.

Approved strategy:
H1 = External narrative
M5 = Confirmation
M1 = Entry

A+ scoring is handled by the master SMC engine.
This module does not authorize order execution.
"""

from typing import Any, Dict, List, Optional


class SMCConfluenceEngine:
    VERSION = "2.0"

    VALID_DIRECTIONS = ("BULLISH", "BEARISH")

    def __init__(self):
        pass

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
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").strip().upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    def _get_direction(
        self,
        evidence: Dict[str, Any],
    ) -> Optional[str]:
        direction = self._direction(
            evidence.get("direction")
        )

        if direction:
            return direction

        structure = self._as_dict(
            evidence.get("structure")
        )

        return self._direction(
            structure.get("bias")
            or structure.get("direction")
        )

    def _check_timeframes(
        self,
        timeframes: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:
        results = {}
        conflicts = []
        missing = []

        for timeframe in ("H1", "M5", "M1"):
            evidence = self._as_dict(
                timeframes.get(timeframe)
            )

            if not evidence:
                results[timeframe] = {
                    "available": False,
                    "direction": None,
                    "aligned": False,
                }
                missing.append(timeframe)
                continue

            direction = self._get_direction(evidence)

            # M1 may provide entry context without a fresh
            # structural direction or M1 BOS/CHoCH.
            if timeframe == "M1" and direction is None:
                results[timeframe] = {
                    "available": True,
                    "direction": None,
                    "aligned": True,
                    "context_only": True,
                }
                continue

            aligned = direction == expected_direction

            results[timeframe] = {
                "available": True,
                "direction": direction,
                "aligned": aligned,
            }

            if direction is None:
                missing.append(timeframe)
            elif not aligned:
                conflicts.append(
                    f"{timeframe}_DIRECTION_CONFLICT"
                )

        return {
            "results": results,
            "conflicts": conflicts,
            "missing": missing,
            "aligned": (
                "H1" not in missing
                and "M5" not in missing
                and not conflicts
            ),
        }

    def _check_m5_confirmation(
        self,
        m5_evidence: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:
        breaks = self._as_list(
            m5_evidence.get("breaks")
        )

        confirmed_choch = []

        for item in breaks:
            event = self._as_dict(item)

            event_type = str(
                event.get("type", "")
            ).upper()

            event_direction = self._direction(
                event.get("direction")
            )

            confirmation = str(
                event.get("confirmation", "")
            ).upper()

            body_close = (
                event.get("body_close_confirmed") is True
                or confirmation == "BODY_CLOSE"
            )

            if (
                event_type == "CHOCH"
                and event_direction == expected_direction
                and body_close
            ):
                confirmed_choch.append(event)

        return {
            "confirmed": bool(confirmed_choch),
            "required_event": "CHOCH",
            "confirmation_required": "BODY_CLOSE",
            "matching_events": confirmed_choch,
        }

    def _check_liquidity(
        self,
        evidence: Dict[str, Any],
        expected_direction: str,
    ) -> Dict[str, Any]:
        source = self._as_dict(evidence)

        sweeps = source.get(
            "sweeps",
            source.get("liquidity_sweeps", []),
        )

        matching_type = (
            "SELL_SIDE_SWEEP"
            if expected_direction == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        confirmed = []

        for item in self._as_list(sweeps):
            sweep = self._as_dict(item)

            sweep_type = str(
                sweep.get("type", "")
            ).upper()

            confirmation = str(
                sweep.get("confirmation", "")
            ).upper()

            valid_confirmation = (
                confirmation
                == "WICK_THROUGH_CLOSE_BACK_INSIDE"
            )

            if (
                sweep_type == matching_type
                and valid_confirmation
            ):
                confirmed.append(sweep)

        return {
            "confirmed": bool(confirmed),
            "required_sweep": matching_type,
            "matching_sweeps": confirmed,
        }

    def _check_zones(
        self,
        evidence: Any,
        expected_direction: str,
        zone_name: str,
    ) -> Dict[str, Any]:
        source = self._as_dict(evidence)

        if zone_name == "POI":
            candidates = source.get(
                "order_blocks",
                source.get("zones", []),
            )
        else:
            candidates = source.get(
                "clean_fvgs",
                source.get("fvgs", []),
            )

        if not candidates and source:
            candidates = [source]

        matching = []

        for item in self._as_list(candidates):
            zone = self._as_dict(item)

            direction = self._direction(
                zone.get("direction")
            )

            clean = (
                zone.get("clean") is True
                or zone.get("unmitigated") is True
            )

            invalidated = (
                zone.get("invalidated") is True
                or zone.get("valid") is False
            )

            if (
                direction == expected_direction
                and clean
                and not invalidated
            ):
                matching.append(zone)

        return {
            "confirmed": bool(matching),
            "matching_zones": matching,
        }

    def _check_displacement(
        self,
        evidence: Any,
        expected_direction: str,
    ) -> Dict[str, Any]:
        source = self._as_dict(evidence)

        latest = self._as_dict(
            source.get("latest_displacement")
        )

        direction = self._direction(
            source.get("direction")
            or latest.get("direction")
        )

        detected = (
            source.get("detected") is True
            or latest.get("detected") is True
        )

        confirmed = (
            source.get("confirmed") is True
            or latest.get("confirmed") is True
        )

        aligned = (
            detected
            and confirmed
            and direction == expected_direction
        )

        return {
            "confirmed": aligned,
            "detected": detected,
            "direction": direction,
        }

    def _check_entry(
        self,
        evidence: Any,
        expected_direction: str,
    ) -> Dict[str, Any]:
        source = self._as_dict(evidence)

        models = source.get(
            "confirmed_models",
            source.get("entry_models", []),
        )

        matching = []

        for item in self._as_list(models):
            model = self._as_dict(item)

            direction = self._direction(
                model.get("direction")
            )

            confirmed = (
                model.get("confirmed") is True
                or model.get("valid") is True
            )

            if (
                confirmed
                and direction == expected_direction
            ):
                matching.append(model)

        return {
            "confirmed": bool(matching),
            "matching_models": matching,
        }

    def analyze(
        self,
        evidence: Dict[str, Any],
        expected_direction: Optional[str] = None,
    ) -> Dict[str, Any]:

        if not isinstance(evidence, dict):
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "INVALID_EVIDENCE",
                "execution_authorized": False,
            }

        direction = self._direction(
            expected_direction
            or evidence.get("direction")
        )

        if direction not in self.VALID_DIRECTIONS:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "MISSING_OR_INVALID_DIRECTION",
                "execution_authorized": False,
            }

        timeframes = self._as_dict(
            evidence.get("timeframes")
        )

        if not timeframes:
            timeframes = {
                "H1": evidence.get("H1"),
                "M5": evidence.get("M5"),
                "M1": evidence.get("M1"),
            }

        timeframe_result = self._check_timeframes(
            timeframes,
            direction,
        )

        m5 = self._as_dict(
            timeframes.get("M5")
        )

        liquidity = self._check_liquidity(
            evidence.get("liquidity", {}),
            direction,
        )

        zones = self._as_dict(
            evidence.get("zones")
        )

        poi = self._check_zones(
            zones.get("poi", evidence.get("poi", {})),
            direction,
            "POI",
        )

        fvg = self._check_zones(
            zones.get("fvg", evidence.get("fvg", {})),
            direction,
            "FVG",
        )

        displacement = self._check_displacement(
            evidence.get("displacement", {}),
            direction,
        )

        entry = self._check_entry(
            evidence.get("entry", {}),
            direction,
        )

        m5_confirmation = self._check_m5_confirmation(
            m5,
            direction,
        )

        checks = {
            "timeframe_alignment": (
                timeframe_result["aligned"]
            ),
            "m5_external_choch": (
                m5_confirmation["confirmed"]
            ),
            "liquidity_sweep": liquidity["confirmed"],
            "poi": poi["confirmed"],
            "fvg": fvg["confirmed"],
            "displacement": displacement["confirmed"],
            "entry_model": entry["confirmed"],
        }

        failed_checks = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        conflicts = timeframe_result["conflicts"]

        valid = (
            not failed_checks
            and not conflicts
        )

        return {
            "status": (
                "CONFLUENCE_CONFIRMED"
                if valid
                else "CONFLUENCE_INCOMPLETE"
            ),
            "version": self.VERSION,
            "valid": valid,
            "confirmed": valid,
            "instrument": evidence.get("instrument"),
            "direction": direction,
            "checks": checks,
            "failed_checks": failed_checks,
            "missing_timeframes": (
                timeframe_result["missing"]
            ),
            "conflicts": conflicts,
            "details": {
                "timeframes": timeframe_result["results"],
                "m5_confirmation": m5_confirmation,
                "liquidity": liquidity,
                "poi": poi,
                "fvg": fvg,
                "displacement": displacement,
                "entry": entry,
            },
            "execution_authorized": False,
        }


smc_confluence_engine = SMCConfluenceEngine()
