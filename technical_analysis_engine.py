from logging_config import get_logger

logger = get_logger("technical_analysis_engine")


class TechnicalAnalysisEngine:

    def __init__(self, swing_window=3):

        self.swing_window = swing_window

    @staticmethod
    def normalize_candles(candles):

        normalized = []

        for candle in candles:

            try:
                item = {
                    "time": candle.get("time"),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(
                        candle.get("volume", 0)
                    ),
                }

            except (KeyError, TypeError, ValueError):
                continue

            if (
                item["high"] < item["low"]
                or item["open"] <= 0
                or item["close"] <= 0
            ):
                continue

            normalized.append(item)

        return normalized

    def find_swings(self, candles):

        window = self.swing_window

        swing_highs = []
        swing_lows = []

        for i in range(window, len(candles) - window):

            current = candles[i]

            left = candles[i - window:i]
            right = candles[i + 1:i + window + 1]

            is_high = all(
                current["high"] > candle["high"]
                for candle in left + right
            )

            is_low = all(
                current["low"] < candle["low"]
                for candle in left + right
            )

            if is_high:

                swing_highs.append({
                    "index": i,
                    "price": current["high"],
                    "time": current["time"],
                })

            if is_low:

                swing_lows.append({
                    "index": i,
                    "price": current["low"],
                    "time": current["time"],
                })

        return swing_highs, swing_lows

    @staticmethod
    def determine_structure(
        swing_highs,
        swing_lows,
    ):

        if len(swing_highs) < 2 or len(swing_lows) < 2:

            return {
                "bias": "UNKNOWN",
                "structure": [],
                "reason": "Insufficient swing points",
            }

        highs = swing_highs[-2:]
        lows = swing_lows[-2:]

        higher_high = highs[-1]["price"] > highs[-2]["price"]
        higher_low = lows[-1]["price"] > lows[-2]["price"]

        lower_high = highs[-1]["price"] < highs[-2]["price"]
        lower_low = lows[-1]["price"] < lows[-2]["price"]

        if higher_high and higher_low:

            bias = "BULLISH"
            structure = ["HH", "HL"]

        elif lower_high and lower_low:

            bias = "BEARISH"
            structure = ["LH", "LL"]

        else:

            bias = "RANGING"
            structure = []

            if higher_high:
                structure.append("HH")

            elif lower_high:
                structure.append("LH")

            if higher_low:
                structure.append("HL")

            elif lower_low:
                structure.append("LL")

        return {
            "bias": bias,
            "structure": structure,
            "latest_swing_high": highs[-1],
            "previous_swing_high": highs[-2],
            "latest_swing_low": lows[-1],
            "previous_swing_low": lows[-2],
        }

    @staticmethod
    def detect_breaks(
        candles,
        swing_highs,
        swing_lows,
        previous_bias="UNKNOWN",
    ):

        if not candles:
            return []

        candle = candles[-1]
        events = []

        if swing_highs:

            level = swing_highs[-1]["price"]

            if candle["close"] > level:

                event_type = (
                    "CHoCH"
                    if previous_bias == "BEARISH"
                    else "BOS"
                )

                events.append({
                    "type": event_type,
                    "direction": "BULLISH",
                    "level": level,
                    "close": candle["close"],
                    "confirmation": "BODY_CLOSE",
                })

        if swing_lows:

            level = swing_lows[-1]["price"]

            if candle["close"] < level:

                event_type = (
                    "CHoCH"
                    if previous_bias == "BULLISH"
                    else "BOS"
                )

                events.append({
                    "type": event_type,
                    "direction": "BEARISH",
                    "level": level,
                    "close": candle["close"],
                    "confirmation": "BODY_CLOSE",
                })

        return events

    @staticmethod
    def detect_liquidity_sweeps(
        candles,
        swing_highs,
        swing_lows,
    ):

        if not candles:
            return []

        candle = candles[-1]
        sweeps = []

        if swing_highs:

            level = swing_highs[-1]["price"]

            if (
                candle["high"] > level
                and candle["close"] < level
            ):

                sweeps.append({
                    "type": "HIGH_SWEEP",
                    "level": level,
                    "direction": "BEARISH",
                    "wick_beyond_level": (
                        candle["high"] - level
                    ),
                    "close_back_inside": True,
                })

        if swing_lows:

            level = swing_lows[-1]["price"]

            if (
                candle["low"] < level
                and candle["close"] > level
            ):

                sweeps.append({
                    "type": "LOW_SWEEP",
                    "level": level,
                    "direction": "BULLISH",
                    "wick_beyond_level": (
                        level - candle["low"]
                    ),
                    "close_back_inside": True,
                })

        return sweeps

    @staticmethod
    def detect_equal_levels(
        swing_points,
        tolerance,
    ):

        groups = []

        for point in swing_points:

            matched = False

            for group in groups:

                average = sum(
                    item["price"]
                    for item in group
                ) / len(group)

                if abs(
                    point["price"] - average
                ) <= tolerance:

                    group.append(point)
                    matched = True
                    break

            if not matched:
                groups.append([point])

        return [
            {
                "price": round(
                    sum(item["price"] for item in group)
                    / len(group),
                    8,
                ),
                "touches": len(group),
                "points": group,
            }
            for group in groups
            if len(group) >= 2
        ]

    @staticmethod
    def detect_fvg(candles):

        gaps = []

        for i in range(2, len(candles)):

            first = candles[i - 2]
            third = candles[i]

            # Bullish imbalance
            if third["low"] > first["high"]:

                gaps.append({
                    "type": "BULLISH_FVG",
                    "lower": first["high"],
                    "upper": third["low"],
                    "midpoint": (
                        first["high"] + third["low"]
                    ) / 2,
                    "index": i,
                    "time": third["time"],
                })

            # Bearish imbalance
            elif third["high"] < first["low"]:

                gaps.append({
                    "type": "BEARISH_FVG",
                    "lower": third["high"],
                    "upper": first["low"],
                    "midpoint": (
                        third["high"] + first["low"]
                    ) / 2,
                    "index": i,
                    "time": third["time"],
                })

        return gaps

    @staticmethod
    def detect_order_block_candidates(candles):

        candidates = []

        for i in range(1, len(candles) - 1):

            current = candles[i]
            following = candles[i + 1]

            current_bearish = (
                current["close"] < current["open"]
            )

            current_bullish = (
                current["close"] > current["open"]
            )

            following_bullish = (
                following["close"] > following["open"]
            )

            following_bearish = (
                following["close"] < following["open"]
            )

            if current_bearish and following_bullish:

                candidates.append({
                    "type": "BULLISH_OB_CANDIDATE",
                    "high": current["high"],
                    "low": current["low"],
                    "index": i,
                    "time": current["time"],
                })

            elif current_bullish and following_bearish:

                candidates.append({
                    "type": "BEARISH_OB_CANDIDATE",
                    "high": current["high"],
                    "low": current["low"],
                    "index": i,
                    "time": current["time"],
                })

        return candidates

    @staticmethod
    def calculate_premium_discount(candles):

        if not candles:
            return None

        high = max(
            candle["high"]
            for candle in candles
        )

        low = min(
            candle["low"]
            for candle in candles
        )

        midpoint = (high + low) / 2

        current_price = candles[-1]["close"]

        if current_price > midpoint:
            zone = "PREMIUM"

        elif current_price < midpoint:
            zone = "DISCOUNT"

        else:
            zone = "EQUILIBRIUM"

        return {
            "range_high": high,
            "range_low": low,
            "equilibrium": midpoint,
            "current_price": current_price,
            "zone": zone,
        }

    def analyze(
        self,
        candles,
        symbol=None,
        timeframe=None,
        previous_bias="UNKNOWN",
        liquidity_tolerance=None,
    ):

        candles = self.normalize_candles(candles)

        if len(candles) < (
            self.swing_window * 2 + 5
        ):

            return {
                "success": False,
                "symbol": symbol,
                "timeframe": timeframe,
                "reason": "Insufficient candle history",
            }

        swing_highs, swing_lows = (
            self.find_swings(candles)
        )

        structure = self.determine_structure(
            swing_highs,
            swing_lows,
        )

        breaks = self.detect_breaks(
            candles,
            swing_highs,
            swing_lows,
            previous_bias,
        )

        sweeps = self.detect_liquidity_sweeps(
            candles,
            swing_highs,
            swing_lows,
        )

        fvgs = self.detect_fvg(candles)

        order_blocks = (
            self.detect_order_block_candidates(candles)
        )

        premium_discount = (
            self.calculate_premium_discount(candles)
        )

        if liquidity_tolerance is None:

            liquidity_tolerance = (
                candles[-1]["close"] * 0.0001
            )

        equal_highs = self.detect_equal_levels(
            swing_highs,
            liquidity_tolerance,
        )

        equal_lows = self.detect_equal_levels(
            swing_lows,
            liquidity_tolerance,
        )

        result = {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "candles_analyzed": len(candles),
            "current_price": candles[-1]["close"],
            "bias": structure["bias"],
            "structure": structure,
            "swing_highs": swing_highs,
            "swing_lows": swing_lows,
            "breaks": breaks,
            "liquidity_sweeps": sweeps,
            "equal_highs": equal_highs,
            "equal_lows": equal_lows,
            "fvgs": fvgs,
            "order_block_candidates": order_blocks,
            "premium_discount": premium_discount,
        }

        logger.info(
            "Technical analysis complete | %s | %s | Bias: %s",
            symbol,
            timeframe,
            structure["bias"],
        )

        return result


technical_analysis_engine = TechnicalAnalysisEngine()
