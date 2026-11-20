"""
VROTEX BOT V1
SMC Evidence Aggregator

Purpose:
- Collect evidence from individual SMC modules.
- Organise evidence by timeframe and category.
- Preserve original evidence for auditing.
- Detect missing and contradictory evidence.
- Produce a unified evidence package for the master SMC engine.

Approved strategy:
H1 = External narrative
M5 = Confirmation
M1 = Entry

This module does not calculate A+ scores or execute trades.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


class SMCEvidenceAggregator:
    VERSION = "2.0"

    REQUIRED_TIMEFRAMES = ("H1", "M5", "M1")

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
    def _as_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            return [value]

        return []

    def _extract_direction(
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

    def _normalise_timeframes(
        self,
        timeframe_evidence: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        result = {}

        for timeframe in self.REQUIRED_TIMEFRAMES:
            raw = self._as_dict(
                timeframe_evidence.get(timeframe)
            )

            result[timeframe] = {
                "timeframe": timeframe,
                "direction": self._extract_direction(raw),
                "structure": self._as_dict(
                    raw.get("structure")
                ),
                "breaks": self._as_list(
                    raw.get("breaks")
                ),
                "liquidity_sweeps": self._as_list(
                    raw.get("liquidity_sweeps")
                ),
                "confirmed": raw.get("confirmed"),
                "source_evidence": raw,
                "available": bool(raw),
            }

        return result

    def _collect_liquidity(
        self,
        liquidity_evidence: Any,
    ) -> Dict[str, Any]:
        source = self._as_dict(liquidity_evidence)

        sweeps = source.get(
            "liquidity_sweeps",
            source.get("sweeps", []),
        )

        targets = source.get(
            "liquidity_targets",
            source.get("targets", []),
        )

        if isinstance(sweeps, dict):
            sweeps = [sweeps]

        if isinstance(targets, dict):
            targets = [targets]

        return {
            "sweeps": self._as_list(sweeps),
            "targets": self._as_list(targets),
            "inducements": self._as_list(
                source.get("inducements", [])
            ),
            "source_evidence": source,
        }

    def _collect_zones(
        self,
        poi_evidence: Any,
        fvg_evidence: Any,
    ) -> Dict[str, Any]:
        poi = self._as_dict(poi_evidence)
        fvg = self._as_dict(fvg_evidence)

        poi_zones = poi.get(
            "order_blocks",
            poi.get("zones", []),
        )

        if not poi_zones and poi:
            poi_zones = [poi]

        fvgs = fvg.get(
            "fvgs",
            fvg.get("clean_fvgs", []),
        )

        if not fvgs and fvg:
            fvgs = [fvg]

        return {
            "poi": self._as_list(poi_zones),
            "fvg": self._as_list(fvgs),
            "poi_source": poi,
            "fvg_source": fvg,
        }

    def _collect_displacement(
        self,
        displacement_evidence: Any,
    ) -> Dict[str, Any]:
        source = self._as_dict(displacement_evidence)

        latest = source.get("latest_displacement")

        return {
            "detected": source.get("detected") is True,
            "confirmed": source.get("confirmed") is True,
            "direction": self._direction(
                source.get("direction")
                or (
                    latest.get("direction")
                    if isinstance(latest, dict)
                    else None
                )
            ),
            "latest_displacement": (
                latest if isinstance(latest, dict) else None
            ),
            "displacements": self._as_list(
                source.get("displacements", [])
            ),
            "source_evidence": source,
        }

    def _collect_entry_models(
        self,
        entry_evidence: Any,
    ) -> Dict[str, Any]:
        source = self._as_dict(entry_evidence)

        models = source.get(
            "confirmed_models",
            source.get("entry_models", []),
        )

        return {
            "confirmed_models": self._as_list(models),
            "confirmed": source.get("confirmed") is True,
            "direction": self._direction(
                source.get("direction")
            ),
            "source_evidence": source,
        }

    def _collect_risk(
        self,
        risk_evidence: Any,
    ) -> Dict[str, Any]:
        source = self._as_dict(risk_evidence)

        return {
            "valid": source.get("valid") is True,
            "checks": self._as_dict(
                source.get("checks")
            ),
            "risk_reward": source.get("risk_reward"),
            "stop_loss": source.get("stop_loss"),
            "take_profit": source.get("take_profit"),
            "source_evidence": source,
        }

    def _detect_conflicts(
        self,
        timeframes: Dict[str, Dict[str, Any]],
        expected_direction: Optional[str],
    ) -> List[str]:
        conflicts = []

        for timeframe, evidence in timeframes.items():
            direction = evidence.get("direction")

            if (
                direction is not None
                and expected_direction is not None
                and direction != expected_direction
            ):
                conflicts.append(
                    f"{timeframe}_DIRECTION_CONFLICT"
                )

        return conflicts

    def aggregate(
        self,
        timeframe_evidence: Dict[str, Any],
        liquidity_evidence: Optional[Dict[str, Any]] = None,
        poi_evidence: Optional[Dict[str, Any]] = None,
        fvg_evidence: Optional[Dict[str, Any]] = None,
        displacement_evidence: Optional[Dict[str, Any]] = None,
        entry_evidence: Optional[Dict[str, Any]] = None,
        risk_evidence: Optional[Dict[str, Any]] = None,
        expected_direction: Optional[str] = None,
        instrument: Optional[str] = None,
    ) -> Dict[str, Any]:

        if not isinstance(timeframe_evidence, dict):
            return {
                "status": "ERROR",
                "reason": "INVALID_TIMEFRAME_EVIDENCE",
                "valid": False,
            }

        direction = self._direction(expected_direction)

        if direction is None:
            direction = self._extract_direction(
                self._as_dict(timeframe_evidence.get("H1"))
            )

        timeframes = self._normalise_timeframes(
            timeframe_evidence
        )

        liquidity = self._collect_liquidity(
            liquidity_evidence
        )

        zones = self._collect_zones(
            poi_evidence,
            fvg_evidence,
        )

        displacement = self._collect_displacement(
            displacement_evidence
        )

        entry = self._collect_entry_models(
            entry_evidence
        )

        risk = self._collect_risk(
            risk_evidence
        )

        missing_timeframes = [
            timeframe
            for timeframe, evidence in timeframes.items()
            if not evidence["available"]
        ]

        conflicts = self._detect_conflicts(
            timeframes,
            direction,
        )

        valid = (
            direction is not None
            and not missing_timeframes
            and not conflicts
        )

        return {
            "status": (
                "AGGREGATED"
                if valid
                else "INCOMPLETE_OR_CONFLICTING"
            ),
            "version": self.VERSION,
            "valid": valid,
            "confirmed": False,
            "instrument": instrument,
            "direction": direction,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "timeframes": timeframes,
            "liquidity": liquidity,
            "zones": zones,
            "displacement": displacement,
            "entry": entry,
            "risk": risk,
            "missing_timeframes": missing_timeframes,
            "conflicts": conflicts,
            "evidence_count": (
                sum(
                    len(item["breaks"])
                    + len(item["liquidity_sweeps"])
                    for item in timeframes.values()
                )
                + len(liquidity["sweeps"])
                + len(zones["poi"])
                + len(zones["fvg"])
                + len(displacement["displacements"])
                + len(entry["confirmed_models"])
            ),
            "execution_authorized": False,
        }

    def analyze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.aggregate(*args, **kwargs)


smc_evidence_aggregator = SMCEvidenceAggregator()
