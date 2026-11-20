
"""
VROTEX BOT V1
SMC ENTRY MODEL ENGINE

Evaluates approved M1 entry models.
This module identifies evidence only.
It does not authorize or execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCEntryModelEngine:

    MODELS = (
        "CHOCH_FVG",
        "SWEEP_ENGULFING",
        "BREAKER_RETEST",
        "MSS_SWEEP_DISPLACEMENT",
        "SUPPLY_DEMAND_FLIP",
    )

    def __init__(self):
        self.last_result: Dict[str, Any] = {}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result or result in (
                float("inf"), float("-inf")
            ):
                return None
            return result
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _direction(value: Any) -> str:
        value = str(value or "").upper()
        return value if value in ("BULLISH", "BEARISH") else "NONE"

    def _validate_common(
        self,
        direction: str,
        candles: List[Dict[str, Any]],
    ) -> Optional[str]:

        if direction not in ("BULLISH", "BEARISH"):
            return "INVALID_DIRECTION"

        if not isinstance(candles, list) or len(candles) < 3:
            return "INSUFFICIENT_CANDLES"

        return None

    def _last_candles(
        self,
        candles: List[Dict[str, Any]],
        count: int = 3,
    ) -> Optional[List[Dict[str, float]]]:

        result = []

        for candle in candles[-count:]:
            if not isinstance(candle, dict):
                return None

            values = {
                key: self._number(candle.get(key))
                for key in ("open", "high", "low", "close")
            }

            if any(value is None for value in values.values()):
                return None

            if values["high"] < max(
                values["open"], values["close"]
            ):
                return None

            if values["low"] > min(
                values["open"], values["close"]
            ):
                return None

            if values["high"] < values["low"]:
                return None

            result.append(values)

        return result

    def validate_choch_fvg(
        self,
        direction: str,
        structure: Dict[str, Any],
        fvg: Dict[str, Any],
    ) -> Dict[str, Any]:

        structure_direction = self._direction(
            structure.get("direction")
        )

        fvg_direction = self._direction(
            fvg.get("direction")
        )

        body_close = structure.get(
            "body_close_confirmed", False
        )

        structure_confirmed = (
            structure.get("confirmed", False)
            or structure.get("choch_confirmed", False)
        )

        fvg_confirmed = (
            fvg.get("confirmed", False)
            or fvg.get("valid", False)
        )

        passed = (
            structure_direction == direction
            and fvg_direction == direction
            and structure_confirmed
            and body_close is True
            and fvg_confirmed
            and fvg.get("mitigated") is not True
            and fvg.get("clean") is not False
        )

        return self._result(
            "CHOCH_FVG",
            direction,
            passed,
            {
                "structure_confirmed": structure_confirmed,
                "body_close_confirmed": body_close is True,
                "fvg_confirmed": fvg_confirmed,
                "fvg_unmitigated": fvg.get("mitigated") is not True,
            },
        )

    def validate_sweep_engulfing(
        self,
        direction: str,
        candles: List[Dict[str, Any]],
        sweep: Dict[str, Any],
    ) -> Dict[str, Any]:

        error = self._validate_common(direction, candles)

        if error:
            return self._result(
                "SWEEP_ENGULFING", direction, False,
                {"error": error}
            )

        data = self._last_candles(candles, 2)

        if not data:
            return self._result(
                "SWEEP_ENGULFING", direction, False,
                {"error": "INVALID_CANDLE_DATA"}
            )

        previous, current = data

        sweep_direction = self._direction(
            sweep.get("direction")
        )

        sweep_confirmed = (
            sweep.get("detected", False)
            and sweep.get("valid", True)
        )

        if direction == "BULLISH":
            engulfing = (
                current["close"] > current["open"]
                and previous["close"] < previous["open"]
                and current["open"] <= previous["close"]
                and current["close"] >= previous["open"]
            )
        else:
            engulfing = (
                current["close"] < current["open"]
                and previous["close"] > previous["open"]
                and current["open"] >= previous["close"]
                and current["close"] <= previous["open"]
            )

        passed = (
            sweep_confirmed
            and sweep_direction == direction
            and engulfing
        )

        return self._result(
            "SWEEP_ENGULFING",
            direction,
            passed,
            {
                "sweep_confirmed": sweep_confirmed,
                "engulfing_confirmed": engulfing,
            },
        )

    def validate_breaker_retest(
        self,
        direction: str,
        breaker: Dict[str, Any],
        price: float,
    ) -> Dict[str, Any]:

        price = self._number(price)

        if price is None:
            return self._result(
                "BREAKER_RETEST", direction, False,
                {"error": "INVALID_PRICE"}
            )

        breaker_direction = self._direction(
            breaker.get("direction")
        )

        lower = self._number(breaker.get("lower"))
        upper = self._number(breaker.get("upper"))

        if lower is None or upper is None or lower >= upper:
            return self._result(
                "BREAKER_RETEST", direction, False,
                {"error": "INVALID_BREAKER_ZONE"}
            )

        retest = (
            lower <= price <= upper
        )

        broken = breaker.get("broken", False)
        confirmed = breaker.get("confirmed", False)
        active = breaker.get("active", True)

        passed = (
            breaker_direction == direction
            and broken is True
            and confirmed is True
            and active is True
            and retest
        )

        return self._result(
            "BREAKER_RETEST",
            direction,
            passed,
            {
                "breaker_broken": broken,
                "breaker_confirmed": confirmed,
                "breaker_active": active,
                "price_in_zone": retest,
            },
        )

    def validate_mss_sweep_displacement(
        self,
        direction: str,
        sweep: Dict[str, Any],
        mss: Dict[str, Any],
        displacement: Dict[str, Any],
    ) -> Dict[str, Any]:

        sweep_direction = self._direction(
            sweep.get("direction")
        )

        mss_direction = self._direction(
            mss.get("direction")
        )

        displacement_direction = self._direction(
            displacement.get("direction")
        )

        sweep_confirmed = sweep.get("detected", False)
        mss_confirmed = (
            mss.get("confirmed", False)
            and mss.get("body_close_confirmed", False)
        )

        displacement_confirmed = (
            displacement.get("detected", False)
            or displacement.get("confirmed", False)
        )

        passed = (
            sweep_confirmed is True
            and sweep_direction == direction
            and mss_confirmed is True
            and mss_direction == direction
            and displacement_confirmed is True
            and displacement_direction == direction
        )

        return self._result(
            "MSS_SWEEP_DISPLACEMENT",
            direction,
            passed,
            {
                "sweep_confirmed": sweep_confirmed,
                "mss_confirmed": mss_confirmed,
                "displacement_confirmed": displacement_confirmed,
            },
        )

    def validate_supply_demand_flip(
        self,
        direction: str,
        zone: Dict[str, Any],
        price: float,
    ) -> Dict[str, Any]:

        price = self._number(price)

        if price is None:
            return self._result(
                "SUPPLY_DEMAND_FLIP", direction, False,
                {"error": "INVALID_PRICE"}
            )

        lower = self._number(zone.get("lower"))
        upper = self._number(zone.get("upper"))

        if lower is None or upper is None or lower >= upper:
            return self._result(
                "SUPPLY_DEMAND_FLIP", direction, False,
                {"error": "INVALID_ZONE"}
            )

        flip_direction = self._direction(
            zone.get("direction")
        )

        retested = lower <= price <= upper

        valid_flip = (
            zone.get("flip_confirmed", False) is True
            and zone.get("body_close_confirmed", False) is True
            and zone.get("active", True) is True
        )

        passed = (
            flip_direction == direction
            and valid_flip
            and retested
        )

        return self._result(
            "SUPPLY_DEMAND_FLIP",
            direction,
            passed,
            {
                "flip_confirmed": valid_flip,
                "price_in_zone": retested,
            },
        )

    def evaluate_all(
        self,
        direction: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        direction = self._direction(direction)

        if direction == "NONE":
            return {
                "valid": False,
                "status": "INVALID_DIRECTION",
                "models": {},
                "confirmed_models": [],
            }

        evidence = evidence or {}

        results = {
            "CHOCH_FVG": self.validate_choch_fvg(
                direction,
                evidence.get("structure", {}),
                evidence.get("fvg", {}),
            ),
            "SWEEP_ENGULFING": self.validate_sweep_engulfing(
                direction,
                evidence.get("candles", []),
                evidence.get("sweep", {}),
            ),
            "BREAKER_RETEST": self.validate_breaker_retest(
                direction,
                evidence.get("breaker", {}),
                evidence.get("price"),
            ),
            "MSS_SWEEP_DISPLACEMENT":
                self.validate_mss_sweep_displacement(
                    direction,
                    evidence.get("sweep", {}),
                    evidence.get("mss", {}),
                    evidence.get("displacement", {}),
                ),
            "SUPPLY_DEMAND_FLIP":
                self.validate_supply_demand_flip(
                    direction,
                    evidence.get("flip_zone", {}),
                    evidence.get("price"),
                ),
        }

        confirmed = [
            name
            for name, result in results.items()
            if result["confirmed"]
        ]

        output = {
            "valid": True,
            "status": "ENTRY_MODE_ANALYSIS_COMPLETE",
            "direction": direction,
            "models": results,
            "confirmed_models": confirmed,
            "confirmed_count": len(confirmed),
            "entry_model_confirmed": len(confirmed) > 0,
            "execution_authorized": False,
        }

        self.last_result = output
        return output

    @staticmethod
    def _result(
        model: str,
        direction: str,
        confirmed: bool,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        return {
            "model": model,
            "direction": direction,
            "confirmed": bool(confirmed),
            "evidence": evidence,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "module": "SMCEntryModelEngine",
            "supported_models": list(self.MODELS),
            "last_result": self.last_result,
        }


smc_entry_model_engine = SMCEntryModelEngine()
