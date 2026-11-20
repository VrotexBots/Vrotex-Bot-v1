
"""
Vrotex Bot V1 - SMC Liquidity Engine

Detects:
- Buy-side liquidity (BSL)
- Sell-side liquidity (SSL)
- Equal highs and equal lows
- Previous swing liquidity
- Liquidity clusters
- Wick sweeps and rejection
- Potential liquidity targets

A liquidity sweep is not automatically a reversal
or an entry signal.

All prices must be supplied using the instrument's
actual quoted precision.
"""

from typing import Any, Dict, List


class SMCLiquidityEngine:

    VERSION = "1.0"

    def __init__(
        self,
        tolerance_by_instrument=None,
        minimum_cluster_touches=2,
    ):
        if minimum_cluster_touches < 2:
            raise ValueError(
                "minimum_cluster_touches must be at least 2"
            )

        self.minimum_cluster_touches = minimum_cluster_touches

        self.tolerance_by_instrument = (
            tolerance_by_instrument or {}
        )

        self.total_analyses = 0
        self.last_result = None

    @staticmethod
    def _validate_candles(candles):
        if not isinstance(candles, list):
            raise TypeError("Candles must be a list")

        validated = []

        for index, candle in enumerate(candles):
            if not isinstance(candle, dict):
                raise ValueError(
                    f"Candle {index} must be a dictionary"
                )

            item = {}

            for field in ("open", "high", "low", "close"):
                try:
                    item[field] = float(candle[field])
                except (KeyError, TypeError, ValueError):
                    raise ValueError(
                        f"Candle {index} has invalid {field}"
                    )

            if item["high"] < max(
                item["open"],
                item["close"],
                item["low"],
            ):
                raise ValueError(
                    f"Candle {index} has invalid high"
                )

            if item["low"] > min(
                item["open"],
                item["close"],
                item["high"],
            ):
                raise ValueError(
                    f"Candle {index} has invalid low"
                )

            validated.append(item)

        return validated

    def _get_tolerance(self, instrument):
        tolerance = self.tolerance_by_instrument.get(
            instrument
        )

        if tolerance is None:
            return None

        tolerance = float(tolerance)

        if tolerance < 0:
            raise ValueError(
                "Liquidity tolerance cannot be negative"
            )

        return tolerance

    def detect_equal_levels(
        self,
        swings,
        tolerance,
    ):
        if tolerance is None:
            return {
                "equal_highs": [],
                "equal_lows": [],
                "status": "CALIBRATION_REQUIRED",
            }

        highs = [
            item for item in swings
            if item.get("type") == "HIGH"
        ]

        lows = [
            item for item in swings
            if item.get("type") == "LOW"
        ]

        equal_highs = self._cluster_levels(
            highs,
            tolerance,
            "EQUAL_HIGHS",
        )

        equal_lows = self._cluster_levels(
            lows,
            tolerance,
            "EQUAL_LOWS",
        )

        return {
            "equal_highs": equal_highs,
            "equal_lows": equal_lows,
            "status": "ANALYZED",
        }

    def _cluster_levels(
        self,
        levels,
        tolerance,
        cluster_type,
    ):
        clusters = []
        used = set()

        for index, first in enumerate(levels):

            if index in used:
                continue

            cluster = [first]
            used.add(index)

            for other_index in range(
                index + 1,
                len(levels)
            ):
                if other_index in used:
                    continue

                other = levels[other_index]

                if abs(
                    float(first["price"])
                    - float(other["price"])
                ) <= tolerance:
                    cluster.append(other)
                    used.add(other_index)

            if len(cluster) >= self.minimum_cluster_touches:
                prices = [
                    float(item["price"])
                    for item in cluster
                ]

                clusters.append({
                    "type": cluster_type,
                    "touches": len(cluster),
                    "level": sum(prices) / len(prices),
                    "first_index": min(
                        item["index"] for item in cluster
                    ),
                    "last_index": max(
                        item["index"] for item in cluster
                    ),
                })

        return clusters

    def identify_liquidity_pools(
        self,
        swings,
        equal_levels,
    ):
        pools = []

        for swing in swings:
            if swing.get("type") == "HIGH":
                pools.append({
                    "type": "BUY_SIDE_LIQUIDITY",
                    "level": float(swing["price"]),
                    "source": "SWING_HIGH",
                    "index": swing["index"],
                })

            elif swing.get("type") == "LOW":
                pools.append({
                    "type": "SELL_SIDE_LIQUIDITY",
                    "level": float(swing["price"]),
                    "source": "SWING_LOW",
                    "index": swing["index"],
                })

        for cluster in equal_levels.get(
            "equal_highs", []
        ):
            pools.append({
                "type": "BUY_SIDE_LIQUIDITY",
                "level": cluster["level"],
                "source": "EQUAL_HIGHS",
                "touches": cluster["touches"],
            })

        for cluster in equal_levels.get(
            "equal_lows", []
        ):
            pools.append({
                "type": "SELL_SIDE_LIQUIDITY",
                "level": cluster["level"],
                "source": "EQUAL_LOWS",
                "touches": cluster["touches"],
            })

        return pools

    def detect_sweeps(
        self,
        candles,
        liquidity_pools,
    ):
        if not candles:
            return []

        candle = candles[-1]
        candle_index = len(candles) - 1

        sweeps = []

        for pool in liquidity_pools:
            level = pool["level"]

            if pool["type"] == "BUY_SIDE_LIQUIDITY":

                if (
                    candle["high"] > level
                    and candle["close"] < level
                ):
                    sweeps.append({
                        "type": "BUY_SIDE_SWEEP",
                        "level": level,
                        "candle_index": candle_index,
                        "rejection_confirmed": True,
                        "confirmation": (
                            "WICK_ABOVE_LEVEL_CLOSE_BELOW"
                        ),
                    })

            elif pool["type"] == "SELL_SIDE_LIQUIDITY":

                if (
                    candle["low"] < level
                    and candle["close"] > level
                ):
                    sweeps.append({
                        "type": "SELL_SIDE_SWEEP",
                        "level": level,
                        "candle_index": candle_index,
                        "rejection_confirmed": True,
                        "confirmation": (
                            "WICK_BELOW_LEVEL_CLOSE_ABOVE"
                        ),
                    })

        return sweeps

    def identify_external_targets(
        self,
        current_price,
        liquidity_pools,
    ):
        current_price = float(current_price)

        above = [
            pool for pool in liquidity_pools
            if pool["level"] > current_price
        ]

        below = [
            pool for pool in liquidity_pools
            if pool["level"] < current_price
        ]

        nearest_bsl = (
            min(above, key=lambda item: item["level"])
            if above else None
        )

        nearest_ssl = (
            max(below, key=lambda item: item["level"])
            if below else None
        )

        return {
            "nearest_buy_side_target": nearest_bsl,
            "nearest_sell_side_target": nearest_ssl,
        }

    def analyze(
        self,
        instrument,
        candles,
        swings,
    ):
        candles = self._validate_candles(candles)

        if not isinstance(swings, list):
            raise TypeError("Swings must be a list")

        if not candles:
            return {
                "status": "INSUFFICIENT_DATA",
                "instrument": instrument,
            }

        tolerance = self._get_tolerance(instrument)

        equal_levels = self.detect_equal_levels(
            swings,
            tolerance,
        )

        pools = self.identify_liquidity_pools(
            swings,
            equal_levels,
        )

        sweeps = self.detect_sweeps(
            candles,
            pools,
        )

        targets = self.identify_external_targets(
            candles[-1]["close"],
            pools,
        )

        self.total_analyses += 1

        result = {
            "status": (
                "ANALYZED"
                if tolerance is not None
                else "PARTIAL_CALIBRATION_REQUIRED"
            ),
            "instrument": instrument,
            "tolerance": tolerance,
            "liquidity_pools": pools,
            "equal_levels": equal_levels,
            "sweeps": sweeps,
            "external_targets": targets,
            "trade_authorized": False,
        }

        self.last_result = result

        return result

    def get_status(self):
        return {
            "component": "SMC_LIQUIDITY_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "total_analyses": self.total_analyses,
            "calibrated_instruments": list(
                self.tolerance_by_instrument.keys()
            ),
        }


smc_liquidity_engine = SMCLiquidityEngine()
