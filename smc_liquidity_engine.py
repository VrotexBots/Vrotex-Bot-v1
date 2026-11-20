
"""
VROTEX BOT V1
SMC Liquidity Engine
Version 2.0

Responsibilities:
- Detect swing-high and swing-low liquidity.
- Identify equal highs and equal lows.
- Detect buy-side and sell-side liquidity sweeps.
- Require wick-through and close-back-inside confirmation.
- Identify liquidity targets relative to trade direction.

A wick through a level alone is not a confirmed structure break.
A sweep requires price to return and close inside the level.

This module does not execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCLiquidityEngine:

    VERSION = "2.0"

    def __init__(
        self,
        swing_left: int = 2,
        swing_right: int = 2,
        equal_tolerance: float = 0.0001
    ):
        self.swing_left = max(1, int(swing_left))
        self.swing_right = max(1, int(swing_right))
        self.equal_tolerance = max(
            0.0, float(equal_tolerance)
        )

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # CANDLE VALIDATION
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result:
                return None
            return result
        except (TypeError, ValueError):
            return None

    def _validate_candles(
        self,
        candles: Any
    ) -> List[Dict[str, float]]:

        if not isinstance(candles, list):
            return []

        validated = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            high = self._number(candle.get("high"))
            low = self._number(candle.get("low"))
            open_price = self._number(candle.get("open"))
            close = self._number(candle.get("close"))

            if None in (
                high, low, open_price, close
            ):
                continue

            if high < low:
                continue

            if (
                open_price < low
                or open_price > high
                or close < low
                or close > high
            ):
                continue

            validated.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close
            })

        return validated

    # ---------------------------------------------------------
    # SWING DETECTION
    # ---------------------------------------------------------

    def _detect_swing_highs(
        self,
        candles: List[Dict[str, float]]
    ) -> List[Dict[str, Any]]:

        swings = []
        count = len(candles)

        for index in range(
            self.swing_left,
            count - self.swing_right
        ):
            current = candles[index]
            left = candles[
                index - self.swing_left:index
            ]
            right = candles[
                index + 1:index + self.swing_right + 1
            ]

            if not left or not right:
                continue

            is_swing = (
                current["high"] > max(
                    item["high"] for item in left
                )
                and current["high"] >= max(
                    item["high"] for item in right
                )
            )

            if is_swing:
                swings.append({
                    "index": index,
                    "price": current["high"],
                    "type": "SWING_HIGH"
                })

        return swings

    def _detect_swing_lows(
        self,
        candles: List[Dict[str, float]]
    ) -> List[Dict[str, Any]]:

        swings = []
        count = len(candles)

        for index in range(
            self.swing_left,
            count - self.swing_right
        ):
            current = candles[index]
            left = candles[
                index - self.swing_left:index
            ]
            right = candles[
                index + 1:index + self.swing_right + 1
            ]

            if not left or not right:
                continue

            is_swing = (
                current["low"] < min(
                    item["low"] for item in left
                )
                and current["low"] <= min(
                    item["low"] for item in right
                )
            )

            if is_swing:
                swings.append({
                    "index": index,
                    "price": current["low"],
                    "type": "SWING_LOW"
                })

        return swings

    # ---------------------------------------------------------
    # EQUAL HIGH / LOW CLUSTERS
    # ---------------------------------------------------------

    def _group_equal_levels(
        self,
        swings: List[Dict[str, Any]],
        level_type: str
    ) -> List[Dict[str, Any]]:

        groups = []

        for swing in swings:
            price = swing["price"]
            matched = None

            for group in groups:
                reference = group["level"]

                if abs(price - reference) <= self.equal_tolerance:
                    matched = group
                    break

            if matched is None:
                groups.append({
                    "level": price,
                    "touches": 1,
                    "indices": [swing["index"]],
                    "type": level_type
                })
            else:
                matched["touches"] += 1
                matched["indices"].append(
                    swing["index"]
                )

                # Keep the average of the clustered levels.
                matched["level"] = sum(
                    [
                        next(
                            item["price"]
                            for item in swings
                            if item["index"] == idx
                        )
                        for idx in matched["indices"]
                    ]
                ) / matched["touches"]

        return [
            group for group in groups
            if group["touches"] >= 2
        ]

    # ---------------------------------------------------------
    # LIQUIDITY SWEEP DETECTION
    # ---------------------------------------------------------

    def _detect_sweeps(
        self,
        candles: List[Dict[str, float]],
        swing_highs: List[Dict[str, Any]],
        swing_lows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:

        if len(candles) < 2:
            return []

        last_index = len(candles) - 1
        last = candles[-1]

        sweeps = []

        # Only levels formed before the current candle
        # can be swept by the current candle.
        for swing in swing_highs:
            if swing["index"] >= last_index:
                continue

            level = swing["price"]

            wick_through = last["high"] > level
            close_back_inside = last["close"] < level

            if wick_through and close_back_inside:
                sweeps.append({
                    "type": "BUY_SIDE_SWEEP",
                    "level": level,
                    "candle_index": last_index,
                    "confirmation":
                        "WICK_THROUGH_CLOSE_BACK_INSIDE",
                    "wick_through": True,
                    "close_back_inside": True
                })

        for swing in swing_lows:
            if swing["index"] >= last_index:
                continue

            level = swing["price"]

            wick_through = last["low"] < level
            close_back_inside = last["close"] > level

            if wick_through and close_back_inside:
                sweeps.append({
                    "type": "SELL_SIDE_SWEEP",
                    "level": level,
                    "candle_index": last_index,
                    "confirmation":
                        "WICK_THROUGH_CLOSE_BACK_INSIDE",
                    "wick_through": True,
                    "close_back_inside": True
                })

        return sweeps

    # ---------------------------------------------------------
    # LIQUIDITY TARGETS
    # ---------------------------------------------------------

    def _build_targets(
        self,
        swing_highs: List[Dict[str, Any]],
        swing_lows: List[Dict[str, Any]],
        current_price: float
    ) -> Dict[str, List[Dict[str, Any]]]:

        buy_side = []
        sell_side = []

        for swing in swing_highs:
            price = swing["price"]

            if price > current_price:
                buy_side.append({
                    "type": "BUY_SIDE_LIQUIDITY",
                    "level": price,
                    "swing_index": swing["index"],
                    "status": "UNSWEPT"
                })

        for swing in swing_lows:
            price = swing["price"]

            if price < current_price:
                sell_side.append({
                    "type": "SELL_SIDE_LIQUIDITY",
                    "level": price,
                    "swing_index": swing["index"],
                    "status": "UNSWEPT"
                })

        buy_side.sort(
            key=lambda item: item["level"]
        )

        sell_side.sort(
            key=lambda item: item["level"],
            reverse=True
        )

        return {
            "buy_side": buy_side,
            "sell_side": sell_side
        }

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Any,
        current_price: Optional[float] = None,
        tolerance: Optional[float] = None
    ) -> Dict[str, Any]:

        original_tolerance = self.equal_tolerance

        if tolerance is not None:
            try:
                self.equal_tolerance = max(
                    0.0, float(tolerance)
                )
            except (TypeError, ValueError):
                self.equal_tolerance = original_tolerance

        try:
            validated = self._validate_candles(candles)

            if len(validated) < (
                self.swing_left
                + self.swing_right
                + 2
            ):
                result = {
                    "status": "INSUFFICIENT_DATA",
                    "version": self.VERSION,
                    "swing_highs": [],
                    "swing_lows": [],
                    "equal_highs": [],
                    "equal_lows": [],
                    "liquidity_sweeps": [],
                    "targets": {
                        "buy_side": [],
                        "sell_side": []
                    }
                }

                self.last_result = result
                return result

            if current_price is None:
                current_price = validated[-1]["close"]

            current_price = self._number(current_price)

            if current_price is None or current_price <= 0:
                result = {
                    "status": "INVALID_CURRENT_PRICE",
                    "version": self.VERSION,
                    "liquidity_sweeps": []
                }

                self.last_result = result
                return result

            swing_highs = self._detect_swing_highs(
                validated
            )

            swing_lows = self._detect_swing_lows(
                validated
            )

            equal_highs = self._group_equal_levels(
                swing_highs,
                "EQUAL_HIGHS"
            )

            equal_lows = self._group_equal_levels(
                swing_lows,
                "EQUAL_LOWS"
            )

            sweeps = self._detect_sweeps(
                validated,
                swing_highs,
                swing_lows
            )

            targets = self._build_targets(
                swing_highs,
                swing_lows,
                current_price
            )

            result = {
                "status": "ANALYZED",
                "version": self.VERSION,
                "candle_count": len(validated),
                "current_price": current_price,

                "swing_highs": swing_highs,
                "swing_lows": swing_lows,

                "equal_highs": equal_highs,
                "equal_lows": equal_lows,

                "equal_levels": {
                    "equal_highs": equal_highs,
                    "equal_lows": equal_lows
                },

                "liquidity_sweeps": sweeps,

                "targets": targets,

                "buy_side_liquidity_count": len(
                    targets["buy_side"]
                ),

                "sell_side_liquidity_count": len(
                    targets["sell_side"]
                ),

                "sweep_detected": bool(sweeps)
            }

            self.last_result = result
            return result

        finally:
            self.equal_tolerance = original_tolerance

    # British spelling compatibility
    def analyse(
        self,
        candles: Any,
        current_price: Optional[float] = None,
        tolerance: Optional[float] = None
    ) -> Dict[str, Any]:

        return self.analyze(
            candles,
            current_price,
            tolerance
        )

    # ---------------------------------------------------------
    # DIRECTIONAL SWEEP VALIDATION
    # ---------------------------------------------------------

    def validate_trade_sweep(
        self,
        analysis: Dict[str, Any],
        trade_direction: str
    ) -> Dict[str, Any]:

        direction = str(
            trade_direction
        ).strip().upper()

        if direction in {"BUY", "BULLISH", "LONG"}:
            expected = "SELL_SIDE_SWEEP"

        elif direction in {"SELL", "BEARISH", "SHORT"}:
            expected = "BUY_SIDE_SWEEP"

        else:
            return {
                "valid": False,
                "reason": "INVALID_TRADE_DIRECTION",
                "matching_sweeps": []
            }

        sweeps = analysis.get(
            "liquidity_sweeps", []
        )

        matching = [
            sweep for sweep in sweeps
            if (
                isinstance(sweep, dict)
                and sweep.get("type") == expected
                and sweep.get("confirmation")
                == "WICK_THROUGH_CLOSE_BACK_INSIDE"
            )
        ]

        return {
            "valid": bool(matching),
            "trade_direction": direction,
            "expected_sweep": expected,
            "matching_sweeps": matching
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "SMC_LIQUIDITY_ENGINE",
            "version": self.VERSION,
            "status": "ACTIVE"
        }


smc_liquidity_engine = SMCLiquidityEngine()
