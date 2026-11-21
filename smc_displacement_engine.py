
"""
Vrotex Bot V1
SMC Displacement Engine V3.0

Purpose:
- Detect confirmed bullish and bearish displacement.
- Calculate ATR using preceding candles only.
- Detect consecutive displacement sequences.
- Preserve timestamps and optional symbol/timeframe context.
- Produce structured evidence for the Master SMC engine.
- Support automatic trade authorization through the Master SMC
  and execution architecture.

IMPORTANT:
This is an evidence producer. It does not independently authorize
or execute orders. The Master SMC engine evaluates the complete
setup, and the execution engine acts on its authorization.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence


class SMCDisplacementEngine:
    VERSION = "3.0"

    def __init__(
        self,
        atr_period: int = 14,
        lookback: int = 10,
        min_body_ratio: float = 0.60,
        min_range_atr: float = 1.20,
        min_body_atr: float = 0.70,
        consecutive_minimum: int = 2,
    ):
        self.atr_period = max(2, int(atr_period))
        self.lookback = max(1, int(lookback))

        self.min_body_ratio = float(min_body_ratio)
        self.min_range_atr = float(min_range_atr)
        self.min_body_atr = float(min_body_atr)

        self.consecutive_minimum = max(
            2, int(consecutive_minimum)
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

    # ---------------------------------------------------------
    # ATR
    # ---------------------------------------------------------

    @staticmethod
    def _true_range(
        candle: Dict[str, Any],
        previous_close: Optional[float],
    ) -> float:
        high = candle["high"]
        low = candle["low"]

        if previous_close is None:
            return high - low

        return max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

    def _calculate_atr(
        self,
        candles: List[Dict[str, Any]],
        candidate_index: int,
    ) -> Optional[float]:
        """
        ATR is calculated from candles before the candidate.
        The candidate displacement candle is excluded.
        """

        start = candidate_index - self.atr_period

        if start < 0:
            return None

        ranges = []

        for position in range(start, candidate_index):
            previous_close = (
                candles[position - 1]["close"]
                if position > 0
                else None
            )

            ranges.append(
                self._true_range(
                    candles[position],
                    previous_close,
                )
            )

        if len(ranges) != self.atr_period:
            return None

        atr = sum(ranges) / len(ranges)

        return atr if atr > 0 else None

    # ---------------------------------------------------------
    # SINGLE CANDLE EVALUATION
    # ---------------------------------------------------------

    def _evaluate_candle(
        self,
        candles: List[Dict[str, Any]],
        index: int,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:

        candle = candles[index]

        open_price = candle["open"]
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]

        candle_range = high - low
        body = abs(close - open_price)

        if candle_range <= 0:
            return {
                "confirmed": False,
                "reason": "ZERO_RANGE",
                "index": index,
            }

        atr = self._calculate_atr(candles, index)

        if atr is None:
            return {
                "confirmed": False,
                "reason": "INSUFFICIENT_PRECEDING_ATR_DATA",
                "index": index,
            }

        if close > open_price:
            direction = "BULLISH"
        elif close < open_price:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        body_ratio = body / candle_range
        range_atr = candle_range / atr
        body_atr = body / atr

        body_confirmed = (
            body_ratio >= self.min_body_ratio
        )

        range_confirmed = (
            range_atr >= self.min_range_atr
        )

        body_size_confirmed = (
            body_atr >= self.min_body_atr
        )

        directional = direction in ("BULLISH", "BEARISH")

        confirmed = (
            directional
            and body_confirmed
            and range_confirmed
            and body_size_confirmed
        )

        reasons = []

        if not directional:
            reasons.append("NO_DIRECTIONAL_BODY")

        if not body_confirmed:
            reasons.append("BODY_RATIO_BELOW_THRESHOLD")

        if not range_confirmed:
            reasons.append("RANGE_BELOW_ATR_THRESHOLD")

        if not body_size_confirmed:
            reasons.append("BODY_BELOW_ATR_THRESHOLD")

        return {
            "confirmed": confirmed,
            "direction": direction,
            "index": index,
            "candle_index": index,
            "original_index": candle["original_index"],
            "timestamp": candle.get("timestamp"),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "body_size": body,
            "candle_range": candle_range,
            "atr": atr,
            "body_ratio": round(body_ratio, 6),
            "range_atr": round(range_atr, 6),
            "body_atr": round(body_atr, 6),
            "body_confirmed": body_confirmed,
            "range_confirmed": range_confirmed,
            "body_size_confirmed": body_size_confirmed,
            "reasons": reasons,
            "invalidated": False,
        }

    # ---------------------------------------------------------
    # CONSECUTIVE DISPLACEMENT
    # ---------------------------------------------------------

    def _detect_sequences(
        self,
        events: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        sequences = []
        current = []

        for event in events:
            if not event.get("confirmed"):
                if len(current) >= self.consecutive_minimum:
                    sequences.append(self._build_sequence(current))
                current = []
                continue

            if not current:
                current = [event]
                continue

            previous = current[-1]

            consecutive_index = (
                event["index"] == previous["index"] + 1
            )

            same_direction = (
                event["direction"] == previous["direction"]
            )

            if consecutive_index and same_direction:
                current.append(event)
            else:
                if len(current) >= self.consecutive_minimum:
                    sequences.append(self._build_sequence(current))

                current = [event]

        if len(current) >= self.consecutive_minimum:
            sequences.append(self._build_sequence(current))

        return sequences

    @staticmethod
    def _build_sequence(
        events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        first = events[0]
        last = events[-1]

        return {
            "confirmed": True,
            "direction": first["direction"],
            "start_index": first["index"],
            "end_index": last["index"],
            "start_timestamp": first.get("timestamp"),
            "end_timestamp": last.get("timestamp"),
            "count": len(events),
            "events": deepcopy(events),
        }

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyse(
        self,
        candles: Sequence[Dict[str, Any]],
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:

        normalized = self._normalize_candles(candles)

        if len(normalized) <= self.atr_period:
            result = self._error(
                "INSUFFICIENT_CANDLES",
                len(normalized),
            )
            self.last_result = deepcopy(result)
            return result

        first_index = max(
            self.atr_period,
            len(normalized) - self.lookback,
        )

        events = []

        for index in range(first_index, len(normalized)):
            event = self._evaluate_candle(
                normalized,
                index,
                symbol=symbol,
                timeframe=timeframe,
            )
            events.append(event)

        confirmed_events = [
            event for event in events
            if event.get("confirmed")
        ]

        bullish = [
            event for event in confirmed_events
            if event["direction"] == "BULLISH"
        ]

        bearish = [
            event for event in confirmed_events
            if event["direction"] == "BEARISH"
        ]

        sequences = self._detect_sequences(events)

        bullish_sequences = [
            sequence for sequence in sequences
            if sequence["direction"] == "BULLISH"
        ]

        bearish_sequences = [
            sequence for sequence in sequences
            if sequence["direction"] == "BEARISH"
        ]

        latest = (
            confirmed_events[-1]
            if confirmed_events
            else None
        )

        latest_is_current = bool(
            latest
            and latest["index"] == len(normalized) - 1
        )

        latest_evidence = None

        if latest:
            latest_evidence = deepcopy(latest)
            latest_evidence["fresh"] = latest_is_current
            latest_evidence["candle_index"] = latest["index"]
            latest_evidence["invalidated"] = False
            latest_evidence["confirmation"] = (
                "BODY_DISPLACEMENT"
            )

        result = {
            "success": True,
            "version": self.VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "candles_analyzed": len(normalized),
            "lookback": self.lookback,
            "atr_period": self.atr_period,

            "detected": bool(confirmed_events),
            "confirmed": bool(latest),
            "direction": (
                latest["direction"] if latest else None
            ),

            "index": (
                latest["index"] if latest else None
            ),
            "candle_index": (
                latest["index"] if latest else None
            ),

            "fresh": latest_is_current,
            "confirmation": (
                "BODY_DISPLACEMENT" if latest else None
            ),
            "invalidated": False,

            "latest_displacement": latest_evidence,
            "displacements": deepcopy(confirmed_events),
            "bullish_displacements": deepcopy(bullish),
            "bearish_displacements": deepcopy(bearish),

            "sequences": deepcopy(sequences),
            "bullish_sequences": deepcopy(bullish_sequences),
            "bearish_sequences": deepcopy(bearish_sequences),

            "sequence_detected": bool(sequences),
            "evidence_only": True,
            "trade_authorization": False,
            "execution_authorized": False,
            "reason": (
                "DISPLACEMENT_CONFIRMED"
                if latest
                else "NO_CONFIRMED_DISPLACEMENT"
            ),
        }

        self.last_result = deepcopy(result)
        return result

    # ---------------------------------------------------------
    # AMERICAN SPELLING COMPATIBILITY
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Sequence[Dict[str, Any]],
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, Any]:

        return self.analyse(
            candles=candles,
            symbol=symbol,
            timeframe=timeframe,
        )

    # ---------------------------------------------------------
    # DIRECTIONAL VALIDATION
    # ---------------------------------------------------------

    def validate_displacement(
        self,
        analysis: Dict[str, Any],
        expected_direction: str,
        require_fresh: bool = False,
    ) -> Dict[str, Any]:

        expected = str(
            expected_direction or ""
        ).upper()

        if expected not in ("BULLISH", "BEARISH"):
            return {
                "valid": False,
                "confirmed": False,
                "reason": "INVALID_EXPECTED_DIRECTION",
                "direction": expected,
            }

        if not isinstance(analysis, dict):
            return {
                "valid": False,
                "confirmed": False,
                "reason": "INVALID_ANALYSIS",
                "direction": expected,
            }

        events = analysis.get("displacements", [])

        if not isinstance(events, list):
            events = []

        matching = [
            event for event in events
            if (
                isinstance(event, dict)
                and event.get("confirmed") is True
                and event.get("direction") == expected
                and event.get("invalidated") is not True
            )
        ]

        latest = matching[-1] if matching else None

        if latest is None:
            return {
                "valid": False,
                "confirmed": False,
                "reason": "NO_MATCHING_DIRECTIONAL_DISPLACEMENT",
                "direction": expected,
                "matching_events": [],
            }

        latest_index = latest.get(
            "index",
            latest.get("candle_index"),
        )

        analysis_current_index = (
            analysis.get("candles_analyzed", 0) - 1
        )

        fresh = (
            latest_index == analysis_current_index
        )

        if require_fresh and not fresh:
            return {
                "valid": False,
                "confirmed": False,
                "reason": "DISPLACEMENT_NOT_FRESH",
                "direction": expected,
                "fresh": False,
                "latest": deepcopy(latest),
                "matching_events": deepcopy(matching),
            }

        evidence = deepcopy(latest)
        evidence["fresh"] = fresh
        evidence["candle_index"] = latest_index
        evidence["confirmation"] = "BODY_DISPLACEMENT"
        evidence["invalidated"] = False

        return {
            "valid": True,
            "confirmed": True,
            "direction": expected,
            "index": latest_index,
            "candle_index": latest_index,
            "fresh": fresh,
            "confirmation": "BODY_DISPLACEMENT",
            "invalidated": False,
            "latest": evidence,
            "matching_events": deepcopy(matching),
            "reason": "DIRECTIONAL_DISPLACEMENT_VALIDATED",
        }

    # ---------------------------------------------------------
    # ERROR RESPONSE
    # ---------------------------------------------------------

    @staticmethod
    def _error(
        reason: str,
        candle_count: int = 0,
    ) -> Dict[str, Any]:

        return {
            "success": False,
            "version": SMCDisplacementEngine.VERSION,
            "detected": False,
            "confirmed": False,
            "direction": None,
            "index": None,
            "candle_index": None,
            "fresh": False,
            "confirmation": None,
            "invalidated": False,
            "latest_displacement": None,
            "displacements": [],
            "bullish_displacements": [],
            "bearish_displacements": [],
            "sequences": [],
            "bullish_sequences": [],
            "bearish_sequences": [],
            "sequence_detected": False,
            "candles_analyzed": candle_count,
            "evidence_only": True,
            "trade_authorization": False,
            "execution_authorized": False,
            "reason": reason,
        }


# -------------------------------------------------------------
# SHARED ENGINE INSTANCE
# -------------------------------------------------------------

smc_displacement_engine = SMCDisplacementEngine()
