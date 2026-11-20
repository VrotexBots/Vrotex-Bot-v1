
"""
VROTEX BOT V1
SMC Opposing Liquidity Engine

Purpose:
- Identify swing-high and swing-low liquidity.
- Detect equal highs and equal lows.
- Identify opposing liquidity targets.
- Detect wick sweeps and body-close runs.
- Provide potential liquidity targets for trade planning.

Approved strategy:
- Bullish setups target buy-side liquidity above price.
- Bearish setups target sell-side liquidity below price.
- Wick through and close back inside = sweep.
- Full candle-body close beyond a level = run/break.

This module does not authorize order execution.
"""

from typing import Any, Dict, List, Optional


class SMCOpposingLiquidityEngine:
    VERSION = "2.0"

    def __init__(
        self,
        swing_strength: int = 2,
        equal_level_tolerance: float = 0.0001,
    ):
        self.swing_strength = max(1, int(swing_strength))
        self.equal_level_tolerance = max(
            0.0,
            float(equal_level_tolerance),
        )

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

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        value = str(value or "").upper()

        if value in ("BULLISH", "BULL", "BUY"):
            return "BULLISH"

        if value in ("BEARISH", "BEAR", "SELL"):
            return "BEARISH"

        return None

    def _normalise_candles(
        self,
        candles: Any,
    ) -> List[Dict[str, Any]]:
        if not isinstance(candles, list):
            return []

        result = []

        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                continue

            open_price = self._number(
                candle.get("open", candle.get("OPEN"))
            )
            high = self._number(
                candle.get("high", candle.get("HIGH"))
            )
            low = self._number(
                candle.get("low", candle.get("LOW"))
            )
            close = self._number(
                candle.get("close", candle.get("CLOSE"))
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
                "index": index,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })

        return result

    def _find_swings(
        self,
        candles: List[Dict[str, Any]],
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

            if all(
                current["high"] > item["high"]
                for item in left + right
            ):
                highs.append({
                    "type": "BUY_SIDE_LIQUIDITY",
                    "price": current["high"],
                    "index": current["index"],
                })

            if all(
                current["low"] < item["low"]
                for item in left + right
            ):
                lows.append({
                    "type": "SELL_SIDE_LIQUIDITY",
                    "price": current["low"],
                    "index": current["index"],
                })

        return {
            "highs": highs,
            "lows": lows,
        }

    def _find_equal_levels(
        self,
        levels: List[Dict[str, Any]],
        level_type: str,
    ) -> List[Dict[str, Any]]:
        clusters = []
        used = set()

        for index, first in enumerate(levels):
            if index in used:
                continue

            cluster = [first]

            for other_index in range(
                index + 1,
                len(levels),
            ):
                if other_index in used:
                    continue

                other = levels[other_index]

                if (
                    abs(
                        first["price"] - other["price"]
                    )
                    <= self.equal_level_tolerance
                ):
                    cluster.append(other)
                    used.add(other_index)

            if len(cluster) >= 2:
                used.add(index)

                prices = [
                    item["price"]
                    for item in cluster
                ]

                clusters.append({
                    "type": level_type,
                    "price": sum(prices) / len(prices),
                    "touch_count": len(cluster),
                    "levels": cluster,
                })

        return clusters

    def _detect_latest_event(
        self,
        candles: List[Dict[str, Any]],
        targets: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not candles:
            return None

        latest = candles[-1]
        events = []

        for target in targets:
            level = target["price"]

            if target["type"] == "BUY_SIDE_LIQUIDITY":
                wick_through = latest["high"] > level
                close_beyond = latest["close"] > level

                if close_beyond:
                    event_type = "BUY_SIDE_RUN"
                elif (
                    wick_through
                    and latest["close"] <= level
                ):
                    event_type = "BUY_SIDE_SWEEP"
                else:
                    continue

            else:
                wick_through = latest["low"] < level
                close_beyond = latest["close"] < level

                if close_beyond:
                    event_type = "SELL_SIDE_RUN"
                elif (
                    wick_through
                    and latest["close"] >= level
                ):
                    event_type = "SELL_SIDE_SWEEP"
                else:
                    continue

            events.append({
                "type": event_type,
                "level": level,
                "candle_index": latest["index"],
                "confirmation": (
                    "BODY_CLOSE"
                    if "RUN" in event_type
                    else "WICK_THROUGH_CLOSE_BACK_INSIDE"
                ),
            })

        return events[-1] if events else None

    def analyze(
        self,
        candles: List[Dict[str, Any]],
        current_price: float,
        direction: str,
    ) -> Dict[str, Any]:
        direction = self._direction(direction)
        price = self._number(current_price)

        if direction is None:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_DIRECTION",
            }

        if price is None or price <= 0:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INVALID_CURRENT_PRICE",
            }

        normalized = self._normalise_candles(candles)

        minimum = (self.swing_strength * 2) + 2

        if len(normalized) < minimum:
            return {
                "status": "REJECTED",
                "valid": False,
                "reason": "INSUFFICIENT_CANDLES",
            }

        swings = self._find_swings(normalized)

        equal_highs = self._find_equal_levels(
            swings["highs"],
            "EQUAL_HIGHS",
        )

        equal_lows = self._find_equal_levels(
            swings["lows"],
            "EQUAL_LOWS",
        )

        all_targets = (
            swings["highs"] + swings["lows"]
        )

        if direction == "BULLISH":
            opposing_targets = [
                target
                for target in all_targets
                if (
                    target["type"] == "BUY_SIDE_LIQUIDITY"
                    and target["price"] > price
                )
            ]
            required_target = "BUY_SIDE_LIQUIDITY"

        else:
            opposing_targets = [
                target
                for target in all_targets
                if (
                    target["type"] == "SELL_SIDE_LIQUIDITY"
                    and target["price"] < price
                )
            ]
            required_target = "SELL_SIDE_LIQUIDITY"

        opposing_targets.sort(
            key=lambda item: (
                abs(item["price"] - price)
            )
        )

        nearest_target = (
            opposing_targets[0]
            if opposing_targets
            else None
        )

        latest_event = self._detect_latest_event(
            normalized,
            all_targets,
        )

        return {
            "status": "ANALYZED",
            "version": self.VERSION,
            "valid": True,
            "direction": direction,
            "current_price": price,
            "buy_side_liquidity": swings["highs"],
            "sell_side_liquidity": swings["lows"],
            "equal_highs": equal_highs,
            "equal_lows": equal_lows,
            "opposing_liquidity": opposing_targets,
            "nearest_opposing_target": nearest_target,
            "required_target_type": required_target,
            "latest_liquidity_event": latest_event,
            "execution_authorized": False,
        }


smc_opposing_liquidity_engine = SMCOpposingLiquidityEngine()
