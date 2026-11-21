
"""
Vrotex Bot V1
SMC Entry Model Engine V3.0

Five approved M1 entry models:
1. CHoCH + FVG
2. Sweep + Engulfing
3. Breaker Retest
4. MSS + Sweep + Displacement
5. Supply-Demand Flip

Evidence producer only.
The Master SMC engine evaluates the complete setup.
The execution engine handles authorized orders.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence


class SMCEntryModelEngine:
    VERSION = "3.0"

    APPROVED_MODELS = (
        "CHOCH_FVG",
        "SWEEP_ENGULFING",
        "BREAKER_RETEST",
        "MSS_SWEEP_DISPLACEMENT",
        "SUPPLY_DEMAND_FLIP",
    )

    def __init__(
        self,
        require_fresh_evidence: bool = True,
    ):
        self.require_fresh_evidence = bool(
            require_fresh_evidence
        )
        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # NORMALIZATION
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)
            if number != number:
                return None
            return number
        except (TypeError, ValueError, OverflowError):
            return None

    def _normalize_candles(
        self,
        candles: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        normalized = []

        if not isinstance(candles, (list, tuple)):
            return normalized

        for original_index, source in enumerate(candles):
            if not isinstance(source, dict):
                continue

            open_price = self._number(source.get("open"))
            high = self._number(source.get("high"))
            low = self._number(source.get("low"))
            close = self._number(source.get("close"))

            if None in (open_price, high, low, close):
                continue

            if high < low:
                continue

            if high < max(open_price, close):
                continue

            if low > min(open_price, close):
                continue

            normalized.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "timestamp": (
                    source.get("timestamp")
                    or source.get("time")
                    or source.get("datetime")
                ),
                "original_index": original_index,
            })

        return normalized

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        direction = str(value or "").upper()

        if direction in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if direction in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    @staticmethod
    def _opposite(direction: str) -> str:
        return (
            "BEARISH"
            if direction == "BULLISH"
            else "BULLISH"
        )

    @staticmethod
    def _zone_contains(
        price: float,
        zone: Dict[str, Any],
    ) -> bool:

        lower = SMCEntryModelEngine._number(
            zone.get("lower", zone.get("low"))
        )
        upper = SMCEntryModelEngine._number(
            zone.get("upper", zone.get("high"))
        )

        if lower is None or upper is None:
            return False

        if lower > upper:
            return False

        return lower <= price <= upper

    def _event_fresh(
        self,
        event: Dict[str, Any],
        latest_index: int,
    ) -> bool:

        if event.get("fresh") is True:
            return True

        event_index = event.get(
            "candle_index",
            event.get("index"),
        )

        if event_index is None:
            return False

        try:
            return int(event_index) == latest_index
        except (TypeError, ValueError):
            return False

    def _validate_event(
        self,
        event: Any,
        direction: str,
        latest_index: int,
    ) -> bool:

        if not isinstance(event, dict):
            return False

        event_direction = self._direction(
            event.get("direction")
        )

        if event_direction != direction:
            return False

        if event.get("invalidated") is True:
            return False

        confirmed = (
            event.get("confirmed") is True
            or event.get("valid") is True
        )

        if not confirmed:
            return False

        if (
            self.require_fresh_evidence
            and not self._event_fresh(event, latest_index)
        ):
            return False

        return True

    # ---------------------------------------------------------
    # MODEL 1: CHoCH + FVG
    # ---------------------------------------------------------

    def _choch_fvg(
        self,
        direction: str,
        evidence: Dict[str, Any],
        latest_index: int,
    ) -> Dict[str, Any]:

        structure = evidence.get("choch")
        fvg = evidence.get("fvg")

        if structure is None:
            structure = evidence.get("structure_break")

        if not self._validate_event(
            structure,
            direction,
            latest_index,
        ):
            return self._failed(
                "CHOCH_FVG",
                "VALID_DIRECTIONAL_CHOCH_REQUIRED",
            )

        break_type = str(
            structure.get("type", structure.get("event", ""))
        ).upper()

        if break_type and "CHOCH" not in break_type:
            return self._failed(
                "CHOCH_FVG",
                "EVENT_IS_NOT_CHOCH",
            )

        body_close = (
            structure.get("body_close_confirmed") is True
            or structure.get("confirmation") == "BODY_CLOSE"
        )

        if not body_close:
            return self._failed(
                "CHOCH_FVG",
                "BODY_CLOSE_CONFIRMATION_REQUIRED",
            )

        if not isinstance(fvg, dict):
            return self._failed(
                "CHOCH_FVG",
                "FVG_EVIDENCE_MISSING",
            )

        if self._direction(fvg.get("direction")) != direction:
            return self._failed(
                "CHOCH_FVG",
                "FVG_DIRECTION_MISMATCH",
            )

        if fvg.get("clean") is not True:
            return self._failed(
                "CHOCH_FVG",
                "FVG_NOT_CLEAN",
            )

        if fvg.get("unmitigated") is not True:
            return self._failed(
                "CHOCH_FVG",
                "FVG_NOT_UNMITIGATED",
            )

        if fvg.get("invalidated") is True:
            return self._failed(
                "CHOCH_FVG",
                "FVG_INVALIDATED",
            )

        if not self._zone_contains(
            self._number(fvg.get("midpoint"))
            if fvg.get("midpoint") is not None
            else self._number(fvg.get("lower")),
            fvg,
        ):
            return self._failed(
                "CHOCH_FVG",
                "FVG_ZONE_INVALID",
            )

        return self._passed(
            "CHOCH_FVG",
            direction,
            {
                "choch": deepcopy(structure),
                "fvg": deepcopy(fvg),
            },
        )

    # ---------------------------------------------------------
    # MODEL 2: SWEEP + ENGULFING
    # ---------------------------------------------------------

    def _sweep_engulfing(
        self,
        direction: str,
        candles: List[Dict[str, Any]],
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        sweep = evidence.get("sweep")

        if not isinstance(sweep, dict):
            return self._failed(
                "SWEEP_ENGULFING",
                "SWEEP_EVIDENCE_MISSING",
            )

        expected_sweep = (
            "SELL_SIDE_SWEEP"
            if direction == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        sweep_type = str(
            sweep.get("type", sweep.get("sweep_type", ""))
        ).upper()

        if sweep_type != expected_sweep:
            return self._failed(
                "SWEEP_ENGULFING",
                "WRONG_LIQUIDITY_SIDE",
            )

        confirmation = str(
            sweep.get("confirmation", "")
        ).upper()

        if confirmation != "WICK_THROUGH_CLOSE_BACK_INSIDE":
            return self._failed(
                "SWEEP_ENGULFING",
                "SWEEP_CLOSE_BACK_INSIDE_REQUIRED",
            )

        if sweep.get("invalidated") is True:
            return self._failed(
                "SWEEP_ENGULFING",
                "SWEEP_INVALIDATED",
            )

        if len(candles) < 2:
            return self._failed(
                "SWEEP_ENGULFING",
                "INSUFFICIENT_CANDLES",
            )

        previous = candles[-2]
        current = candles[-1]

        if direction == "BULLISH":
            engulfing = (
                previous["close"] < previous["open"]
                and current["close"] > current["open"]
                and current["open"] <= previous["close"]
                and current["close"] >= previous["open"]
            )
        else:
            engulfing = (
                previous["close"] > previous["open"]
                and current["close"] < current["open"]
                and current["open"] >= previous["close"]
                and current["close"] <= previous["open"]
            )

        if not engulfing:
            return self._failed(
                "SWEEP_ENGULFING",
                "ENGULFING_CONFIRMATION_MISSING",
            )

        return self._passed(
            "SWEEP_ENGULFING",
            direction,
            {
                "sweep": deepcopy(sweep),
                "engulfing_confirmed": True,
                "candle_index": len(candles) - 1,
                "timestamp": current.get("timestamp"),
            },
        )

    # ---------------------------------------------------------
    # MODEL 3: BREAKER RETEST
    # ---------------------------------------------------------

    def _breaker_retest(
        self,
        direction: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        breaker = evidence.get("breaker")

        if not isinstance(breaker, dict):
            return self._failed(
                "BREAKER_RETEST",
                "BREAKER_EVIDENCE_MISSING",
            )

        if self._direction(
            breaker.get("direction")
        ) != direction:
            return self._failed(
                "BREAKER_RETEST",
                "BREAKER_DIRECTION_MISMATCH",
            )

        if breaker.get("broken") is not True:
            return self._failed(
                "BREAKER_RETEST",
                "BREAKER_NOT_CONFIRMED",
            )

        if breaker.get("active") is not True:
            return self._failed(
                "BREAKER_RETEST",
                "BREAKER_NOT_ACTIVE",
            )

        if breaker.get("retest_confirmed") is not True:
            return self._failed(
                "BREAKER_RETEST",
                "BREAKER_RETEST_NOT_CONFIRMED",
            )

        if breaker.get("invalidated") is True:
            return self._failed(
                "BREAKER_RETEST",
                "BREAKER_INVALIDATED",
            )

        retest_price = self._number(
            breaker.get("retest_price")
        )

        if retest_price is None:
            return self._failed(
                "BREAKER_RETEST",
                "RETEST_PRICE_MISSING",
            )

        if not self._zone_contains(
            retest_price,
            breaker,
        ):
            return self._failed(
                "BREAKER_RETEST",
                "RETEST_OUTSIDE_BREAKER_ZONE",
            )

        return self._passed(
            "BREAKER_RETEST",
            direction,
            {"breaker": deepcopy(breaker)},
        )

    # ---------------------------------------------------------
    # MODEL 4: MSS + SWEEP + DISPLACEMENT
    # ---------------------------------------------------------

    def _mss_sweep_displacement(
        self,
        direction: str,
        evidence: Dict[str, Any],
        latest_index: int,
    ) -> Dict[str, Any]:

        mss = evidence.get("mss")
        sweep = evidence.get("sweep")
        displacement = evidence.get("displacement")

        if not self._validate_event(
            mss,
            direction,
            latest_index,
        ):
            return self._failed(
                "MSS_SWEEP_DISPLACEMENT",
                "VALID_MSS_REQUIRED",
            )

        body_close = (
            mss.get("body_close_confirmed") is True
            or mss.get("confirmation") == "BODY_CLOSE"
        )

        if not body_close:
            return self._failed(
                "MSS_SWEEP_DISPLACEMENT",
                "MSS_BODY_CLOSE_REQUIRED",
            )

        expected_sweep = (
            "SELL_SIDE_SWEEP"
            if direction == "BULLISH"
            else "BUY_SIDE_SWEEP"
        )

        if not isinstance(sweep, dict):
            return self._failed(
                "MSS_SWEEP_DISPLACEMENT",
                "SWEEP_EVIDENCE_MISSING",
            )

        sweep_type = str(
            sweep.get("type", sweep.get("sweep_type", ""))
        ).upper()

        if sweep_type != expected_sweep:
            return self._failed(
                "MSS_SWEEP_DISPLACEMENT",
                "WRONG_LIQUIDITY_SIDE",
            )

        if (
            sweep.get("confirmation")
            != "WICK_THROUGH_CLOSE_BACK_INSIDE"
        ):
            return self._failed(
                "MSS_SWEEP_DISPLACEMENT",
                "SWEEP_CONFIRMATION_INVALID",
            )

        if not self._validate_event(
            displacement,
            direction,
            latest_index,
        ):
            return self._failed(
                "MSS_SWEEP_DISPLACEMENT",
                "VALID_DISPLACEMENT_REQUIRED",
            )

        return self._passed(
            "MSS_SWEEP_DISPLACEMENT",
            direction,
            {
                "mss": deepcopy(mss),
                "sweep": deepcopy(sweep),
                "displacement": deepcopy(displacement),
            },
        )

    # ---------------------------------------------------------
    # MODEL 5: SUPPLY-DEMAND FLIP
    # ---------------------------------------------------------

    def _supply_demand_flip(
        self,
        direction: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        flip = evidence.get("flip")

        if not isinstance(flip, dict):
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "FLIP_EVIDENCE_MISSING",
            )

        if self._direction(
            flip.get("direction")
        ) != direction:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "FLIP_DIRECTION_MISMATCH",
            )

        if flip.get("flip_confirmed") is not True:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "FLIP_NOT_CONFIRMED",
            )

        if flip.get("body_close_confirmed") is not True:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "BODY_CLOSE_REQUIRED",
            )

        if flip.get("active") is not True:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "FLIP_ZONE_NOT_ACTIVE",
            )

        if flip.get("invalidated") is True:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "FLIP_INVALIDATED",
            )

        if flip.get("retest_confirmed") is not True:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "FLIP_RETEST_REQUIRED",
            )

        retest_price = self._number(
            flip.get("retest_price")
        )

        if retest_price is None:
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "RETEST_PRICE_MISSING",
            )

        if not self._zone_contains(
            retest_price,
            flip,
        ):
            return self._failed(
                "SUPPLY_DEMAND_FLIP",
                "RETEST_OUTSIDE_FLIP_ZONE",
            )

        return self._passed(
            "SUPPLY_DEMAND_FLIP",
            direction,
            {"flip": deepcopy(flip)},
        )

    # ---------------------------------------------------------
    # RESULT HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _failed(
        model: str,
        reason: str,
    ) -> Dict[str, Any]:

        return {
            "model": model,
            "confirmed": False,
            "valid": False,
            "direction": None,
            "reason": reason,
            "evidence": {},
        }

    @staticmethod
    def _passed(
        model: str,
        direction: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:

        return {
            "model": model,
            "confirmed": True,
            "valid": True,
            "direction": direction,
            "reason": "ENTRY_MODEL_CONFIRMED",
            "evidence": evidence,
        }

    # ---------------------------------------------------------
    # EVALUATE ALL FIVE MODELS INDEPENDENTLY
    # ---------------------------------------------------------

    def evaluate_all(
        self,
        candles: Sequence[Dict[str, Any]],
        direction: str,
        evidence: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
        timeframe: str = "M1",
    ) -> Dict[str, Any]:

        normalized_direction = self._direction(direction)

        if normalized_direction is None:
            result = {
                "success": False,
                "version": self.VERSION,
                "confirmed": False,
                "valid": False,
                "reason": "INVALID_DIRECTION",
                "models": {},
                "confirmed_models": [],
                "evidence_only": True,
                "trade_authorization": False,
                "execution_authorized": False,
            }
            self.last_result = deepcopy(result)
            return result

        normalized_timeframe = str(
            timeframe or ""
        ).upper()

        if normalized_timeframe != "M1":
            result = {
                "success": False,
                "version": self.VERSION,
                "confirmed": False,
                "valid": False,
                "direction": normalized_direction,
                "symbol": symbol,
                "timeframe": normalized_timeframe,
                "reason": "ENTRY_MODELS_REQUIRE_M1",
                "models": {},
                "confirmed_models": [],
                "evidence_only": True,
                "trade_authorization": False,
                "execution_authorized": False,
            }
            self.last_result = deepcopy(result)
            return result

        normalized_candles = self._normalize_candles(
            candles
        )

        if len(normalized_candles) < 2:
            result = {
                "success": False,
                "version": self.VERSION,
                "confirmed": False,
                "valid": False,
                "direction": normalized_direction,
                "symbol": symbol,
                "timeframe": normalized_timeframe,
                "reason": "INSUFFICIENT_M1_CANDLES",
                "models": {},
                "confirmed_models": [],
                "evidence_only": True,
                "trade_authorization": False,
                "execution_authorized": False,
            }
            self.last_result = deepcopy(result)
            return result

        evidence = evidence or {}

        if not isinstance(evidence, dict):
            evidence = {}

        latest_index = len(normalized_candles) - 1

        # Each model is evaluated independently.
        # A failed model does not stop the other models.

        models = {
            "CHOCH_FVG": self._choch_fvg(
                normalized_direction,
                evidence,
                latest_index,
            ),

            "SWEEP_ENGULFING": self._sweep_engulfing(
                normalized_direction,
                normalized_candles,
                evidence,
            ),

            "BREAKER_RETEST": self._breaker_retest(
                normalized_direction,
                evidence,
            ),

            "MSS_SWEEP_DISPLACEMENT": (
                self._mss_sweep_displacement(
                    normalized_direction,
                    evidence,
                    latest_index,
                )
            ),

            "SUPPLY_DEMAND_FLIP": (
                self._supply_demand_flip(
                    normalized_direction,
                    evidence,
                )
            ),
        }

        confirmed_models = [
            name
            for name, result in models.items()
            if result.get("confirmed") is True
        ]

        result = {
            "success": True,
            "version": self.VERSION,
            "symbol": symbol,
            "timeframe": normalized_timeframe,
            "direction": normalized_direction,
            "candles_analyzed": len(normalized_candles),
            "latest_candle_index": latest_index,
            "latest_timestamp": normalized_candles[-1].get(
                "timestamp"
            ),

            "confirmed": bool(confirmed_models),
            "valid": bool(confirmed_models),

            "models": models,
            "confirmed_models": confirmed_models,
            "confirmed_model_count": len(confirmed_models),

            "reason": (
                "ENTRY_MODEL_CONFIRMED"
                if confirmed_models
                else "NO_ENTRY_MODEL_CONFIRMED"
            ),

            "evidence_only": True,
            "trade_authorization": False,
            "execution_authorized": False,
        }

        self.last_result = deepcopy(result)
        return result

    # ---------------------------------------------------------
    # COMPATIBILITY ALIASES
    # ---------------------------------------------------------

    def analyse(
        self,
        candles: Sequence[Dict[str, Any]],
        direction: str,
        evidence: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
        timeframe: str = "M1",
    ) -> Dict[str, Any]:

        return self.evaluate_all(
            candles=candles,
            direction=direction,
            evidence=evidence,
            symbol=symbol,
            timeframe=timeframe,
        )

    def analyze(
        self,
        candles: Sequence[Dict[str, Any]],
        direction: str,
        evidence: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
        timeframe: str = "M1",
    ) -> Dict[str, Any]:

        return self.evaluate_all(
            candles=candles,
            direction=direction,
            evidence=evidence,
            symbol=symbol,
            timeframe=timeframe,
        )


# -------------------------------------------------------------
# SHARED ENGINE INSTANCE
# -------------------------------------------------------------

smc_entry_model_engine = SMCEntryModelEngine()
