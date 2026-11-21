
"""
VROTEX BOT V1
SMC LIQUIDITY ENGINE
Version 3.0

Responsibilities:
- Detect swing-high and swing-low liquidity.
- Identify equal highs and equal lows.
- Detect historical buy-side and sell-side liquidity sweeps.
- Require wick-through and close-back-inside confirmation.
- Identify liquidity targets relative to current price.
- Support external and internal liquidity classification.
- Preserve timestamps and candle indexes.
- Provide directional sweep evidence to the master SMC engine.

IMPORTANT:
- A wick through a level alone is not a confirmed sweep.
- A sweep requires a close back inside the relevant level.
- A liquidity sweep is not automatically a BOS or CHoCH.
- External and internal liquidity classifications require
  structural context supplied by the caller.
- This module does not authorize trade execution.
"""

from typing import Any, Dict, List, Optional
from copy import deepcopy
import math


class SMCLiquidityEngine:

    VERSION = "3.0"

    def __init__(
        self,
        swing_left: int = 2,
        swing_right: int = 2,
        equal_tolerance: float = 0.0001,
        minimum_equal_touches: int = 2,
    ):

        self.swing_left = max(1, int(swing_left))
        self.swing_right = max(1, int(swing_right))

        self.equal_tolerance = max(
            0.0,
            float(equal_tolerance),
        )

        self.minimum_equal_touches = max(
            2,
            int(minimum_equal_touches),
        )

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # NUMBER VALIDATION
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:

        try:
            result = float(value)

            if not math.isfinite(result):
                return None

            return result

        except (TypeError, ValueError):
            return None

    # ---------------------------------------------------------
    # CANDLE VALIDATION
    # ---------------------------------------------------------

    def _validate_candles(
        self,
        candles: Any,
    ) -> List[Dict[str, Any]]:

        if not isinstance(candles, list):
            return []

        validated = []

        for source_index, original in enumerate(candles):

            if not isinstance(original, dict):
                continue

            high = self._number(
                original.get("high", original.get("HIGH"))
            )

            low = self._number(
                original.get("low", original.get("LOW"))
            )

            open_price = self._number(
                original.get("open", original.get("OPEN"))
            )

            close = self._number(
                original.get("close", original.get("CLOSE"))
            )

            if None in (
                high,
                low,
                open_price,
                close,
            ):
                continue

            if high < low:
                continue

            if high < max(open_price, close):
                continue

            if low > min(open_price, close):
                continue

            candle = {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "index": source_index,
            }

            timestamp = (
                original.get("timestamp")
                or original.get("time")
                or original.get("datetime")
            )

            if timestamp is not None:
                candle["timestamp"] = timestamp

            validated.append(candle)

        return validated

    # ---------------------------------------------------------
    # SWING DETECTION
    # ---------------------------------------------------------

    def _detect_swing_highs(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        swings = []
        count = len(candles)

        for index in range(
            self.swing_left,
            count - self.swing_right,
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

                event = {
                    "index": current["index"],
                    "price": current["high"],
                    "type": "SWING_HIGH",
                }

                if "timestamp" in current:
                    event["timestamp"] = current["timestamp"]

                swings.append(event)

        return swings

    def _detect_swing_lows(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        swings = []
        count = len(candles)

        for index in range(
            self.swing_left,
            count - self.swing_right,
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

                event = {
                    "index": current["index"],
                    "price": current["low"],
                    "type": "SWING_LOW",
                }

                if "timestamp" in current:
                    event["timestamp"] = current["timestamp"]

                swings.append(event)

        return swings

    # ---------------------------------------------------------
    # EQUAL HIGH / LOW CLUSTERING
    # ---------------------------------------------------------

    def _group_equal_levels(
        self,
        swings: List[Dict[str, Any]],
        level_type: str,
        tolerance: Optional[float] = None,
    ) -> List[Dict[str, Any]]:

        active_tolerance = (
            self.equal_tolerance
            if tolerance is None
            else max(0.0, float(tolerance))
        )

        ordered = sorted(
            swings,
            key=lambda item: item["index"],
        )

        groups = []

        for swing in ordered:

            price = swing["price"]
            matched = None

            for group in groups:

                if abs(
                    price - group["level"]
                ) <= active_tolerance:

                    matched = group
                    break

            if matched is None:

                group = {
                    "level": price,
                    "prices": [price],
                    "touches": 1,
                    "indices": [swing["index"]],
                    "type": level_type,
                }

                if "timestamp" in swing:
                    group["timestamps"] = [
                        swing["timestamp"]
                    ]

                groups.append(group)

            else:

                matched["prices"].append(price)

                matched["touches"] += 1

                matched["indices"].append(
                    swing["index"]
                )

                matched["level"] = (
                    sum(matched["prices"])
                    / len(matched["prices"])
                )

                if "timestamp" in swing:

                    matched.setdefault(
                        "timestamps", []
                    ).append(swing["timestamp"])

        result = []

        for group in groups:

            if group["touches"] < self.minimum_equal_touches:
                continue

            output = {
                "type": group["type"],
                "level": group["level"],
                "touches": group["touches"],
                "indices": list(group["indices"]),
                "tolerance": active_tolerance,
            }

            if "timestamps" in group:
                output["timestamps"] = list(
                    group["timestamps"]
                )

            result.append(output)

        return result

    # ---------------------------------------------------------
    # OPTIONAL STRUCTURAL CLASSIFICATION
    # ---------------------------------------------------------

    @staticmethod
    def _normalise_context_swings(
        swings: Any,
    ) -> List[Dict[str, Any]]:

        if not isinstance(swings, list):
            return []

        result = []

        for item in swings:

            if not isinstance(item, dict):
                continue

            price = SMCLiquidityEngine._number(
                item.get("price")
            )

            index = item.get(
                "index",
                item.get("candle_index"),
            )

            try:
                index = int(index)
            except (TypeError, ValueError):
                continue

            if price is None:
                continue

            result.append({
                "price": price,
                "index": index,
                "type": str(
                    item.get("type", "")
                ).upper(),
            })

        return result

    def _classify_liquidity_levels(
        self,
        swing_highs: List[Dict[str, Any]],
        swing_lows: List[Dict[str, Any]],
        external_swings: Any = None,
        internal_swings: Any = None,
    ) -> Dict[str, Any]:

        external = self._normalise_context_swings(
            external_swings
        )

        internal = self._normalise_context_swings(
            internal_swings
        )

        def classify(
            level: Dict[str, Any],
            level_type: str,
        ) -> str:

            level_price = level["price"]
            level_index = level["index"]

            for item in external:

                if (
                    item["type"] in (
                        level_type,
                        "SWING_HIGH" if level_type == "HIGH" else "SWING_LOW",
                    )
                    and item["index"] == level_index
                    and abs(
                        item["price"] - level_price
                    ) <= self.equal_tolerance
                ):
                    return "EXTERNAL"

            for item in internal:

                if (
                    item["type"] in (
                        level_type,
                        "SWING_HIGH" if level_type == "HIGH" else "SWING_LOW",
                    )
                    and item["index"] == level_index
                    and abs(
                        item["price"] - level_price
                    ) <= self.equal_tolerance
                ):
                    return "INTERNAL"

            return "UNCLASSIFIED"

        for swing in swing_highs:

            swing["liquidity_context"] = classify(
                swing,
                "HIGH",
            )

        for swing in swing_lows:

            swing["liquidity_context"] = classify(
                swing,
                "LOW",
            )

        return {
            "external_context_supplied": bool(external),
            "internal_context_supplied": bool(internal),
            "classification_available": bool(
                external or internal
            ),
        }

    # ---------------------------------------------------------
    # HISTORICAL LIQUIDITY SWEEPS
    # ---------------------------------------------------------

    def _detect_sweeps(
        self,
        candles: List[Dict[str, Any]],
        swing_highs: List[Dict[str, Any]],
        swing_lows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        sweeps = []

        for candle in candles:

            candle_index = candle["index"]

            for swing in swing_highs:

                if swing["index"] >= candle_index:
                    continue

                level = swing["price"]

                wick_through = (
                    candle["high"] > level
                )

                close_back_inside = (
                    candle["close"] < level
                )

                if wick_through and close_back_inside:

                    event = {
                        "type": "BUY_SIDE_SWEEP",
                        "level": level,
                        "swing_index": swing["index"],
                        "candle_index": candle_index,
                        "confirmation":
                            "WICK_THROUGH_CLOSE_BACK_INSIDE",
                        "wick_through": True,
                        "close_back_inside": True,
                        "confirmed": True,
                        "liquidity_context": swing.get(
                            "liquidity_context",
                            "UNCLASSIFIED",
                        ),
                    }

                    if "timestamp" in candle:
                        event["timestamp"] = candle["timestamp"]

                    sweeps.append(event)

            for swing in swing_lows:

                if swing["index"] >= candle_index:
                    continue

                level = swing["price"]

                wick_through = (
                    candle["low"] < level
                )

                close_back_inside = (
                    candle["close"] > level
                )

                if wick_through and close_back_inside:

                    event = {
                        "type": "SELL_SIDE_SWEEP",
                        "level": level,
                        "swing_index": swing["index"],
                        "candle_index": candle_index,
                        "confirmation":
                            "WICK_THROUGH_CLOSE_BACK_INSIDE",
                        "wick_through": True,
                        "close_back_inside": True,
                        "confirmed": True,
                        "liquidity_context": swing.get(
                            "liquidity_context",
                            "UNCLASSIFIED",
                        ),
                    }

                    if "timestamp" in candle:
                        event["timestamp"] = candle["timestamp"]

                    sweeps.append(event)

        return sorted(
            sweeps,
            key=lambda item: item["candle_index"],
        )

    # ---------------------------------------------------------
    # LIQUIDITY TARGETS
    # ---------------------------------------------------------

    def _build_targets(
        self,
        swing_highs: List[Dict[str, Any]],
        swing_lows: List[Dict[str, Any]],
        current_price: float,
        swept_levels: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:

        buy_side = []
        sell_side = []

        swept_levels = swept_levels or []

        swept_keys = {
            (
                item.get("type"),
                item.get("swing_index"),
            )
            for item in swept_levels
        }

        for swing in swing_highs:

            price = swing["price"]

            if price <= current_price:
                continue

            key = (
                "BUY_SIDE_SWEEP",
                swing["index"],
            )

            status = (
                "SWEPT"
                if key in swept_keys
                else "UNSWEPT"
            )

            target = {
                "type": "BUY_SIDE_LIQUIDITY",
                "level": price,
                "swing_index": swing["index"],
                "status": status,
                "liquidity_context": swing.get(
                    "liquidity_context",
                    "UNCLASSIFIED",
                ),
            }

            if "timestamp" in swing:
                target["timestamp"] = swing["timestamp"]

            buy_side.append(target)

        for swing in swing_lows:

            price = swing["price"]

            if price >= current_price:
                continue

            key = (
                "SELL_SIDE_SWEEP",
                swing["index"],
            )

            status = (
                "SWEPT"
                if key in swept_keys
                else "UNSWEPT"
            )

            target = {
                "type": "SELL_SIDE_LIQUIDITY",
                "level": price,
                "swing_index": swing["index"],
                "status": status,
                "liquidity_context": swing.get(
                    "liquidity_context",
                    "UNCLASSIFIED",
                ),
            }

            if "timestamp" in swing:
                target["timestamp"] = swing["timestamp"]

            sell_side.append(target)

        buy_side.sort(
            key=lambda item: item["level"]
        )

        sell_side.sort(
            key=lambda item: item["level"],
            reverse=True,
        )

        return {
            "buy_side": buy_side,
            "sell_side": sell_side,
        }

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Any,
        current_price: Optional[float] = None,
        tolerance: Optional[float] = None,
        external_swings: Any = None,
        internal_swings: Any = None,
        tick_size: Optional[float] = None,
    ) -> Dict[str, Any]:

        validated = self._validate_candles(candles)

        active_tolerance = self.equal_tolerance

        if tolerance is not None:

            parsed = self._number(tolerance)

            if parsed is not None and parsed >= 0:
                active_tolerance = parsed

        if tick_size is not None:

            parsed_tick = self._number(tick_size)

            if parsed_tick is not None and parsed_tick > 0:
                active_tolerance = max(
                    active_tolerance,
                    parsed_tick,
                )

        minimum_required = (
            self.swing_left
            + self.swing_right
            + 2
        )

        if len(validated) < minimum_required:

            result = {
                "status": "INSUFFICIENT_DATA",
                "version": self.VERSION,
                "candle_count": len(validated),
                "swing_highs": [],
                "swing_lows": [],
                "equal_highs": [],
                "equal_lows": [],
                "liquidity_sweeps": [],
                "targets": {
                    "buy_side": [],
                    "sell_side": [],
                },
                "execution_authorized": False,
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
                "liquidity_sweeps": [],
                "execution_authorized": False,
            }

            self.last_result = result

            return result

        swing_highs = self._detect_swing_highs(
            validated
        )

        swing_lows = self._detect_swing_lows(
            validated
        )

        context = self._classify_liquidity_levels(
            swing_highs,
            swing_lows,
            external_swings,
            internal_swings,
        )

        equal_highs = self._group_equal_levels(
            swing_highs,
            "EQUAL_HIGHS",
            active_tolerance,
        )

        equal_lows = self._group_equal_levels(
            swing_lows,
            "EQUAL_LOWS",
            active_tolerance,
        )

        sweeps = self._detect_sweeps(
            validated,
            swing_highs,
            swing_lows,
        )

        targets = self._build_targets(
            swing_highs,
            swing_lows,
            current_price,
            sweeps,
        )

        latest_index = validated[-1]["index"]

        latest_sweeps = [
            item for item in sweeps
            if item["candle_index"] == latest_index
        ]

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
                "equal_lows": equal_lows,
            },

            # Historical confirmed events.
            "liquidity_sweeps": sweeps,

            # Latest candle events only.
            "latest_liquidity_sweeps": latest_sweeps,

            "targets": targets,

            "buy_side_liquidity_count": len(
                targets["buy_side"]
            ),

            "sell_side_liquidity_count": len(
                targets["sell_side"]
            ),

            "sweep_count": len(sweeps),

            "sweep_detected": bool(sweeps),

            "latest_candle_sweep_detected": bool(
                latest_sweeps
            ),

            "liquidity_context": context,

            "equal_level_tolerance": active_tolerance,

            "execution_authorized": False,
        }

        self.last_result = result

        return result

    # ---------------------------------------------------------
    # BRITISH SPELLING COMPATIBILITY
    # ---------------------------------------------------------

    def analyse(
        self,
        candles: Any,
        current_price: Optional[float] = None,
        tolerance: Optional[float] = None,
        external_swings: Any = None,
        internal_swings: Any = None,
        tick_size: Optional[float] = None,
    ) -> Dict[str, Any]:

        return self.analyze(
            candles=candles,
            current_price=current_price,
            tolerance=tolerance,
            external_swings=external_swings,
            internal_swings=internal_swings,
            tick_size=tick_size,
        )

    # ---------------------------------------------------------
    # DIRECTIONAL SWEEP VALIDATION
    # ---------------------------------------------------------

    def validate_trade_sweep(
        self,
        analysis: Dict[str, Any],
        trade_direction: str,
        max_age_candles: Optional[int] = None,
        current_candle_index: Optional[int] = None,
        liquidity_context: Optional[str] = None,
    ) -> Dict[str, Any]:

        direction = str(
            trade_direction
        ).strip().upper()

        if direction in (
            "BUY",
            "BULLISH",
            "LONG",
        ):

            expected = "SELL_SIDE_SWEEP"

        elif direction in (
            "SELL",
            "BEARISH",
            "SHORT",
        ):

            expected = "BUY_SIDE_SWEEP"

        else:

            return {
                "valid": False,
                "reason": "INVALID_TRADE_DIRECTION",
                "matching_sweeps": [],
            }

        if not isinstance(analysis, dict):

            return {
                "valid": False,
                "reason": "INVALID_ANALYSIS",
                "matching_sweeps": [],
            }

        sweeps = analysis.get(
            "liquidity_sweeps",
            [],
        )

        if not isinstance(sweeps, list):
            sweeps = []

        matching = []

        for sweep in sweeps:

            if not isinstance(sweep, dict):
                continue

            if sweep.get("type") != expected:
                continue

            if sweep.get("confirmation") != (
                "WICK_THROUGH_CLOSE_BACK_INSIDE"
            ):
                continue

            if sweep.get("confirmed") is False:
                continue

            if liquidity_context is not None:

                if sweep.get("liquidity_context") != (
                    str(liquidity_context).upper()
                ):
                    continue

            if (
                max_age_candles is not None
                and current_candle_index is not None
            ):

                try:

                    age = (
                        int(current_candle_index)
                        - int(sweep["candle_index"])
                    )

                except (KeyError, TypeError, ValueError):
                    continue

                if age < 0 or age > max_age_candles:
                    continue

            matching.append(sweep)

        return {
            "valid": bool(matching),
            "trade_direction": direction,
            "expected_sweep": expected,
            "matching_sweeps": matching,
            "latest": (
                matching[-1] if matching else None
            ),
            "reason": (
                "DIRECTIONAL_SWEEP_CONFIRMED"
                if matching
                else "NO_MATCHING_CONFIRMED_SWEEP"
            ),
            "execution_authorized": False,
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:

        return deepcopy(self.last_result)

    def get_status(self) -> Dict[str, Any]:

        return {
            "component": "SMC_LIQUIDITY_ENGINE",
            "version": self.VERSION,
            "status": "ACTIVE",
            "swing_left": self.swing_left,
            "swing_right": self.swing_right,
            "equal_tolerance": self.equal_tolerance,
            "minimum_equal_touches":
                self.minimum_equal_touches,
        }


smc_liquidity_engine = SMCLiquidityEngine()
