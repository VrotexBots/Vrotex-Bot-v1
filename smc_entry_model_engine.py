
"""
VROTEX BOT V1
SMC Entry Model Engine

Purpose:
- Validate the five approved M1 entry models.
- Require directional confirmation.
- Check candle-body confirmation where required.
- Reject incomplete or contradictory entry evidence.
- Return confirmed entry-model evidence to the master SMC engine.

Approved entry models:
1. CHoCH + FVG
2. Liquidity sweep + engulfing candle
3. Breaker retest
4. MSS + sweep + displacement
5. Supply-to-demand / demand-to-supply flip

This module does not calculate the A+ score.
This module does not authorize order execution.
"""

from typing import Any, Dict, List, Optional


class SMCEntryModelEngine:
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

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)

            if number != number:
                return None

            if number in (float("inf"), float("-inf")):
                return None

            return number
        except (TypeError, ValueError):
            return None

    def _normalise_candles(
        self,
        candles: Any,
    ) -> List[Dict[str, Any]]:
        result = []

        for candle in self._as_list(candles):
            item = self._as_dict(candle)

            open_price = self._number(
                item.get("open", item.get("OPEN"))
            )
            high = self._number(
                item.get("high", item.get("HIGH"))
            )
            low = self._number(
                item.get("low", item.get("LOW"))
            )
            close = self._number(
                item.get("close", item.get("CLOSE"))
            )

            if None in (open_price, high, low, close):
                continue

            if high < low:
                continue

            if high < max(open_price, close):
                continue

            if low > min(open_price, close):
                continue

            result.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })

        return result

    def _validate_choch_fvg(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        structure = self._as_dict(
            evidence.get("structure")
        )

        choch = self._as_dict(
            evidence.get("choch")
        )

        fvg = self._as_dict(
            evidence.get("fvg")
        )

        structure_breaks = self._as_list(
            structure.get("breaks")
        )

        choch_events = [
            event
            for event in structure_breaks
            if str(
                self._as_dict(event).get("type", "")
            ).upper() == "CHOCH"
        ]

        if choch:
            choch_events.append(choch)

        confirmed_choch = any(
            self._direction(
                self._as_dict(event).get("direction")
            ) == direction
            and (
                self._as_dict(event).get(
                    "confirmation"
                ) == "BODY_CLOSE"
                or self._as_dict(event).get(
                    "body_close_confirmed"
                ) is True
            )
            for event in choch_events
        )

        fvg_direction = self._direction(
            fvg.get("direction")
        )

        fvg_clean = (
            fvg.get("clean") is True
            or fvg.get("unmitigated") is True
        )

        fvg_valid = (
            fvg.get("invalidated") is not True
            and fvg.get("valid") is not False
        )

        confirmed = (
            confirmed_choch
            and fvg_direction == direction
            and fvg_clean
            and fvg_valid
        )

        return {
            "model": "CHOCH_FVG",
            "confirmed": confirmed,
            "direction": direction,
            "choch_confirmed": confirmed_choch,
            "fvg_confirmed": (
                fvg_direction == direction
                and fvg_clean
                and fvg_valid
            ),
        }

    def _validate_sweep_engulfing(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        sweep = self._as_dict(
            evidence.get("sweep")
        )

        candles = self._normalise_candles(
            evidence.get("candles")
        )

        expected_sweep = (
            "SELL_SIDE_SWEEP"
            if direction == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        sweep_type = str(
            sweep.get("type", "")
        ).upper()

        sweep_confirmed = (
            sweep_type == expected_sweep
            and sweep.get("confirmation")
            == "WICK_THROUGH_CLOSE_BACK_INSIDE"
        )

        engulfing = False

        if len(candles) >= 2:
            previous = candles[-2]
            current = candles[-1]

            if direction == "BULLISH":
                previous_bearish = (
                    previous["close"] < previous["open"]
                )
                current_bullish = (
                    current["close"] > current["open"]
                )

                engulfing = (
                    previous_bearish
                    and current_bullish
                    and current["open"] <= previous["close"]
                    and current["close"] >= previous["open"]
                )

            else:
                previous_bullish = (
                    previous["close"] > previous["open"]
                )
                current_bearish = (
                    current["close"] < current["open"]
                )

                engulfing = (
                    previous_bullish
                    and current_bearish
                    and current["open"] >= previous["close"]
                    and current["close"] <= previous["open"]
                )

        confirmed = sweep_confirmed and engulfing

        return {
            "model": "SWEEP_ENGULFING",
            "confirmed": confirmed,
            "direction": direction,
            "sweep_confirmed": sweep_confirmed,
            "engulfing_confirmed": engulfing,
        }

    def _validate_breaker_retest(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        breaker = self._as_dict(
            evidence.get("breaker")
        )

        breaker_direction = self._direction(
            breaker.get("direction")
        )

        lower = self._number(
            breaker.get("lower")
        )

        upper = self._number(
            breaker.get("upper")
        )

        retest_price = self._number(
            evidence.get("retest_price")
        )

        valid_zone = (
            lower is not None
            and upper is not None
            and lower < upper
        )

        retest_inside = (
            valid_zone
            and retest_price is not None
            and lower <= retest_price <= upper
        )

        confirmed = (
            breaker_direction == direction
            and breaker.get("broken") is True
            and breaker.get("confirmed") is True
            and breaker.get("active") is True
            and breaker.get("retest_confirmed") is True
            and retest_inside
        )

        return {
            "model": "BREAKER_RETEST",
            "confirmed": confirmed,
            "direction": direction,
            "retest_inside_zone": retest_inside,
        }

    def _validate_mss_sweep_displacement(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        sweep = self._as_dict(
            evidence.get("sweep")
        )

        mss = self._as_dict(
            evidence.get("mss")
        )

        displacement = self._as_dict(
            evidence.get("displacement")
        )

        expected_sweep = (
            "SELL_SIDE_SWEEP"
            if direction == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        sweep_confirmed = (
            str(sweep.get("type", "")).upper()
            == expected_sweep
            and sweep.get("confirmation")
            == "WICK_THROUGH_CLOSE_BACK_INSIDE"
        )

        mss_confirmed = (
            mss.get("confirmed") is True
            and self._direction(
                mss.get("direction")
            ) == direction
            and (
                mss.get("body_close_confirmed") is True
                or mss.get("confirmation") == "BODY_CLOSE"
            )
        )

        displacement_confirmed = (
            displacement.get("confirmed") is True
            and self._direction(
                displacement.get("direction")
            ) == direction
        )

        confirmed = (
            sweep_confirmed
            and mss_confirmed
            and displacement_confirmed
        )

        return {
            "model": "MSS_SWEEP_DISPLACEMENT",
            "confirmed": confirmed,
            "direction": direction,
            "sweep_confirmed": sweep_confirmed,
            "mss_confirmed": mss_confirmed,
            "displacement_confirmed": (
                displacement_confirmed
            ),
        }

    def _validate_supply_demand_flip(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        flip = self._as_dict(
            evidence.get("flip")
        )

        zone = self._as_dict(
            flip.get("zone")
        )

        flip_direction = self._direction(
            flip.get("direction")
        )

        lower = self._number(
            zone.get("lower")
        )

        upper = self._number(
            zone.get("upper")
        )

        valid_zone = (
            lower is not None
            and upper is not None
            and lower < upper
        )

        confirmed = (
            flip_direction == direction
            and flip.get("flip_confirmed") is True
            and flip.get("body_close_confirmed") is True
            and flip.get("active") is True
            and valid_zone
        )

        return {
            "model": "SUPPLY_DEMAND_FLIP",
            "confirmed": confirmed,
            "direction": direction,
            "valid_zone": valid_zone,
        }

    def evaluate_all(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        if not isinstance(evidence, dict):
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "INVALID_EVIDENCE",
                "execution_authorized": False,
            }

        direction = self._direction(direction)

        if direction not in self.VALID_DIRECTIONS:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_DIRECTION",
                "execution_authorized": False,
            }

        models = {
            "choch_fvg": self._validate_choch_fvg(
                self._as_dict(
                    evidence.get("choch_fvg")
                ),
                direction,
            ),
            "sweep_engulfing": self._validate_sweep_engulfing(
                self._as_dict(
                    evidence.get("sweep_engulfing")
                ),
                direction,
            ),
            "breaker_retest": self._validate_breaker_retest(
                self._as_dict(
                    evidence.get("breaker_retest")
                ),
                direction,
            ),
            "mss_sweep_displacement": (
                self._validate_mss_sweep_displacement(
                    self._as_dict(
                        evidence.get("mss_sweep_displacement")
                    ),
                    direction,
                )
            ),
            "supply_demand_flip": (
                self._validate_supply_demand_flip(
                    self._as_dict(
                        evidence.get("supply_demand_flip")
                    ),
                    direction,
                )
            ),
        }

        confirmed_models = [
            result
            for result in models.values()
            if result["confirmed"]
        ]

        return {
            "status": (
                "ENTRY_MODEL_CONFIRMED"
                if confirmed_models
                else "NO_CONFIRMED_ENTRY_MODEL"
            ),
            "version": self.VERSION,
            "valid": bool(confirmed_models),
            "confirmed": bool(confirmed_models),
            "direction": direction,
            "models": models,
            "confirmed_models": confirmed_models,
            "confirmed_model_count": len(
                confirmed_models
            ),
            "execution_authorized": False,
        }

    def analyze(
        self,
        evidence: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        return self.evaluate_all(evidence, direction)


smc_entry_model_engine = SMCEntryModelEngine()
