
"""
Vrotex Bot V1
Technical Analysis Engine V3.0

Purpose:
- Produce technical market evidence for the SMC system.
- Identify market structure and body-close breaks.
- Identify liquidity sweeps and equal highs/lows.
- Detect fair value gaps and order-block candidates.
- Calculate premium/discount and technical indicators.

This module does not authorize or execute trades.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple


class TechnicalAnalysisEngine:
    VERSION = "3.0"

    def __init__(
        self,
        swing_strength: int = 3,
        atr_period: int = 14,
        rsi_period: int = 14,
        ema_periods: Optional[List[int]] = None,
        equal_level_tolerance: float = 0.0002,
        displacement_atr_multiple: float = 1.0,
    ):
        self.swing_strength = max(1, int(swing_strength))
        self.atr_period = max(2, int(atr_period))
        self.rsi_period = max(2, int(rsi_period))

        self.ema_periods = ema_periods or [
            20, 50, 100, 200
        ]

        self.equal_level_tolerance = float(
            equal_level_tolerance
        )

        self.displacement_atr_multiple = float(
            displacement_atr_multiple
        )

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # NORMALIZATION
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result:
                return None
            return result
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

            if None in (
                open_price,
                high,
                low,
                close,
            ):
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
                "volume": self._number(
                    source.get("volume")
                ),
                "original_index": original_index,
            })

        return normalized

    # ---------------------------------------------------------
    # TRUE RANGE AND ATR
    # ---------------------------------------------------------

    @staticmethod
    def _true_range(
        candle: Dict[str, Any],
        previous_close: Optional[float],
    ) -> float:

        if previous_close is None:
            return candle["high"] - candle["low"]

        return max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close),
        )

    def calculate_atr(
        self,
        candles: List[Dict[str, Any]],
    ) -> Optional[float]:

        if len(candles) < self.atr_period + 1:
            return None

        ranges = []

        start = len(candles) - self.atr_period

        for index in range(start, len(candles)):
            previous_close = candles[index - 1]["close"]

            ranges.append(
                self._true_range(
                    candles[index],
                    previous_close,
                )
            )

        if not ranges:
            return None

        return sum(ranges) / len(ranges)

    # ---------------------------------------------------------
    # EMA
    # ---------------------------------------------------------

    @staticmethod
    def calculate_ema(
        values: List[float],
        period: int,
    ) -> Optional[float]:

        if period <= 0 or len(values) < period:
            return None

        multiplier = 2 / (period + 1)

        ema = sum(values[:period]) / period

        for value in values[period:]:
            ema = (
                value * multiplier
                + ema * (1 - multiplier)
            )

        return ema

    # ---------------------------------------------------------
    # RSI
    # ---------------------------------------------------------

    def calculate_rsi(
        self,
        candles: List[Dict[str, Any]],
    ) -> Optional[float]:

        if len(candles) <= self.rsi_period:
            return None

        closes = [
            candle["close"] for candle in candles
        ]

        gains = []
        losses = []

        for index in range(1, len(closes)):
            change = closes[index] - closes[index - 1]

            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        average_gain = (
            sum(gains[:self.rsi_period])
            / self.rsi_period
        )

        average_loss = (
            sum(losses[:self.rsi_period])
            / self.rsi_period
        )

        for index in range(
            self.rsi_period,
            len(gains),
        ):
            average_gain = (
                average_gain * (self.rsi_period - 1)
                + gains[index]
            ) / self.rsi_period

            average_loss = (
                average_loss * (self.rsi_period - 1)
                + losses[index]
            ) / self.rsi_period

        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0

        relative_strength = (
            average_gain / average_loss
        )

        return 100 - (
            100 / (1 + relative_strength)
        )

    # ---------------------------------------------------------
    # SWING DETECTION
    # ---------------------------------------------------------

    def detect_swings(
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
                    "price": current["high"],
                    "index": index,
                    "timestamp": current.get("timestamp"),
                    "type": "SWING_HIGH",
                    "confirmed": True,
                })

            if is_low:
                lows.append({
                    "price": current["low"],
                    "index": index,
                    "timestamp": current.get("timestamp"),
                    "type": "SWING_LOW",
                    "confirmed": True,
                })

        return {
            "highs": highs,
            "lows": lows,
        }

    # ---------------------------------------------------------
    # MARKET STRUCTURE
    # ---------------------------------------------------------

    def classify_structure(
        self,
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:

        highs = swings["highs"]
        lows = swings["lows"]

        high_labels = []
        low_labels = []

        for index in range(1, len(highs)):
            current = highs[index]
            previous = highs[index - 1]

            label = (
                "HH"
                if current["price"] > previous["price"]
                else "LH"
            )

            high_labels.append({
                **current,
                "label": label,
            })

        for index in range(1, len(lows)):
            current = lows[index]
            previous = lows[index - 1]

            label = (
                "HL"
                if current["price"] > previous["price"]
                else "LL"
            )

            low_labels.append({
                **current,
                "label": label,
            })

        bullish = (
            len(high_labels) >= 2
            and len(low_labels) >= 2
            and high_labels[-1]["label"] == "HH"
            and high_labels[-2]["label"] == "HH"
            and low_labels[-1]["label"] == "HL"
            and low_labels[-2]["label"] == "HL"
        )

        bearish = (
            len(high_labels) >= 2
            and len(low_labels) >= 2
            and high_labels[-1]["label"] == "LH"
            and high_labels[-2]["label"] == "LH"
            and low_labels[-1]["label"] == "LL"
            and low_labels[-2]["label"] == "LL"
        )

        if bullish:
            bias = "BULLISH"
        elif bearish:
            bias = "BEARISH"
        else:
            bias = "RANGING"

        return {
            "bias": bias,
            "direction": bias,
            "highs": high_labels,
            "lows": low_labels,
            "latest_swing_high": (
                highs[-1] if highs else None
            ),
            "latest_swing_low": (
                lows[-1] if lows else None
            ),
        }

    # ---------------------------------------------------------
    # BOS AND CHoCH
    # ---------------------------------------------------------

    def detect_breaks(
        self,
        candles: List[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
        previous_bias: str = "UNKNOWN",
    ) -> List[Dict[str, Any]]:

        if len(candles) < 2:
            return []

        current = candles[-1]
        previous = candles[-2]

        previous_bias = str(
            previous_bias or "UNKNOWN"
        ).upper()

        events = []

        highs = swings["highs"]
        lows = swings["lows"]

        latest_high = (
            highs[-1] if highs else None
        )

        latest_low = (
            lows[-1] if lows else None
        )

        if latest_high:
            level = latest_high["price"]

            # A wick above the level is not a break.
            # The previous and current candle closes must
            # establish a full close beyond the level.

            if (
                previous["close"] <= level
                and current["close"] > level
            ):
                event_type = (
                    "CHoCH"
                    if previous_bias == "BEARISH"
                    else (
                        "BOS"
                        if previous_bias == "BULLISH"
                        else "BULLISH_BREAK"
                    )
                )

                events.append({
                    "type": event_type,
                    "direction": "BULLISH",
                    "level": level,
                    "index": len(candles) - 1,
                    "timestamp": current.get("timestamp"),
                    "previous_close": previous["close"],
                    "current_close": current["close"],
                    "confirmation": "BODY_CLOSE",
                    "body_close_confirmed": True,
                    "confirmed": True,
                })

        if latest_low:
            level = latest_low["price"]

            if (
                previous["close"] >= level
                and current["close"] < level
            ):
                event_type = (
                    "CHoCH"
                    if previous_bias == "BULLISH"
                    else (
                        "BOS"
                        if previous_bias == "BEARISH"
                        else "BEARISH_BREAK"
                    )
                )

                events.append({
                    "type": event_type,
                    "direction": "BEARISH",
                    "level": level,
                    "index": len(candles) - 1,
                    "timestamp": current.get("timestamp"),
                    "previous_close": previous["close"],
                    "current_close": current["close"],
                    "confirmation": "BODY_CLOSE",
                    "body_close_confirmed": True,
                    "confirmed": True,
                })

        return events

    # ---------------------------------------------------------
    # LIQUIDITY SWEEPS
    # ---------------------------------------------------------

    def detect_liquidity_sweeps(
        self,
        candles: List[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:

        if not candles:
            return []

        current = candles[-1]
        events = []

        for swing in swings["highs"]:
            level = swing["price"]

            if (
                current["high"] > level
                and current["close"] < level
            ):
                events.append({
                    "type": "HIGH_SWEEP",
                    "direction": "BEARISH",
                    "level": level,
                    "index": len(candles) - 1,
                    "timestamp": current.get("timestamp"),
                    "confirmation": (
                        "WICK_THROUGH_CLOSE_BACK_INSIDE"
                    ),
                    "confirmed": True,
                    "invalidated": False,
                })

        for swing in swings["lows"]:
            level = swing["price"]

            if (
                current["low"] < level
                and current["close"] > level
            ):
                events.append({
                    "type": "LOW_SWEEP",
                    "direction": "BULLISH",
                    "level": level,
                    "index": len(candles) - 1,
                    "timestamp": current.get("timestamp"),
                    "confirmation": (
                        "WICK_THROUGH_CLOSE_BACK_INSIDE"
                    ),
                    "confirmed": True,
                    "invalidated": False,
                })

        return events

    # ---------------------------------------------------------
    # EQUAL HIGHS AND LOWS
    # ---------------------------------------------------------

    def detect_equal_levels(
        self,
        swings: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:

        tolerance = self.equal_level_tolerance

        def cluster_levels(
            levels: List[Dict[str, Any]],
            level_type: str,
        ) -> List[Dict[str, Any]]:

            clusters = []

            for level in levels:
                matched = None

                for cluster in clusters:
                    if abs(
                        level["price"] - cluster["price"]
                    ) <= tolerance:
                        matched = cluster
                        break

                if matched is None:
                    clusters.append({
                        "price": level["price"],
                        "levels": [level],
                    })
                else:
                    matched["levels"].append(level)
                    matched["price"] = sum(
                        item["price"]
                        for item in matched["levels"]
                    ) / len(matched["levels"])

            results = []

            for cluster in clusters:
                if len(cluster["levels"]) < 2:
                    continue

                results.append({
                    "type": level_type,
                    "price": cluster["price"],
                    "touches": len(cluster["levels"]),
                    "indices": [
                        item["index"]
                        for item in cluster["levels"]
                    ],
                    "confirmed": True,
                })

            return results

        return {
            "equal_highs": cluster_levels(
                swings["highs"],
                "EQUAL_HIGHS",
            ),
            "equal_lows": cluster_levels(
                swings["lows"],
                "EQUAL_LOWS",
            ),
        }

    # ---------------------------------------------------------
    # FAIR VALUE GAPS
    # ---------------------------------------------------------

    def detect_fvgs(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        fvgs = []

        for index in range(2, len(candles)):
            first = candles[index - 2]
            middle = candles[index - 1]
            third = candles[index]

            if third["low"] > first["high"]:
                lower = first["high"]
                upper = third["low"]

                fvgs.append({
                    "type": "BULLISH_FVG",
                    "direction": "BULLISH",
                    "lower": lower,
                    "upper": upper,
                    "midpoint": (lower + upper) / 2,
                    "gap_size": upper - lower,
                    "formation_index": index,
                    "index": index,
                    "timestamp": third.get("timestamp"),
                    "clean": True,
                    "unmitigated": True,
                    "mitigation": "NONE",
                    "confirmed": True,
                })

            if third["high"] < first["low"]:
                lower = third["high"]
                upper = first["low"]

                fvgs.append({
                    "type": "BEARISH_FVG",
                    "direction": "BEARISH",
                    "lower": lower,
                    "upper": upper,
                    "midpoint": (lower + upper) / 2,
                    "gap_size": upper - lower,
                    "formation_index": index,
                    "index": index,
                    "timestamp": third.get("timestamp"),
                    "clean": True,
                    "unmitigated": True,
                    "mitigation": "NONE",
                    "confirmed": True,
                })

        self._track_fvg_mitigation(fvgs, candles)

        return fvgs

    @staticmethod
    def _track_fvg_mitigation(
        fvgs: List[Dict[str, Any]],
        candles: List[Dict[str, Any]],
    ) -> None:

        for fvg in fvgs:
            lower = fvg["lower"]
            upper = fvg["upper"]

            for index in range(
                fvg["formation_index"] + 1,
                len(candles),
            ):
                candle = candles[index]

                if (
                    candle["low"] <= upper
                    and candle["high"] >= lower
                ):
                    fvg["clean"] = False
                    fvg["unmitigated"] = False

                    if (
                        candle["low"] <= lower
                        and candle["high"] >= upper
                    ):
                        fvg["mitigation"] = "FULL"
                    elif (
                        candle["low"] <= fvg["midpoint"]
                        if fvg["direction"] == "BULLISH"
                        else candle["high"] >= fvg["midpoint"]
                    ):
                        fvg["mitigation"] = "MIDPOINT"
                    else:
                        fvg["mitigation"] = "PARTIAL"

                    fvg["mitigated_at_index"] = index
                    fvg["mitigated_at_timestamp"] = (
                        candle.get("timestamp")
                    )
                    break

    # ---------------------------------------------------------
    # ORDER-BLOCK CANDIDATES
    # ---------------------------------------------------------

    def detect_order_block_candidates(
        self,
        candles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        candidates = []

        for index in range(
            self.atr_period + 1,
            len(candles),
        ):
            displacement_candle = candles[index]
            origin = candles[index - 1]

            atr = self._calculate_historical_atr(
                candles,
                index,
            )

            if atr is None:
                continue

            body = abs(
                displacement_candle["close"]
                - displacement_candle["open"]
            )

            if body < (
                atr * self.displacement_atr_multiple
            ):
                continue

            if (
                displacement_candle["close"]
                > displacement_candle["open"]
                and origin["close"] < origin["open"]
            ):
                direction = "BULLISH"
            elif (
                displacement_candle["close"]
                < displacement_candle["open"]
                and origin["close"] > origin["open"]
            ):
                direction = "BEARISH"
            else:
                continue

            lower = origin["low"]
            upper = origin["high"]

            candidates.append({
                "type": f"{direction}_ORDER_BLOCK",
                "direction": direction,
                "lower": lower,
                "upper": upper,
                "midpoint": (lower + upper) / 2,
                "formation_index": index - 1,
                "displacement_index": index,
                "timestamp": origin.get("timestamp"),
                "displacement_timestamp": (
                    displacement_candle.get("timestamp")
                ),
                "origin_open": origin["open"],
                "origin_close": origin["close"],
                "displacement_body": body,
                "atr": atr,
                "confirmed": True,
                "valid_candidate": True,
            })

        self._track_ob_mitigation(candidates, candles)

        return candidates

    def _calculate_historical_atr(
        self,
        candles: List[Dict[str, Any]],
        candidate_index: int,
    ) -> Optional[float]:

        start = candidate_index - self.atr_period

        if start < 1:
            return None

        ranges = []

        for index in range(start, candidate_index):
            ranges.append(
                self._true_range(
                    candles[index],
                    candles[index - 1]["close"],
                )
            )

        if len(ranges) != self.atr_period:
            return None

        atr = sum(ranges) / len(ranges)

        return atr if atr > 0 else None

    @staticmethod
    def _track_ob_mitigation(
        blocks: List[Dict[str, Any]],
        candles: List[Dict[str, Any]],
    ) -> None:

        for block in blocks:
            lower = block["lower"]
            upper = block["upper"]

            block["clean"] = True
            block["unmitigated"] = True
            block["mitigation"] = "NONE"

            for index in range(
                block["displacement_index"] + 1,
                len(candles),
            ):
                candle = candles[index]

                if (
                    candle["low"] <= upper
                    and candle["high"] >= lower
                ):
                    block["clean"] = False
                    block["unmitigated"] = False

                    if (
                        candle["low"] <= lower
                        and candle["high"] >= upper
                    ):
                        block["mitigation"] = "FULL"
                    elif (
                        candle["low"] <= block["midpoint"]
                        if block["direction"] == "BULLISH"
                        else candle["high"] >= block["midpoint"]
                    ):
                        block["mitigation"] = "MIDPOINT"
                    else:
                        block["mitigation"] = "PARTIAL"

                    block["mitigated_at_index"] = index
                    block["mitigated_at_timestamp"] = (
                        candle.get("timestamp")
                    )
                    break

    # ---------------------------------------------------------
    # PREMIUM / DISCOUNT
    # ---------------------------------------------------------

    @staticmethod
    def calculate_premium_discount(
        candles: List[Dict[str, Any]],
        swings: Dict[str, List[Dict[str, Any]]],
        current_price: float,
    ) -> Dict[str, Any]:

        highs = swings["highs"]
        lows = swings["lows"]

        if not highs or not lows:
            return {
                "valid": False,
                "zone": "UNKNOWN",
                "equilibrium": None,
                "range_high": None,
                "range_low": None,
            }

        range_high = highs[-1]["price"]
        range_low = lows[-1]["price"]

        if range_high <= range_low:
            return {
                "valid": False,
                "zone": "UNKNOWN",
                "equilibrium": None,
                "range_high": range_high,
                "range_low": range_low,
            }

        equilibrium = (
            range_high + range_low
        ) / 2

        if current_price > equilibrium:
            zone = "PREMIUM"
        elif current_price < equilibrium:
            zone = "DISCOUNT"
        else:
            zone = "EQUILIBRIUM"

        return {
            "valid": True,
            "zone": zone,
            "equilibrium": equilibrium,
            "range_high": range_high,
            "range_low": range_low,
            "current_price": current_price,
            "range_size": range_high - range_low,
        }

    # ---------------------------------------------------------
    # SUPPORT AND RESISTANCE
    # ---------------------------------------------------------

    @staticmethod
    def calculate_support_resistance(
        swings: Dict[str, List[Dict[str, Any]]],
        current_price: float,
    ) -> Dict[str, Any]:

        supports = [
            item["price"]
            for item in swings["lows"]
            if item["price"] <= current_price
        ]

        resistances = [
            item["price"]
            for item in swings["highs"]
            if item["price"] >= current_price
        ]

        return {
            "support": (
                max(supports) if supports else None
            ),
            "resistance": (
                min(resistances) if resistances else None
            ),
            "supports": supports,
            "resistances": resistances,
        }

    # ---------------------------------------------------------
    # MOMENTUM
    # ---------------------------------------------------------

    @staticmethod
    def calculate_momentum(
        candles: List[Dict[str, Any]],
        period: int = 5,
    ) -> Dict[str, Any]:

        if len(candles) <= period:
            return {
                "direction": "UNKNOWN",
                "change": None,
                "strength": None,
            }

        current = candles[-1]["close"]
        previous = candles[-period - 1]["close"]

        change = current - previous

        if change > 0:
            direction = "BULLISH"
        elif change < 0:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        percentage = (
            (change / previous) * 100
            if previous != 0
            else None
        )

        return {
            "direction": direction,
            "change": change,
            "percentage": percentage,
            "strength": abs(percentage) if percentage is not None else None,
        }

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Sequence[Dict[str, Any]],
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        previous_bias: str = "UNKNOWN",
    ) -> Dict[str, Any]:

        normalized = self._normalize_candles(candles)

        if len(normalized) < max(
            self.atr_period + 1,
            self.swing_strength * 2 + 3,
        ):
            result = self._error(
                "INSUFFICIENT_VALID_CANDLES",
                len(normalized),
                symbol,
                timeframe,
            )
            self.last_result = deepcopy(result)
            return result

        current_price = normalized[-1]["close"]

        swings = self.detect_swings(normalized)

        structure = self.classify_structure(swings)

        breaks = self.detect_breaks(
            normalized,
            swings,
            previous_bias=previous_bias,
        )

        liquidity_sweeps = (
            self.detect_liquidity_sweeps(
                normalized,
                swings,
            )
        )

        equal_levels = self.detect_equal_levels(
            swings
        )

        fvgs = self.detect_fvgs(normalized)

        order_blocks = (
            self.detect_order_block_candidates(
                normalized
            )
        )

        premium_discount = (
            self.calculate_premium_discount(
                normalized,
                swings,
                current_price,
            )
        )

        atr = self.calculate_atr(normalized)

        rsi = self.calculate_rsi(normalized)

        closes = [
            candle["close"] for candle in normalized
        ]

        emas = {
            f"ema_{period}": self.calculate_ema(
                closes,
                period,
            )
            for period in self.ema_periods
        }

        momentum = self.calculate_momentum(
            normalized
        )

        support_resistance = (
            self.calculate_support_resistance(
                swings,
                current_price,
            )
        )

        bullish_fvgs = [
            item for item in fvgs
            if item["direction"] == "BULLISH"
        ]

        bearish_fvgs = [
            item for item in fvgs
            if item["direction"] == "BEARISH"
        ]

        clean_order_blocks = [
            item for item in order_blocks
            if (
                item.get("clean") is True
                and item.get("unmitigated") is True
            )
        ]

        bullish_order_blocks = [
            item for item in clean_order_blocks
            if item["direction"] == "BULLISH"
        ]

        bearish_order_blocks = [
            item for item in clean_order_blocks
            if item["direction"] == "BEARISH"
        ]

        result = {
            "success": True,
            "version": self.VERSION,
            "symbol": symbol,
            "timeframe": timeframe,

            "candles_analyzed": len(normalized),
            "current_price": current_price,
            "latest_timestamp": normalized[-1].get(
                "timestamp"
            ),

            "bias": structure["bias"],
            "direction": structure["direction"],

            "structure": structure,
            "swings": swings,
            "breaks": breaks,

            "liquidity_sweeps": liquidity_sweeps,
            "equal_highs": equal_levels["equal_highs"],
            "equal_lows": equal_levels["equal_lows"],

            "fvgs": fvgs,
            "bullish_fvgs": bullish_fvgs,
            "bearish_fvgs": bearish_fvgs,

            "order_block_candidates": order_blocks,
            "clean_order_blocks": clean_order_blocks,
            "bullish_order_blocks": bullish_order_blocks,
            "bearish_order_blocks": bearish_order_blocks,

            "premium_discount": premium_discount,

            "atr": atr,
            "rsi": rsi,
            "emas": emas,
            "momentum": momentum,
            "support_resistance": support_resistance,

            "candle_metrics": {
                "open": normalized[-1]["open"],
                "high": normalized[-1]["high"],
                "low": normalized[-1]["low"],
                "close": normalized[-1]["close"],
                "body": abs(
                    normalized[-1]["close"]
                    - normalized[-1]["open"]
                ),
                "range": (
                    normalized[-1]["high"]
                    - normalized[-1]["low"]
                ),
                "timestamp": normalized[-1].get(
                    "timestamp"
                ),
            },

            "evidence_only": True,
            "trade_authorization": False,
            "execution_authorized": False,
        }

        self.last_result = deepcopy(result)
        return result

    # ---------------------------------------------------------
    # COMPATIBILITY ALIAS
    # ---------------------------------------------------------

    def analyse(
        self,
        candles: Sequence[Dict[str, Any]],
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        previous_bias: str = "UNKNOWN",
    ) -> Dict[str, Any]:

        return self.analyze(
            candles=candles,
            symbol=symbol,
            timeframe=timeframe,
            previous_bias=previous_bias,
        )

    # ---------------------------------------------------------
    # ERROR RESPONSE
    # ---------------------------------------------------------

    def _error(
        self,
        reason: str,
        candle_count: int,
        symbol: Optional[str],
        timeframe: Optional[str],
    ) -> Dict[str, Any]:

        return {
            "success": False,
            "version": self.VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "reason": reason,
            "candles_analyzed": candle_count,
            "bias": "UNKNOWN",
            "direction": "UNKNOWN",
            "structure": {},
            "swings": {
                "highs": [],
                "lows": [],
            },
            "breaks": [],
            "liquidity_sweeps": [],
            "equal_highs": [],
            "equal_lows": [],
            "fvgs": [],
            "bullish_fvgs": [],
            "bearish_fvgs": [],
            "order_block_candidates": [],
            "clean_order_blocks": [],
            "bullish_order_blocks": [],
            "bearish_order_blocks": [],
            "premium_discount": {
                "valid": False,
                "zone": "UNKNOWN",
            },
            "atr": None,
            "rsi": None,
            "emas": {},
            "momentum": {
                "direction": "UNKNOWN",
            },
            "support_resistance": {},
            "evidence_only": True,
            "trade_authorization": False,
            "execution_authorized": False,
        }


# -------------------------------------------------------------
# SHARED ENGINE INSTANCE
# -------------------------------------------------------------

technical_analysis_engine = TechnicalAnalysisEngine()
