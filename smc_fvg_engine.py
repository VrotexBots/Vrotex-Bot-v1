"""
Vrotex Bot V1
SMC Fair Value Gap Engine
Version: 3.0

Responsibilities:
- Detect bullish and bearish FVGs
- Track mitigation
- Track midpoint mitigation
- Track full fills
- Detect invalidation
- Detect potential inverted FVGs (IFVG)
- Track timestamps and candle indexes
- Provide FVG evidence to Master SMC

FVGs are evidence/POI candidates, not standalone trade signals.
"""

import logging
from copy import deepcopy


logger = logging.getLogger("vrotex.smc_fvg")


class SMCFVGEngine:

    VERSION = "3.0"

    def __init__(self):

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
            "bullish": (
                close > open_price
            ),
            "bearish": (
                close < open_price
            ),
        }

    # =========================================================
    # MITIGATION TRACKING
    # =========================================================

    def _track_mitigation(
        self,
        fvg,
        candles,
    ):

        lower = fvg["lower"]

        upper = fvg["upper"]

        midpoint = (
            lower + upper
        ) / 2.0

        result = {
            "touched": False,
            "partial": False,
            "midpoint": False,
            "full": False,
            "invalidated": False,
            "first_touch_index": None,
            "first_touch_timestamp": None,
            "mitigation_percent": 0.0,
            "clean": True,
            "unmitigated": True,
        }

        for index in range(
            fvg["formation_index"] + 1,
            len(candles),
        ):

            candle = candles[index]

            if candle is None:
                continue

            high = candle["high"]

            low = candle["low"]

            close = candle["close"]

            # Bullish FVG invalidation:
            # Close below the FVG lower boundary.
            if (
                fvg["direction"] == "BULLISH"
                and close < lower
            ):

                result[
                    "invalidated"
                ] = True

                break

            # Bearish FVG invalidation:
            # Close above the FVG upper boundary.
            if (
                fvg["direction"] == "BEARISH"
                and close > upper
            ):

                result[
                    "invalidated"
                ] = True

                break

            overlaps = (
                high >= lower
                and low <= upper
            )

            if not overlaps:
                continue

            if not result["touched"]:

                result[
                    "touched"
                ] = True

                result[
                    "first_touch_index"
                ] = index

                result[
                    "first_touch_timestamp"
                ] = candle.get(
                    "timestamp"
                )

            width = (
                upper - lower
            )

            if width <= 0:
                continue

            if (
                fvg["direction"]
                == "BULLISH"
            ):

                penetration = (
                    upper - low
                )

                percent = (
                    penetration
                    / width
                ) * 100.0

                result[
                    "mitigation_percent"
                ] = min(
                    100.0,
                    max(
                        0.0,
                        percent,
                    ),
                )

                if low < upper:

                    result[
                        "partial"
                    ] = True

                if low <= midpoint:

                    result[
                        "midpoint"
                    ] = True

                if low <= lower:

                    result[
                        "full"
                    ] = True

            else:

                penetration = (
                    high - lower
                )

                percent = (
                    penetration
                    / width
                ) * 100.0

                result[
                    "mitigation_percent"
                ] = min(
                    100.0,
                    max(
                        0.0,
                        percent,
                    ),
                )

                if high > lower:

                    result[
                        "partial"
                    ] = True

                if high >= midpoint:

                    result[
                        "midpoint"
                    ] = True

                if high >= upper:

                    result[
                        "full"
                    ] = True

        result["clean"] = (
            not result["touched"]
            and not result["invalidated"]
        )

        result["unmitigated"] = (
            result["clean"]
        )

        return result

    # =========================================================
    # FVG DETECTION
    # =========================================================

    def detect_fvgs(
        self,
        candles,
        symbol=None,
        timeframe=None,
    ):

        normalized = []

        for index, candle in enumerate(
            candles
        ):

            normalized.append(
                self._normalize_candle(
                    candle,
                    index,
                )
            )

        fvgs = []

        if len(normalized) < 3:

            return {
                "status": "INSUFFICIENT_DATA",
                "symbol": symbol,
                "timeframe": timeframe,
                "fvgs": [],
                "count": 0,
            }

        for index in range(
            2,
            len(normalized),
        ):

            first = normalized[
                index - 2
            ]

            middle = normalized[
                index - 1
            ]

            third = normalized[
                index
            ]

            if (
                first is None
                or middle is None
                or third is None
            ):

                continue

            # ---------------------------------------------
            # Bullish FVG
            # ---------------------------------------------
            #
            # Candle 1 high < Candle 3 low
            #
            # Gap:
            # first.high -> third.low
            # ---------------------------------------------

            if (
                first["high"]
                < third["low"]
            ):

                lower = first["high"]

                upper = third["low"]

                direction = "BULLISH"

                fvg_type = "BULLISH_FVG"

            # ---------------------------------------------
            # Bearish FVG
            # ---------------------------------------------
            #
            # Candle 1 low > Candle 3 high
            #
            # Gap:
            # third.high -> first.low
            # ---------------------------------------------

            elif (
                first["low"]
                > third["high"]
            ):

                lower = third["high"]

                upper = first["low"]

                direction = "BEARISH"

                fvg_type = "BEARISH_FVG"

            else:

                continue

            if upper <= lower:

                continue

            midpoint = (
                lower + upper
            ) / 2.0

            fvg = {
                "id": (
                    f"{symbol or 'UNKNOWN'}_"
                    f"{timeframe or 'UNKNOWN'}_"
                    f"{fvg_type}_{index}"
                ),

                "symbol": symbol,

                "timeframe": timeframe,

                "direction": direction,

                "type": fvg_type,

                "formation_index": index,

                "formation_timestamp": (
                    third["timestamp"]
                ),

                "first_candle_index": (
                    first["index"]
                ),

                "first_candle_timestamp": (
                    first["timestamp"]
                ),

                "middle_candle_index": (
                    middle["index"]
                ),

                "middle_candle_timestamp": (
                    middle["timestamp"]
                ),

                "third_candle_index": (
                    third["index"]
                ),

                "third_candle_timestamp": (
                    third["timestamp"]
                ),

                "lower": lower,

                "upper": upper,

                "midpoint": midpoint,

                "width": (
                    upper - lower
                ),

                "candidate": True,

                "poi_confirmed": False,

                "displacement_confirmed": (
                    False
                ),

                "clean": True,

                "unmitigated": True,

                "invalidated": False,
            }

            mitigation = (
                self._track_mitigation(
                    fvg,
                    normalized,
                )
            )

            fvg.update(
                mitigation
            )

            fvgs.append(
                fvg
            )

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "fvgs": fvgs,

            "bullish_fvgs": [
                fvg
                for fvg in fvgs
                if fvg["direction"]
                == "BULLISH"
            ],

            "bearish_fvgs": [
                fvg
                for fvg in fvgs
                if fvg["direction"]
                == "BEARISH"
            ],

            "clean_fvgs": [
                fvg
                for fvg in fvgs
                if fvg["clean"]
            ],

            "mitigated_fvgs": [
                fvg
                for fvg in fvgs
                if fvg["touched"]
            ],

            "invalidated_fvgs": [
                fvg
                for fvg in fvgs
                if fvg["invalidated"]
            ],

            "count": len(fvgs),
        }

        self.last_analysis = (
            deepcopy(result)
        )

        logger.info(
            "FVG analysis | %s | %s | "
            "Found=%s | Clean=%s",
            symbol,
            timeframe,
            result["count"],
            len(
                result["clean_fvgs"]
            ),
        )

        return result

    # =========================================================
    # INVERTED FVG DETECTION
    # =========================================================

    def detect_ifvgs(
        self,
        fvgs,
        candles,
    ):

        normalized = []

        for index, candle in enumerate(
            candles
        ):

            normalized.append(
                self._normalize_candle(
                    candle,
                    index,
                )
            )

        inverted = []

        for fvg in fvgs:

            if not isinstance(
                fvg,
                dict,
            ):
                continue

            if fvg.get(
                "invalidated",
                False,
            ):

                continue

            original_direction = (
                fvg.get(
                    "direction"
                )
            )

            lower = self._number(
                fvg.get(
                    "lower"
                )
            )

            upper = self._number(
                fvg.get(
                    "upper"
                )
            )

            if (
                lower is None
                or upper is None
                or lower >= upper
            ):

                continue

            # Inversion is only confirmed
            # after a candle-body close
            # beyond the far boundary.

            inversion_index = None

            for index in range(
                fvg["formation_index"] + 1,
                len(normalized),
            ):

                candle = normalized[
                    index
                ]

                if candle is None:
                    continue

                if (
                    original_direction
                    == "BULLISH"
                    and candle["close"]
                    < lower
                ):

                    inversion_index = (
                        index
                    )

                    inverted_direction = (
                        "BEARISH"
                    )

                    break

                if (
                    original_direction
                    == "BEARISH"
                    and candle["close"]
                    > upper
                ):

                    inversion_index = (
                        index
                    )

                    inverted_direction = (
                        "BULLISH"
                    )

                    break

            if inversion_index is None:

                continue

            inversion_candle = (
                normalized[
                    inversion_index
                ]
            )

            inverted.append(
                {
                    **fvg,

                    "original_direction": (
                        original_direction
                    ),

                    "direction": (
                        inverted_direction
                    ),

                    "type": (
                        "BEARISH_IFVG"
                        if inverted_direction
                        == "BEARISH"
                        else "BULLISH_IFVG"
                    ),

                    "inverted": True,

                    "inversion_confirmed": (
                        True
                    ),

                    "inversion_index": (
                        inversion_index
                    ),

                    "inversion_timestamp": (
                        inversion_candle[
                            "timestamp"
                        ]
                    ),

                    "inversion_close": (
                        inversion_candle[
                            "close"
                        ]
                    ),

                    "clean": False,

                    "unmitigated": False,

                    "poi_confirmed": False,
                }
            )

        return inverted

    # =========================================================
    # VALIDATION
    # =========================================================

    def validate_fvg(
        self,
        fvg,
        expected_direction=None,
        current_price=None,
    ):

        if not isinstance(
            fvg,
            dict,
        ):

            return {
                "valid": False,
                "reason": "INVALID_FVG",
            }

        lower = self._number(
            fvg.get(
                "lower"
            )
        )

        upper = self._number(
            fvg.get(
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

        direction = (
            fvg.get(
                "direction"
            )
        )

        if expected_direction:

            if (
                direction
                != expected_direction
            ):

                return {
                    "valid": False,
                    "reason": (
                        "DIRECTION_MISMATCH"
                    ),
                }

        if fvg.get(
            "invalidated",
            False,
        ):

            return {
                "valid": False,
                "reason": "INVALIDATED",
            }

        if not fvg.get(
            "clean",
            False,
        ):

            return {
                "valid": False,
                "reason": "MITIGATED",
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
                "VALID_FVG_CANDIDATE"
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

smc_fvg_engine = SMCFVGEngine()
