"""
VROTEX BOT V1
SMC Inducement Engine

Purpose:
- Identify potential inducement liquidity around swing points.
- Detect equal-high and equal-low liquidity clusters.
- Detect wick sweeps followed by candle closes back inside.
- Track whether inducement liquidity has been taken.
- Produce structured evidence for the master SMC engine.

Rules:
- A wick through a level followed by a close back inside
  is a sweep, not a confirmed structure break.
- A full candle-body close beyond a level is not classified
  as a liquidity sweep.
- Inducement detection alone does not authorize an entry.
- This module does not execute orders.
"""

from typing import Any, Dict, List, Optional


class SMCInducementEngine:
    VERSION = "2.0"

    def __init__(
        self,
        equal_level_tolerance: float = 0.0001,
        minimum_cluster_size: int = 2,
        swing_strength: int = 2,
    ):
        self.equal_level_tolerance = max(
            0.0, float(equal_level_tolerance)
        )
        self.minimum_cluster_size = max(
            2, int(minimum_cluster_size)
        )
        self.swing_strength = max(1, int(swing_strength))

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)

            if result != result or abs(result) == float("inf"):
                return None

            return result
        except (TypeError, ValueError):
            return None

    def _normalise_candles(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, float]]:
        result = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            values = {
                key: self._number(candle.get(key))
                for key in ("open", "high", "low", "close")
            }

            if any(value is None for value in values.values()):
                continue

            if values["high"] < values["low"]:
                continue

            if values["high"] < max(
                values["open"], values["close"]
            ):
                continue

            if values["low"] > min(
                values["open"], values["close"]
            ):
                continue

            result.append(values)

        return result

    def _detect_swings(
        self,
        candles: List[Dict[str, float]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        highs = []
        lows = []
        strength = self.swing_strength

        for index in range(
            strength,
            len(candles) - strength,
        ):
            current = candles[index]

            left = candles[index - strength:index]
            right = candles[index + 1:index + strength + 1]

            is_high = all(
                current["high"] > item["high"]
                for item in left + right
            )

            is_low = all(
                current["low"] < item["low"]
                for item in left + right
            )

            if is_high:
                highs.append({
                    "index": index,
                    "price": current["high"],
                    "type": "SWING_HIGH",
                })

            if is_low:
                lows.append({
                    "index": index,
                    "price": current["low"],
                    "type": "SWING_LOW",
                })

        return {
            "highs": highs,
            "lows": lows,
        }

    def _cluster_levels(
        self,
        swings: List[Dict[str, Any]],
        level_type: str,
    ) -> List[Dict[str, Any]]:
        clusters = []

        for swing in swings:
            price = swing["price"]
            matched = None

            for cluster in clusters:
                average = cluster["level"]

                if abs(price - average) <= self.equal_level_tolerance:
                    matched = cluster
                    break

            if matched is None:
                clusters.append({
                    "level": price,
                    "members": [swing],
                })
            else:
                matched["members"].append(swing)
                matched["level"] = sum(
                    item["price"]
                    for item in matched["members"]
                ) / len(matched["members"])

        result = []

        for cluster in clusters:
            if len(cluster["members"]) < self.minimum_cluster_size:
                continue

            result.append({
                "level_type": level_type,
                "level": cluster["level"],
                "touch_count": len(cluster["members"]),
                "swing_indices": [
                    item["index"]
                    for item in cluster["members"]
                ],
                "confirmed_cluster": True,
            })

        return result

    @staticmethod
    def _detect_sweep(
        candles: List[Dict[str, float]],
        level: float,
        level_type: str,
        start_index: int,
    ) -> Optional[Dict[str, Any]]:
        for index in range(
            max(0, start_index),
            len(candles),
        ):
            candle = candles[index]

            if (
                level_type == "BUY_SIDE"
                and candle["high"] > level
                and candle["close"] < level
            ):
                return {
                    "detected": True,
                    "direction": "BEARISH",
                    "type": "BUY_SIDE_SWEEP",
                    "level": level,
                    "candle_index": index,
                    "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
                }

            if (
                level_type == "SELL_SIDE"
                and candle["low"] < level
                and candle["close"] > level
            ):
                return {
                    "detected": True,
                    "direction": "BULLISH",
                    "type": "SELL_SIDE_SWEEP",
                    "level": level,
                    "candle_index": index,
                    "confirmation": "WICK_THROUGH_CLOSE_BACK_INSIDE",
                }

        return None

    def analyse(
        self,
        candles: List[Dict[str, Any]],
        current_price: Optional[float] = None,
        external_direction: str = "NEUTRAL",
    ) -> Dict[str, Any]:
        if not isinstance(candles, list):
            return {
                "status": "ERROR",
                "reason": "INVALID_CANDLE_INPUT",
            }

        normalised = self._normalise_candles(candles)

        minimum = (self.swing_strength * 2) + 3

        if len(normalised) < minimum:
            return {
                "status": "ERROR",
                "reason": "INSUFFICIENT_CANDLES",
                "candle_count": len(normalised),
                "minimum_required": minimum,
            }

        price = self._number(current_price)

        if price is None:
            price = normalised[-1]["close"]

        direction = str(external_direction or "NEUTRAL").upper()

        if direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
            direction = "NEUTRAL"

        swings = self._detect_swings(normalised)

        equal_highs = self._cluster_levels(
            swings["highs"],
            "BUY_SIDE",
        )

        equal_lows = self._cluster_levels(
            swings["lows"],
            "SELL_SIDE",
        )

        inducements = []

        for cluster in equal_highs:
            level = cluster["level"]

            if level >= price:
                inducements.append({
                    **cluster,
                    "inducement_direction": "BEARISH",
                    "position": "ABOVE_PRICE",
                })

        for cluster in equal_lows:
            level = cluster["level"]

            if level <= price:
                inducements.append({
                    **cluster,
                    "inducement_direction": "BULLISH",
                    "position": "BELOW_PRICE",
                })

        sweeps = []

        for item in inducements:
            if item["level_type"] == "BUY_SIDE":
                sweep = self._detect_sweep(
                    normalised,
                    item["level"],
                    "BUY_SIDE",
                    max(item["swing_indices"]) + 1,
                )
            else:
                sweep = self._detect_sweep(
                    normalised,
                    item["level"],
                    "SELL_SIDE",
                    max(item["swing_indices"]) + 1,
                )

            item["swept"] = sweep is not None
            item["sweep_evidence"] = sweep

            if sweep is not None:
                sweeps.append(sweep)

        relevant_sweeps = [
            item for item in sweeps
            if (
                direction == "NEUTRAL"
                or item["direction"] == direction
            )
        ]

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "external_direction": direction,
            "current_price": price,
            "swing_highs": swings["highs"],
            "swing_lows": swings["lows"],
            "equal_highs": equal_highs,
            "equal_lows": equal_lows,
            "inducements": inducements,
            "sweeps": sweeps,
            "directional_sweeps": relevant_sweeps,
            "inducement_detected": bool(inducements),
            "sweep_detected": bool(sweeps),
            "directional_sweep_detected": bool(relevant_sweeps),
            "confirmation": (
                "INDUCEMENT_SWEEP_CONFIRMED"
                if relevant_sweeps
                else "NO_DIRECTIONAL_INDUCEMENT_SWEEP"
            ),
        }

    def analyze(
        self,
        candles: List[Dict[str, Any]],
        current_price: Optional[float] = None,
        external_direction: str = "NEUTRAL",
    ) -> Dict[str, Any]:
        return self.analyse(
            candles,
            current_price,
            external_direction,
        )


smc_inducement_engine = SMCInducementEngine()
