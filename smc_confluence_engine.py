"""
Vrotex Bot V1
SMC Confluence Engine

Purpose:
- Evaluate independent SMC evidence.
- Detect bullish and bearish confluence.
- Identify conflicting signals.
- Evaluate H1, M5 and M1 agreement.
- Report missing confirmation.

This module does not authorize or execute trades.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class SMCConfluenceEngine:

    def __init__(self):
        self.last_result: Optional[Dict[str, Any]] = None

    @staticmethod
    def _direction(value: Any) -> str:
        if not isinstance(value, str):
            return "UNKNOWN"

        value = value.strip().upper()

        if value in ("BULLISH", "BEARISH"):
            return value

        return "UNKNOWN"

    @staticmethod
    def _confirmed(data: Any) -> bool:
        if not isinstance(data, dict):
            return False

        return any(
            data.get(field) is True
            for field in (
                "detected",
                "confirmed",
                "valid",
                "approved",
            )
        )

    def evaluate(
        self,
        h1: Dict[str, Any],
        m5: Dict[str, Any],
        m1: Dict[str, Any],
        structure: Dict[str, Any],
        liquidity: Dict[str, Any],
        poi: Dict[str, Any],
        displacement: Dict[str, Any],
        fvg: Dict[str, Any],
        entry_model: Dict[str, Any],
    ) -> Dict[str, Any]:

        inputs = {
            "h1": h1,
            "m5": m5,
            "m1": m1,
            "structure": structure,
            "liquidity": liquidity,
            "poi": poi,
            "displacement": displacement,
            "fvg": fvg,
            "entry_model": entry_model,
        }

        for name, value in inputs.items():
            if not isinstance(value, dict):
                raise ValueError(
                    f"{name} must be a dictionary"
                )

        directions = {
            "H1": self._direction(
                h1.get("direction", h1.get("bias"))
            ),
            "M5": self._direction(
                m5.get("direction", m5.get("bias"))
            ),
            "M1": self._direction(
                m1.get("direction", m1.get("bias"))
            ),
        }

        bullish = {
            "structure": (
                self._direction(
                    structure.get("direction")
                ) == "BULLISH"
            ),
            "liquidity": (
                self._direction(
                    liquidity.get("direction")
                ) == "BULLISH"
                and self._confirmed(liquidity)
            ),
            "poi": (
                self._direction(
                    poi.get("direction")
                ) == "BULLISH"
                and self._confirmed(poi)
            ),
            "displacement": (
                self._direction(
                    displacement.get("direction")
                ) == "BULLISH"
                and self._confirmed(displacement)
            ),
            "fvg": (
                self._direction(
                    fvg.get("direction")
                ) == "BULLISH"
                and self._confirmed(fvg)
            ),
            "entry_model": (
                self._direction(
                    entry_model.get("direction")
                ) == "BULLISH"
                and self._confirmed(entry_model)
            ),
        }

        bearish = {
            "structure": (
                self._direction(
                    structure.get("direction")
                ) == "BEARISH"
            ),
            "liquidity": (
                self._direction(
                    liquidity.get("direction")
                ) == "BEARISH"
                and self._confirmed(liquidity)
            ),
            "poi": (
                self._direction(
                    poi.get("direction")
                ) == "BEARISH"
                and self._confirmed(poi)
            ),
            "displacement": (
                self._direction(
                    displacement.get("direction")
                ) == "BEARISH"
                and self._confirmed(displacement)
            ),
            "fvg": (
                self._direction(
                    fvg.get("direction")
                ) == "BEARISH"
                and self._confirmed(fvg)
            ),
            "entry_model": (
                self._direction(
                    entry_model.get("direction")
                ) == "BEARISH"
                and self._confirmed(entry_model)
            ),
        }

        bullish_count = sum(bullish.values())
        bearish_count = sum(bearish.values())

        bullish_conflicts = [
            name for name, value in bearish.items()
            if value
        ]

        bearish_conflicts = [
            name for name, value in bullish.items()
            if value
        ]

        h1_m5_aligned = (
            directions["H1"] == directions["M5"]
            and directions["H1"] in ("BULLISH", "BEARISH")
        )

        m5_m1_aligned = (
            directions["M5"] == directions["M1"]
            and directions["M5"] in ("BULLISH", "BEARISH")
        )

        all_aligned = (
            directions["H1"] == directions["M5"]
            == directions["M1"]
            and directions["H1"] in ("BULLISH", "BEARISH")
        )

        conflicting_signals = (
            bullish_count > 0 and bearish_count > 0
        )

        reasons: List[str] = []

        if not h1_m5_aligned:
            reasons.append("H1_M5_CONFLICT")

        if not m5_m1_aligned:
            reasons.append("M5_M1_CONFLICT")

        if conflicting_signals:
            reasons.append("OPPOSING_SMC_EVIDENCE")

        if bullish_count == 0 and bearish_count == 0:
            reasons.append("NO_DIRECTIONAL_CONFLUENCE")

        if all_aligned:
            reasons.append("TIMEFRAMES_FULLY_ALIGNED")

        if bullish_count > bearish_count:
            dominant_direction = "BULLISH"
        elif bearish_count > bullish_count:
            dominant_direction = "BEARISH"
        else:
            dominant_direction = None

        result = {
            "status": (
                "CONFLUENCE_DETECTED"
                if (
                    all_aligned
                    and not conflicting_signals
                    and dominant_direction is not None
                )
                else "CONFLUENCE_INCOMPLETE"
            ),

            "dominant_direction": dominant_direction,

            "timeframe_directions": directions,

            "timeframes_aligned": all_aligned,

            "h1_m5_aligned": h1_m5_aligned,

            "m5_m1_aligned": m5_m1_aligned,

            "bullish_count": bullish_count,

            "bearish_count": bearish_count,

            "bullish_evidence": bullish,

            "bearish_evidence": bearish,

            "bullish_conflicts": bullish_conflicts,

            "bearish_conflicts": bearish_conflicts,

            "conflicting_signals": conflicting_signals,

            "reasons": reasons,

            "execution_authorized": False,
        }

        self.last_result = result

        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "engine": "SMC_CONFLUENCE_ENGINE",
            "initialized": True,
            "has_result": self.last_result is not None,
            "last_result": self.last_result,
        }


# Shared engine instance
smc_confluence_engine = SMCConfluenceEngine()


def evaluate_smc_confluence(
    **kwargs: Any,
) -> Dict[str, Any]:
    return smc_confluence_engine.evaluate(**kwargs)
