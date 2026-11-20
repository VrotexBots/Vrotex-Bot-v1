"""
VROTEX BOT V1
SMC Breaker Engine

Purpose:
- Identify potential bullish and bearish breaker blocks.
- Require a full candle-body close through the original zone.
- Track retests of broken zones.
- Distinguish confirmed breakers from unconfirmed candidates.
- Return structured evidence for the master SMC engine.

Rules:
- A wick through a zone is not a confirmed breaker.
- A bullish breaker requires a bearish-origin zone broken upward.
- A bearish breaker requires a bullish-origin zone broken downward.
- A retest must interact with the broken zone.
- This module does not authorize or execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCBreakerEngine:
    VERSION = "2.0"

    def __init__(self, require_retest: bool = True):
        self.require_retest = bool(require_retest)

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result or abs(result) == float("inf"):
                return None
            return result
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    def _normalise_zone(
        self,
        zone: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(zone, dict):
            return None

        lower = self._number(zone.get("lower", zone.get("low")))
        upper = self._number(zone.get("upper", zone.get("high")))

        origin = self._direction(
            zone.get("origin_direction", zone.get("direction"))
        )

        if lower is None or upper is None or lower >= upper:
            return None

        if origin is None:
            return None

        return {
            "zone_id": zone.get("zone_id", zone.get("id")),
            "lower": lower,
            "upper": upper,
            "origin_direction": origin,
            "zone_type": str(
                zone.get("zone_type", zone.get("type", "UNKNOWN"))
            ).upper(),
        }

    @staticmethod
    def _normalise_candles(
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        result = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            values = {}

            for key in ("open", "high", "low", "close"):
                try:
                    value = float(candle[key])
                except (KeyError, TypeError, ValueError):
                    values = {}
                    break

                if value != value or abs(value) == float("inf"):
                    values = {}
                    break

                values[key] = value

            if not values:
                continue

            if values["high"] < values["low"]:
                continue

            if values["high"] < max(values["open"], values["close"]):
                continue

            if values["low"] > min(values["open"], values["close"]):
                continue

            result.append(values)

        return result

    @staticmethod
    def _detect_break(
        candle: Dict[str, float],
        zone: Dict[str, Any],
    ) -> Optional[str]:
        if (
            zone["origin_direction"] == "BEARISH"
            and candle["open"] <= zone["upper"]
            and candle["close"] > zone["upper"]
            and candle["close"] > candle["open"]
        ):
            return "BULLISH"

        if (
            zone["origin_direction"] == "BULLISH"
            and candle["open"] >= zone["lower"]
            and candle["close"] < zone["lower"]
            and candle["close"] < candle["open"]
        ):
            return "BEARISH"

        return None

    @staticmethod
    def _retest(
        candle: Dict[str, float],
        zone: Dict[str, Any],
        breaker_direction: str,
    ) -> bool:
        overlaps = (
            candle["high"] >= zone["lower"]
            and candle["low"] <= zone["upper"]
        )

        if not overlaps:
            return False

        if breaker_direction == "BULLISH":
            return candle["close"] >= zone["lower"]

        return candle["close"] <= zone["upper"]

    def analyse_zone(
        self,
        zone: Dict[str, Any],
        candles: List[Dict[str, Any]],
        formation_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalised_zone = self._normalise_zone(zone)

        if normalised_zone is None:
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "INVALID_BREAKER_ZONE",
            }

        normalised_candles = self._normalise_candles(candles)

        if not normalised_candles:
            return {
                "status": "ERROR",
                "valid": False,
                "reason": "NO_VALID_CANDLES",
            }

        if formation_index is None:
            start_index = 0
        else:
            try:
                formation_index = int(formation_index)
            except (TypeError, ValueError):
                return {
                    "status": "ERROR",
                    "valid": False,
                    "reason": "INVALID_FORMATION_INDEX",
                }

            if (
                formation_index < -1
                or formation_index >= len(normalised_candles)
            ):
                return {
                    "status": "ERROR",
                    "valid": False,
                    "reason": "FORMATION_INDEX_OUT_OF_RANGE",
                }

            start_index = formation_index + 1

        break_index = None
        breaker_direction = None
        retest_index = None
        events = []

        for index in range(start_index, len(normalised_candles)):
            candle = normalised_candles[index]

            if break_index is None:
                detected_direction = self._detect_break(
                    candle,
                    normalised_zone,
                )

                if detected_direction is None:
                    continue

                break_index = index
                breaker_direction = detected_direction

                events.append({
                    "index": index,
                    "event": "BODY_CLOSE_BREAK",
                    "direction": detected_direction,
                    "close": candle["close"],
                })

                continue

            if index <= break_index:
                continue

            if self._retest(
                candle,
                normalised_zone,
                breaker_direction,
            ):
                retest_index = index

                events.append({
                    "index": index,
                    "event": "RETEST",
                    "direction": breaker_direction,
                })

                break

        broken = break_index is not None
        retested = retest_index is not None

        confirmed = (
            broken
            and (retested or not self.require_retest)
        )

        if not broken:
            status = "UNBROKEN"
        elif confirmed:
            status = "CONFIRMED_BREAKER"
        elif self.require_retest:
            status = "BROKEN_AWAITING_RETEST"
        else:
            status = "BROKEN_NO_RETEST_REQUIRED"

        return {
            "status": status,
            "version": self.VERSION,
            "valid": True,
            "zone_id": normalised_zone["zone_id"],
            "zone_type": normalised_zone["zone_type"],
            "lower": normalised_zone["lower"],
            "upper": normalised_zone["upper"],
            "origin_direction": normalised_zone["origin_direction"],
            "direction": breaker_direction,
            "broken": broken,
            "break_index": break_index,
            "body_close_confirmed": broken,
            "retested": retested,
            "retest_index": retest_index,
            "confirmed": confirmed,
            "active": confirmed,
            "events": events,
            "confirmation": status,
        }

    def analyse(
        self,
        zones: List[Dict[str, Any]],
        candles: List[Dict[str, Any]],
        formation_indices: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(zones, list):
            return {
                "status": "ERROR",
                "reason": "INVALID_ZONES_INPUT",
                "breakers": [],
            }

        results = []

        for index, zone in enumerate(zones):
            formation_index = None

            if formation_indices is not None and index < len(formation_indices):
                formation_index = formation_indices[index]

            results.append(
                self.analyse_zone(
                    zone,
                    candles,
                    formation_index,
                )
            )

        confirmed = [
            item for item in results
            if item.get("confirmed")
        ]

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "zone_count": len(results),
            "confirmed": bool(confirmed),
            "bullish_breakers": [
                item for item in confirmed
                if item.get("direction") == "BULLISH"
            ],
            "bearish_breakers": [
                item for item in confirmed
                if item.get("direction") == "BEARISH"
            ],
            "awaiting_retest": [
                item for item in results
                if item.get("status") == "BROKEN_AWAITING_RETEST"
            ],
            "breakers": results,
        }

    def analyze(
        self,
        zones: List[Dict[str, Any]],
        candles: List[Dict[str, Any]],
        formation_indices: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        return self.analyse(zones, candles, formation_indices)


smc_breaker_engine = SMCBreakerEngine()
