from logging_config import get_logger

logger = get_logger("technical_analysis_engine")


class TechnicalAnalysisEngine:

    def __init__(
        self,
        swing_window=3,
        atr_period=14,
        rsi_period=14,
        ema_periods=None,
        structure_lookback=50,
        displacement_multiplier=1.5,
    ):

        self.swing_window = max(1, int(swing_window))
        self.atr_period = max(1, int(atr_period))
        self.rsi_period = max(1, int(rsi_period))

        self.ema_periods = (
            ema_periods or [9, 20, 50, 200]
        )

        self.structure_lookback = max(
            10,
            int(structure_lookback),
        )

        self.displacement_multiplier = max(
            1.0,
            float(displacement_multiplier),
        )

    # ==================================================
    # CANDLE NORMALIZATION
    # ==================================================

    @staticmethod
    def normalize_candles(candles):

        normalized = []

        if not candles:
            return normalized

        for candle in candles:

            try:

                if not isinstance(candle, dict):
                    continue

                # Explicitly exclude unfinished candles.
                if candle.get("is_closed") is False:
                    continue

                if candle.get("closed") is False:
                    continue

                if candle.get("complete") is False:
                    continue

                if candle.get("is_complete") is False:
                    continue

                item = {
                    "time": candle.get("time"),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(
                        candle.get("volume", 0) or 0
                    ),
                }

            except (
                KeyError,
                TypeError,
                ValueError,
                OverflowError,
            ):
                continue

            values = [
                item["open"],
                item["high"],
                item["low"],
                item["close"],
                item["volume"],
            ]

            if any(
                not isinstance(value, (int, float))
                for value in values
            ):
                continue

            if item["high"] < item["low"]:
                continue

            if item["high"] < max(
                item["open"],
                item["close"],
            ):
                continue

            if item["low"] > min(
                item["open"],
                item["close"],
            ):
                continue

            if (
                item["open"] <= 0
                or item["close"] <= 0
                or item["high"] <= 0
                or item["low"] <= 0
            ):
                continue

            if item["volume"] < 0:
                continue

            normalized.append(item)

        return normalized

    # ==================================================
    # SWING DETECTION
    # ==================================================

    def find_swings(self, candles):

        window = self.swing_window

        swing_highs = []
        swing_lows = []

        if len(candles) < (window * 2 + 1):
            return swing_highs, swing_lows

        for i in range(
            window,
            len(candles) - window,
        ):

            current = candles[i]

            left = candles[i - window:i]

            right = candles[
                i + 1:i + window + 1
            ]

            surrounding = left + right

            is_high = all(
                current["high"] > candle["high"]
                for candle in surrounding
            )

            is_low = all(
                current["low"] < candle["low"]
                for candle in surrounding
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

    # ==================================================
    # MARKET STRUCTURE
    # ==================================================

    @staticmethod
    def determine_structure(
        swing_highs,
        swing_lows,
    ):

        if (
            len(swing_highs) < 2
            or len(swing_lows) < 2
        ):

            return {
                "bias": "UNKNOWN",
                "structure": [],
                "reason": "Insufficient swing points",
            }

        highs = swing_highs[-2:]
        lows = swing_lows[-2:]

        higher_high = (
            highs[-1]["price"]
            > highs[-2]["price"]
        )

        higher_low = (
            lows[-1]["price"]
            > lows[-2]["price"]
        )

        lower_high = (
            highs[-1]["price"]
            < highs[-2]["price"]
        )

        lower_low = (
            lows[-1]["price"]
            < lows[-2]["price"]
        )

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

            else:
                structure.append("EQH")

            if higher_low:
                structure.append("HL")

            elif lower_low:
                structure.append("LL")

            else:
                structure.append("EQL")

        return {
            "bias": bias,
            "structure": structure,
            "latest_swing_high": highs[-1],
            "previous_swing_high": highs[-2],
            "latest_swing_low": lows[-1],
            "previous_swing_low": lows[-2],
        }

    # ==================================================
    # BOS / CHoCH
    # ==================================================

    @staticmethod
    def detect_breaks(
        candles,
        swing_highs,
        swing_lows,
        previous_bias="UNKNOWN",
    ):

        if len(candles) < 2:
            return []

        current = candles[-1]
        previous = candles[-2]

        events = []

        # Bullish break requires a close crossing
        # from below the swing level to above it.

        if swing_highs:

            level = swing_highs[-1]["price"]

            crossed_up = (
                previous["close"] <= level
                and current["close"] > level
            )

            if crossed_up:

                event_type = (
                    "CHoCH"
                    if previous_bias == "BEARISH"
                    else "BOS"
                )

                events.append({
                    "type": event_type,
                    "direction": "BULLISH",
                    "level": level,
                    "previous_close": previous["close"],
                    "close": current["close"],
                    "time": current["time"],
                    "confirmation": "BODY_CLOSE",
                    "confirmed": True,
                })

        # Bearish break requires a close crossing
        # from above the swing level to below it.

        if swing_lows:

            level = swing_lows[-1]["price"]

            crossed_down = (
                previous["close"] >= level
                and current["close"] < level
            )

            if crossed_down:

                event_type = (
                    "CHoCH"
                    if previous_bias == "BULLISH"
                    else "BOS"
                )

                events.append({
                    "type": event_type,
                    "direction": "BEARISH",
                    "level": level,
                    "previous_close": previous["close"],
                    "close": current["close"],
                    "time": current["time"],
                    "confirmation": "BODY_CLOSE",
                    "confirmed": True,
                })

        return events

    # ==================================================
    # LIQUIDITY SWEEPS
    # ==================================================

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
                    "time": candle["time"],
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
                    "time": candle["time"],
                })

        return sweeps

    # ==================================================
    # EQUAL HIGH / EQUAL LOW DETECTION
    # ==================================================

    @staticmethod
    def detect_equal_levels(
        swing_points,
        tolerance,
    ):

        groups = []

        tolerance = max(
            0.0,
            float(tolerance),
        )

        for point in swing_points:

            matched = False

            for group in groups:

                average = (
                    sum(
                        item["price"]
                        for item in group
                    )
                    / len(group)
                )

                if abs(
                    point["price"] - average
                ) <= tolerance:

                    group.append(point)
                    matched = True
                    break

            if not matched:
                groups.append([point])

        results = []

        for group in groups:

            if len(group) < 2:
                continue

            average_price = (
                sum(
                    item["price"]
                    for item in group
                )
                / len(group)
            )

            results.append({
                "price": round(
                    average_price,
                    8,
                ),
                "touches": len(group),
                "points": group,
                "liquidity_type": (
                    "EQUAL_HIGH"
                    if all(
                        item in swing_points
                        for item in group
                    )
                    else "EQUAL_LEVEL"
                ),
            })

        return results

    # ==================================================
    # FAIR VALUE GAP DETECTION
    # ==================================================

    @staticmethod
    def detect_fvg(candles):

        gaps = []

        for i in range(2, len(candles)):

            first = candles[i - 2]
            middle = candles[i - 1]
            third = candles[i]

            # Bullish FVG

            if third["low"] > first["high"]:

                lower = first["high"]
                upper = third["low"]

                subsequent = candles[i + 1:]

                mitigation = (
                    TechnicalAnalysisEngine
                    ._calculate_fvg_mitigation(
                        "BULLISH",
                        lower,
                        upper,
                        subsequent,
                    )
                )

                gaps.append({
                    "type": "BULLISH_FVG",
                    "lower": lower,
                    "upper": upper,
                    "midpoint": (
                        lower + upper
                    ) / 2,
                    "index": i,
                    "time": third["time"],
                    "middle_candle": middle,
                    **mitigation,
                })

            # Bearish FVG

            elif third["high"] < first["low"]:

                lower = third["high"]
                upper = first["low"]

                subsequent = candles[i + 1:]

                mitigation = (
                    TechnicalAnalysisEngine
                    ._calculate_fvg_mitigation(
                        "BEARISH",
                        lower,
                        upper,
                        subsequent,
                    )
                )

                gaps.append({
                    "type": "BEARISH_FVG",
                    "lower": lower,
                    "upper": upper,
                    "midpoint": (
                        lower + upper
                    ) / 2,
                    "index": i,
                    "time": third["time"],
                    "middle_candle": middle,
                    **mitigation,
                })

        return gaps

    @staticmethod
    def _calculate_fvg_mitigation(
        direction,
        lower,
        upper,
        subsequent_candles,
    ):

        touched = False
        partially_mitigated = False
        fully_mitigated = False

        mitigation_time = None

        for candle in subsequent_candles:

            if direction == "BULLISH":

                if candle["low"] <= upper:
                    touched = True

                if candle["low"] < upper:
                    partially_mitigated = True

                if candle["low"] <= lower:

                    fully_mitigated = True

                    if mitigation_time is None:
                        mitigation_time = candle["time"]

            else:

                if candle["high"] >= lower:
                    touched = True

                if candle["high"] > lower:
                    partially_mitigated = True

                if candle["high"] >= upper:

                    fully_mitigated = True

                    if mitigation_time is None:
                        mitigation_time = candle["time"]

        if fully_mitigated:
            status = "FULLY_MITIGATED"

        elif partially_mitigated:
            status = "PARTIALLY_MITIGATED"

        elif touched:
            status = "TOUCHED"

        else:
            status = "UNMITIGATED"

        return {
            "touched": touched,
            "partially_mitigated": (
                partially_mitigated
            ),
            "fully_mitigated": fully_mitigated,
            "mitigation_status": status,
            "mitigation_time": mitigation_time,
            "fresh": not touched,
        }

    # ==================================================
    # ORDER BLOCK CANDIDATES
    # ==================================================

    @staticmethod
    def detect_order_block_candidates(
        candles,
        displacement_multiplier=1.5,
    ):

        candidates = []

        if len(candles) < 3:
            return candidates

        bodies = [
            abs(
                candle["close"]
                - candle["open"]
            )
            for candle in candles
        ]

        for i in range(1, len(candles) - 1):

            current = candles[i]
            following = candles[i + 1]

            current_bearish = (
                current["close"]
                < current["open"]
            )

            current_bullish = (
                current["close"]
                > current["open"]
            )

            following_bullish = (
                following["close"]
                > following["open"]
            )

            following_bearish = (
                following["close"]
                < following["open"]
            )

            average_body = (
                sum(bodies[max(0, i - 10):i])
                / max(
                    1,
                    len(bodies[max(0, i - 10):i]),
                )
            )

            following_body = abs(
                following["close"]
                - following["open"]
            )

            displacement = (
                average_body > 0
                and following_body
                >= (
                    average_body
                    * displacement_multiplier
                )
            )

            # Bullish OB candidate:
            # Last bearish candle before bullish move.

            if (
                current_bearish
                and following_bullish
            ):

                close_above_ob = (
                    following["close"]
                    > current["high"]
                )

                candidates.append({
                    "type": "BULLISH_OB_CANDIDATE",
                    "high": current["high"],
                    "low": current["low"],
                    "index": i,
                    "time": current["time"],
                    "confirmation_time": (
                        following["time"]
                    ),
                    "displacement": displacement,
                    "displacement_body": (
                        following_body
                    ),
                    "average_body": average_body,
                    "close_beyond_ob": (
                        close_above_ob
                    ),
                    "validated": (
                        displacement
                        and close_above_ob
                    ),
                })

            # Bearish OB candidate:
            # Last bullish candle before bearish move.

            elif (
                current_bullish
                and following_bearish
            ):

                close_below_ob = (
                    following["close"]
                    < current["low"]
                )

                candidates.append({
                    "type": "BEARISH_OB_CANDIDATE",
                    "high": current["high"],
                    "low": current["low"],
                    "index": i,
                    "time": current["time"],
                    "confirmation_time": (
                        following["time"]
                    ),
                    "displacement": displacement,
                    "displacement_body": (
                        following_body
                    ),
                    "average_body": average_body,
                    "close_beyond_ob": (
                        close_below_ob
                    ),
                    "validated": (
                        displacement
                        and close_below_ob
                    ),
                })

        return candidates

    # ==================================================
    # PREMIUM / DISCOUNT
    # ==================================================

    @staticmethod
    def calculate_premium_discount(
        candles,
        swing_highs=None,
        swing_lows=None,
    ):

        if not candles:
            return None

        range_high = None
        range_low = None

        # Use the latest structural swing range
        # when valid swing points are available.

        if (
            swing_highs
            and swing_lows
        ):

            latest_high = swing_highs[-1]
            latest_low = swing_lows[-1]

            if latest_high["index"] > latest_low["index"]:

                range_high = latest_high["price"]
                range_low = latest_low["price"]

            elif latest_low["index"] > latest_high["index"]:

                range_high = latest_high["price"]
                range_low = latest_low["price"]

        # Fallback: recent candle range.

        if (
            range_high is None
            or range_low is None
        ):

            lookback = min(
                50,
                len(candles),
            )

            recent = candles[-lookback:]

            range_high = max(
                candle["high"]
                for candle in recent
            )

            range_low = min(
                candle["low"]
                for candle in recent
            )

        if range_high <= range_low:
            return None

        midpoint = (
            range_high + range_low
        ) / 2

        current_price = candles[-1]["close"]

        if current_price > midpoint:
            zone = "PREMIUM"

        elif current_price < midpoint:
            zone = "DISCOUNT"

        else:
            zone = "EQUILIBRIUM"

        range_size = (
            range_high - range_low
        )

        position_percent = (
            (current_price - range_low)
            / range_size
            * 100
        )

        return {
            "range_high": range_high,
            "range_low": range_low,
            "equilibrium": midpoint,
            "current_price": current_price,
            "zone": zone,
            "position_percent": round(
                position_percent,
                2,
            ),
        }

    # ==================================================
    # CANDLE ANALYSIS
    # ==================================================

    @staticmethod
    def analyze_candle(candle):

        candle_range = (
            candle["high"]
            - candle["low"]
        )

        body = abs(
            candle["close"]
            - candle["open"]
        )

        upper_wick = (
            candle["high"]
            - max(
                candle["open"],
                candle["close"],
            )
        )

        lower_wick = (
            min(
                candle["open"],
                candle["close"],
            )
            - candle["low"]
        )

        if candle_range <= 0:

            return {
                "direction": "NEUTRAL",
                "body": body,
                "range": candle_range,
                "body_percent": 0,
                "upper_wick": upper_wick,
                "lower_wick": lower_wick,
            }

        if candle["close"] > candle["open"]:
            direction = "BULLISH"

        elif candle["close"] < candle["open"]:
            direction = "BEARISH"

        else:
            direction = "NEUTRAL"

        return {
            "direction": direction,
            "body": body,
            "range": candle_range,
            "body_percent": round(
                body / candle_range * 100,
                2,
            ),
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "upper_wick_percent": round(
                upper_wick / candle_range * 100,
                2,
            ),
            "lower_wick_percent": round(
                lower_wick / candle_range * 100,
                2,
            ),
            "close_position_percent": round(
                (
                    candle["close"]
                    - candle["low"]
                )
                / candle_range
                * 100,
                2,
            ),
        }

    # ==================================================
    # EMA
    # ==================================================

    @staticmethod
    def calculate_ema(
        candles,
        period,
    ):

        if not candles or period <= 0:
            return None

        closes = [
            candle["close"]
            for candle in candles
        ]

        if len(closes) < period:
            return None

        multiplier = (
            2 / (period + 1)
        )

        ema = sum(
            closes[:period]
        ) / period

        for price in closes[period:]:

            ema = (
                price * multiplier
                + ema * (1 - multiplier)
            )

        return ema

    # ==================================================
    # RSI
    # ==================================================

    @staticmethod
    def calculate_rsi(
        candles,
        period=14,
    ):

        if len(candles) <= period:
            return None

        closes = [
            candle["close"]
            for candle in candles
        ]

        gains = []
        losses = []

        for i in range(1, len(closes)):

            change = (
                closes[i] - closes[i - 1]
            )

            gains.append(
                max(change, 0)
            )

            losses.append(
                abs(min(change, 0))
            )

        average_gain = (
            sum(gains[:period])
            / period
        )

        average_loss = (
            sum(losses[:period])
            / period
        )

        for i in range(period, len(gains)):

            average_gain = (
                (
                    average_gain
                    * (period - 1)
                )
                + gains[i]
            ) / period

            average_loss = (
                (
                    average_loss
                    * (period - 1)
                )
                + losses[i]
            ) / period

        if average_loss == 0:

            if average_gain == 0:
                return 50.0

            return 100.0

        relative_strength = (
            average_gain
            / average_loss
        )

        rsi = (
            100
            - (
                100
                / (
                    1 + relative_strength
                )
            )
        )

        return round(rsi, 2)

    # ==================================================
    # ATR
    # ==================================================

    @staticmethod
    def calculate_atr(
        candles,
        period=14,
    ):

        if len(candles) <= period:
            return None

        true_ranges = []

        for i in range(1, len(candles)):

            current = candles[i]
            previous = candles[i - 1]

            true_range = max(
                current["high"]
                - current["low"],

                abs(
                    current["high"]
                    - previous["close"]
                ),

                abs(
                    current["low"]
                    - previous["close"]
                ),
            )

            true_ranges.append(
                true_range
            )

        if len(true_ranges) < period:
            return None

        atr = (
            sum(true_ranges[:period])
            / period
        )

        for value in true_ranges[period:]:

            atr = (
                (
                    atr * (period - 1)
                )
                + value
            ) / period

        return atr

    # ==================================================
    # SUPPORT / RESISTANCE
    # ==================================================

    @staticmethod
    def detect_support_resistance(
        swing_highs,
        swing_lows,
        tolerance,
    ):

        resistance = (
            TechnicalAnalysisEngine
            .detect_equal_levels(
                swing_highs,
                tolerance,
            )
        )

        support = (
            TechnicalAnalysisEngine
            .detect_equal_levels(
                swing_lows,
                tolerance,
            )
        )

        return {
            "support": support,
            "resistance": resistance,
        }

    # ==================================================
    # MOMENTUM
    # ==================================================

    @staticmethod
    def determine_momentum(
        candles,
        rsi=None,
    ):

        if len(candles) < 3:

            return {
                "momentum": "UNKNOWN",
                "reason": "Insufficient candles",
            }

        latest = candles[-1]
        previous = candles[-2]

        current_body = abs(
            latest["close"]
            - latest["open"]
        )

        previous_body = abs(
            previous["close"]
            - previous["open"]
        )

        if (
            latest["close"]
            > previous["close"]
            and latest["close"]
            > latest["open"]
        ):

            momentum = "BULLISH"

        elif (
            latest["close"]
            < previous["close"]
            and latest["close"]
            < latest["open"]
        ):

            momentum = "BEARISH"

        else:

            momentum = "NEUTRAL"

        strength = "NORMAL"

        if (
            previous_body > 0
            and current_body
            >= previous_body * 1.5
        ):

            strength = "STRONG"

        if (
            rsi is not None
            and rsi >= 70
        ):

            rsi_condition = "OVERBOUGHT"

        elif (
            rsi is not None
            and rsi <= 30
        ):

            rsi_condition = "OVERSOLD"

        else:

            rsi_condition = "NEUTRAL"

        return {
            "momentum": momentum,
            "strength": strength,
            "current_body": current_body,
            "previous_body": previous_body,
            "rsi_condition": rsi_condition,
            "rsi": rsi,
        }

    # ==================================================
    # MAIN ANALYSIS
    # ==================================================

    def analyze(
        self,
        candles,
        symbol=None,
        timeframe=None,
        previous_bias="UNKNOWN",
        liquidity_tolerance=None,
    ):

        candles = self.normalize_candles(
            candles
        )

        minimum_candles = (
            self.swing_window * 2 + 5
        )

        if len(candles) < minimum_candles:

            return {
                "success": False,
                "symbol": symbol,
                "timeframe": timeframe,
                "reason": (
                    "Insufficient candle history"
                ),
                "candles_analyzed": len(candles),
                "required_candles": (
                    minimum_candles
                ),
            }

        swing_highs, swing_lows = (
            self.find_swings(candles)
        )

        structure = (
            self.determine_structure(
                swing_highs,
                swing_lows,
            )
        )

        breaks = (
            self.detect_breaks(
                candles,
                swing_highs,
                swing_lows,
                previous_bias,
            )
        )

        sweeps = (
            self.detect_liquidity_sweeps(
                candles,
                swing_highs,
                swing_lows,
            )
        )

        fvgs = self.detect_fvg(
            candles
        )

        order_blocks = (
            self.detect_order_block_candidates(
                candles,
                self.displacement_multiplier,
            )
        )

        premium_discount = (
            self.calculate_premium_discount(
                candles,
                swing_highs,
                swing_lows,
            )
        )

        if liquidity_tolerance is None:

            liquidity_tolerance = (
                candles[-1]["close"]
                * 0.0001
            )

        equal_highs = (
            self.detect_equal_levels(
                swing_highs,
                liquidity_tolerance,
            )
        )

        equal_lows = (
            self.detect_equal_levels(
                swing_lows,
                liquidity_tolerance,
            )
        )

        candle_analysis = (
            self.analyze_candle(
                candles[-1]
            )
        )

        rsi = (
            self.calculate_rsi(
                candles,
                self.rsi_period,
            )
        )

        atr = (
            self.calculate_atr(
                candles,
                self.atr_period,
            )
        )

        ema_values = {}

        for period in self.ema_periods:

            ema_values[
                f"EMA_{period}"
            ] = self.calculate_ema(
                candles,
                period,
            )

        momentum = (
            self.determine_momentum(
                candles,
                rsi,
            )
        )

        support_resistance = (
            self.detect_support_resistance(
                swing_highs,
                swing_lows,
                liquidity_tolerance,
            )
        )

        current_price = (
            candles[-1]["close"]
        )

        # Current trend relationship to EMAs.

        ema_trend = {}

        for name, value in ema_values.items():

            if value is None:
                ema_trend[name] = "UNKNOWN"

            elif current_price > value:
                ema_trend[name] = "ABOVE"

            elif current_price < value:
                ema_trend[name] = "BELOW"

            else:
                ema_trend[name] = "AT"

        # Evidence-only output.
        # This engine does not authorize trades.

        result = {

            "success": True,

            "symbol": symbol,

            "timeframe": timeframe,

            "candles_analyzed": len(candles),

            "current_price": current_price,

            "latest_candle_time": (
                candles[-1]["time"]
            ),

            "bias": structure["bias"],

            "structure": structure,

            "swing_highs": swing_highs,

            "swing_lows": swing_lows,

            "breaks": breaks,

            "liquidity_sweeps": sweeps,

            "equal_highs": equal_highs,

            "equal_lows": equal_lows,

            "fvgs": fvgs,

            "order_block_candidates": (
                order_blocks
            ),

            "premium_discount": (
                premium_discount
            ),

            "candle_analysis": (
                candle_analysis
            ),

            "momentum": momentum,

            "rsi": rsi,

            "atr": atr,

            "ema": ema_values,

            "ema_relationship": ema_trend,

            "support_resistance": (
                support_resistance
            ),

            "evidence_only": True,

            "trade_authorization": False,
        }

        logger.info(
            (
                "Technical analysis complete | "
                "%s | %s | Bias: %s | "
                "Candles: %s | Breaks: %s | "
                "Sweeps: %s"
            ),
            symbol,
            timeframe,
            structure["bias"],
            len(candles),
            len(breaks),
            len(sweeps),
        )

        return result


# ==================================================
# ENGINE INSTANCE
# ==================================================

technical_analysis_engine = (
    TechnicalAnalysisEngine()
)
