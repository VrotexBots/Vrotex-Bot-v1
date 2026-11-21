"""
Vrotex Bot V1
SMC Order Block Engine
Version: 3.0

Responsibilities:
- Detect bullish and bearish order blocks
- Identify displacement following opposing candles
- Validate candle-body strength
- Track OB mitigation
- Track midpoint mitigation
- Track full mitigation
- Track invalidation
- Preserve timestamps and candle indexes
- Provide evidence to the Master SMC engine

Order blocks are candidates, not trade signals.
"""

import logging
from copy import deepcopy


logger = logging.getLogger("vrotex.smc_order_block")


class SMCOrderBlockEngine:

    VERSION = "3.0"

    DEFAULT_DISPLACEMENT_ATR = 1.2

    def __init__(
        self,
        displacement_atr=None,
    ):

        self.displacement_atr = (
            displacement_atr
            or self.DEFAULT_DISPLACEMENT_ATR
        )

        self.last_analysis = {}

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _number(value, default=None):

        try:
            return float(value)

        except (TypeError, ValueError):

            return default

    @staticmethod
    def _get(candle, key, default=None):

        if isinstance(candle, dict):

            return candle.get(
                key,
                default,
            )

        return getattr(
            candle,
            key,
            default,
        )

    @staticmethod
    def _timestamp(candle):

        if isinstance(candle, dict):

            return candle.get(
                "timestamp",
                candle.get(
                    "time",
                    candle.get(
                        "datetime",
                    ),
                ),
            )

        return getattr(
            candle,
            "timestamp",
            None,
        )

    def _normalize_candle(
        self,
        candle,
        index,
    ):

        open_price = self._number(
            self._get(candle, "open")
        )

        high = self._number(
            self._get(candle, "high")
        )

        low = self._number(
            self._get(candle, "low")
        )

        close = self._number(
            self._get(candle, "close")
        )

        if None in (
            open_price,
            high,
            low,
            close,
        ):

            return None

        if high < low:

            return None

        return {
            "index": index,
            "timestamp": self._timestamp(
                candle
            ),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "body": abs(
                close - open_price
            ),
            "bullish": (
                close > open_price
            ),
            "bearish": (
                close < open_price
            ),
        }

    # =========================================================
    # ATR
    # =========================================================

    def calculate_atr(
        self,
        candles,
        period=14,
    ):

        normalized = []

        for index, candle in enumerate(
            candles
        ):

            item = self._normalize_candle(
                candle,
                index,
            )

            if item is not None:

                normalized.append(
                    item
                )

        if len(normalized) < 2:

            return 0.0

        true_ranges = []

        for index in range(
            1,
            len(normalized),
        ):

            current = normalized[index]

            previous = normalized[
                index - 1
            ]

            tr = max(
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

            true_ranges.append(tr)

        if not true_ranges:

            return 0.0

        selected = true_ranges[
            -period:
        ]

        return (
            sum(selected)
            / len(selected)
        )

    # =========================================================
    # DISPLACEMENT
    # =========================================================

    def _is_displacement(
        self,
        candle,
        atr,
    ):

        if atr <= 0:

            return False

        return (
            candle["body"]
            >= atr
            * self.displacement_atr
        )

    # =========================================================
    # MITIGATION
    # =========================================================

    def _track_mitigation(
        self,
        ob,
        candles,
    ):

        lower = ob["lower"]

        upper = ob["upper"]

        midpoint = (
            lower + upper
        ) / 2.0

        mitigation = {
            "touched": False,
            "partial": False,
            "midpoint": False,
            "full": False,
            "invalidated": False,
            "first_touch_index": None,
            "first_touch_timestamp": None,
            "mitigation_percent": 0.0,
        }

        for index in range(
            ob["formation_index"] + 1,
            len(candles),
        ):

            candle = candles[index]

            if candle is None:
                continue

            high = candle["high"]

            low = candle["low"]

            close = candle["close"]

            # Bullish OB invalidation:
            # candle closes below OB lower boundary.
            if (
                ob["direction"] == "BULLISH"
                and close < lower
            ):

                mitigation[
                    "invalidated"
                ] = True

                break

            # Bearish OB invalidation:
            # candle closes above OB upper boundary.
            if (
                ob["direction"] == "BEARISH"
                and close > upper
            ):

                mitigation[
                    "invalidated"
                ] = True

                break

            overlaps = (
                high >= lower
                and low <= upper
            )

            if not overlaps:
                continue

            if not mitigation["touched"]:

                mitigation[
                    "touched"
                ] = True

                mitigation[
                    "first_touch_index"
                ] = index

                mitigation[
                    "first_touch_timestamp"
                ] = candle.get(
                    "timestamp"
                )

            if (
                ob["direction"] == "BULLISH"
            ):

                penetration = max(
                    0.0,
                    upper - low,
                )

                total_range = (
                    upper - lower
                )

                if total_range > 0:

                    percent = (
                        penetration
                        / total_range
                    ) * 100.0

                    mitigation[
                        "mitigation_percent"
                    ] = min(
                        100.0,
                        percent,
                    )

                if low <= upper:

                    mitigation[
                        "partial"
                    ] = True

                if low <= midpoint:

                    mitigation[
                        "midpoint"
                    ] = True

                if low <= lower:

                    mitigation[
                        "full"
                    ] = True

            else:

                penetration = max(
                    0.0,
                    high - lower,
                )

                total_range = (
                    upper - lower
                )

                if total_range > 0:

                    percent = (
                        penetration
                        / total_range
                    ) * 100.0

                    mitigation[
                        "mitigation_percent"
                    ] = min(
                        100.0,
                        percent,
                    )

                if high >= lower:

                    mitigation[
                        "partial"
                    ] = True

                if high >= midpoint:

                    mitigation[
                        "midpoint"
                    ] = True

                if high >= upper:

                    mitigation[
                        "full"
                    ] = True

        mitigation["clean"] = (
            not mitigation["touched"]
            and not mitigation["invalidated"]
        )

        mitigation["unmitigated"] = (
            mitigation["clean"]
        )

        return mitigation

    # =========================================================
    # ORDER BLOCK DETECTION
    # =========================================================

    def detect_order_blocks(
        self,
        candles,
        symbol=None,
        timeframe=None,
    ):

        normalized = []

        for index, candle in enumerate(
            candles
        ):

            item = self._normalize_candle(
                candle,
                index,
            )

            normalized.append(
                item
            )

        atr = self.calculate_atr(
            candles
        )

        order_blocks = []

        if atr <= 0:

            return {
                "status": "INSUFFICIENT_DATA",
                "symbol": symbol,
                "timeframe": timeframe,
                "atr": atr,
                "order_blocks": [],
            }

        for index in range(
            1,
            len(normalized),
        ):

            current = normalized[index]

            previous = normalized[
                index - 1
            ]

            if (
                current is None
                or previous is None
            ):

                continue

            if not self._is_displacement(
                current,
                atr,
            ):

                continue

            # Bullish displacement:
            # Previous bearish candle
            # followed by strong bullish move.
            if (
                current["bullish"]
                and previous["bearish"]
            ):

                direction = "BULLISH"

                ob_candle = previous

            # Bearish displacement:
            # Previous bullish candle
            # followed by strong bearish move.
            elif (
                current["bearish"]
                and previous["bullish"]
            ):

                direction = "BEARISH"

                ob_candle = previous

            else:

                continue

            lower = ob_candle["low"]

            upper = ob_candle["high"]

            if upper <= lower:

                continue

            midpoint = (
                lower + upper
            ) / 2.0

            ob = {
                "id": (
                    f"{symbol or 'UNKNOWN'}_"
                    f"{timeframe or 'UNKNOWN'}_"
                    f"{direction}_{index}"
                ),

                "symbol": symbol,

                "timeframe": timeframe,

                "direction": direction,

                "type": (
                    "BULLISH_OB"
                    if direction == "BULLISH"
                    else "BEARISH_OB"
                ),

                "formation_index": (
                    ob_candle["index"]
                ),

                "formation_timestamp": (
                    ob_candle["timestamp"]
                ),

                "displacement_index": (
                    current["index"]
                ),

                "displacement_timestamp": (
                    current["timestamp"]
                ),

                "lower": lower,

                "upper": upper,

                "midpoint": midpoint,

                "range": (
                    upper - lower
                ),

                "atr": atr,

                "displacement_body": (
                    current["body"]
                ),

                "displacement_atr_ratio": (
                    current["body"]
                    / atr
                ),

                "displacement_confirmed": (
                    True
                ),

                "structure_confirmed": (
                    False
                ),

                "poi_confirmed": (
                    False
                ),

                "candidate": True,

                "clean": True,

                "unmitigated": True,

                "invalidated": False,
            }

            mitigation = (
                self._track_mitigation(
                    ob,
                    normalized,
                )
            )

            ob.update(
                mitigation
            )

            ob["clean"] = (
                mitigation["clean"]
            )

            ob["unmitigated"] = (
                mitigation["unmitigated"]
            )

            ob["invalidated"] = (
                mitigation["invalidated"]
            )

            order_blocks.append(
                ob
            )

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "atr": atr,
            "order_blocks": order_blocks,
            "bullish_order_blocks": [
                ob
                for ob in order_blocks
                if ob["direction"]
                == "BULLISH"
            ],
            "bearish_order_blocks": [
                ob
                for ob in order_blocks
                if ob["direction"]
                == "BEARISH"
            ],
            "clean_order_blocks": [
                ob
                for ob in order_blocks
                if ob["clean"]
            ],
            "mitigated_order_blocks": [
                ob
                for ob in order_blocks
                if ob["touched"]
            ],
            "count": len(
                order_blocks
            ),
        }

        self.last_analysis = (
            deepcopy(result)
        )

        logger.info(
            "OB analysis | %s | %s | "
            "Found=%s | Clean=%s",
            symbol,
            timeframe,
            result["count"],
            len(
                result[
                    "clean_order_blocks"
                ]
            ),
        )

        return result

    # =========================================================
    # POI VALIDATION
    # =========================================================

    def validate_order_block(
        self,
        order_block,
        expected_direction=None,
        current_price=None,
    ):

        ob = self._normalize_candle(
            {
                "open": order_block.get(
                    "open",
                    order_block.get(
                        "lower",
                    ),
                ),
                "high": order_block.get(
                    "upper",
                ),
                "low": order_block.get(
                    "lower",
                ),
                "close": order_block.get(
                    "close",
                    order_block.get(
                        "midpoint",
                    ),
                ),
            },
            0,
        )

        if ob is None:

            return {
                "valid": False,
                "reason": "INVALID_BOUNDS",
            }

        direction = (
            order_block.get(
                "direction"
            )
        )

        if expected_direction:

            if direction != expected_direction:

                return {
                    "valid": False,
                    "reason": (
                        "DIRECTION_MISMATCH"
                    ),
                }

        if order_block.get(
            "invalidated",
            False,
        ):

            return {
                "valid": False,
                "reason": "INVALIDATED",
            }

        if not order_block.get(
            "clean",
            False,
        ):

            return {
                "valid": False,
                "reason": "MITIGATED",
            }

        lower = self._number(
            order_block.get(
                "lower"
            )
        )

        upper = self._number(
            order_block.get(
                "upper"
            )
        )

        if (
            lower is None
            or upper is None
            or lower >= upper
        ):

            return {
                "valid": False,
                "reason": "INVALID_BOUNDS",
            }

        tapped = False

        if current_price is not None:

            price = self._number(
                current_price
            )

            if price is not None:

                tapped = (
                    lower
                    <= price
                    <= upper
                )

        return {
            "valid": True,
            "direction": direction,
            "lower": lower,
            "upper": upper,
            "midpoint": (
                lower + upper
            ) / 2.0,
            "clean": True,
            "unmitigated": True,
            "tapped": tapped,
            "poi_confirmed": False,
            "reason": (
                "VALID_OB_CANDIDATE"
            ),
        }

    # =========================================================
    # STATUS
    # =========================================================

    def get_status(self):

        return {
            "version": self.VERSION,
            "last_analysis": (
                deepcopy(
                    self.last_analysis
                )
            ),
        }

    def get_last_analysis(self):

        return deepcopy(
            self.last_analysis
        )


# =============================================================
# SINGLETON
# =============================================================

smc_order_block_engine = (
    SMCOrderBlockEngine()
)
