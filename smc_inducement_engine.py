"""
Vrotex Bot V1
SMC Inducement Engine

Detects:
- Potential inducement levels.
- Equal highs and equal lows.
- Liquidity resting around a protected level.
- Wick sweeps and candle-body breaks.
- Potential inducement status.

This module provides evidence only.
It does not independently authorize trades.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class InducementResult:
    level_id: str
    direction: str
    price: float
    status: str
    touch_count: int
    sweep_index: Optional[int]
    break_index: Optional[int]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SMCInducementEngine:

    def __init__(
        self,
        tolerance: float = 0.0001,
        minimum_touches: int = 2,
    ):
        if tolerance <= 0:
            raise ValueError("tolerance must be positive")

        if minimum_touches < 2:
            raise ValueError("minimum_touches must be at least 2")

        self.tolerance = float(tolerance)
        self.minimum_touches = minimum_touches
        self.levels: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _number(value: Any, field: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid {field}")

        if result != result or result in (
            float("inf"),
            float("-inf"),
        ):
            raise ValueError(f"Non-finite {field}")

        return result

    @staticmethod
    def _validate_direction(direction: str) -> str:
        direction = direction.upper()

        if direction not in ("BUY_SIDE", "SELL_SIDE"):
            raise ValueError("Direction must be BUY_SIDE or SELL_SIDE")

        return direction

    def register_level(
        self,
        level_id: str,
        direction: str,
        price: float,
        protected_level: Optional[float] = None,
    ) -> Dict[str, Any]:

        if not isinstance(level_id, str) or not level_id.strip():
            raise ValueError("level_id must be a non-empty string")

        if level_id in self.levels:
            raise ValueError(f"Level already exists: {level_id}")

        direction = self._validate_direction(direction)
        price = self._number(price, "price")

        if price <= 0:
            raise ValueError("price must be positive")

        if protected_level is not None:
            protected_level = self._number(
                protected_level,
                "protected_level",
            )

        self.levels[level_id] = {
            "level_id": level_id,
            "direction": direction,
            "price": price,
            "protected_level": protected_level,
            "status": "WATCHING",
            "touch_count": 0,
            "sweep_index": None,
            "break_index": None,
            "last_processed_index": None,
        }

        return self.get_level(level_id)

    def get_level(self, level_id: str) -> Dict[str, Any]:
        if level_id not in self.levels:
            raise KeyError(f"Unknown inducement level: {level_id}")

        return dict(self.levels[level_id])

    def _result(
        self,
        level: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:

        return InducementResult(
            level_id=level["level_id"],
            direction=level["direction"],
            price=level["price"],
            status=level["status"],
            touch_count=level["touch_count"],
            sweep_index=level["sweep_index"],
            break_index=level["break_index"],
            reason=reason,
        ).to_dict()

    def detect_equal_levels(
        self,
        candles: List[Dict[str, Any]],
        direction: str,
    ) -> List[Dict[str, Any]]:

        direction = self._validate_direction(direction)

        if not isinstance(candles, list):
            raise ValueError("candles must be a list")

        field = "high" if direction == "BUY_SIDE" else "low"

        values = []

        for index, raw in enumerate(candles):
            if not isinstance(raw, dict):
                raise ValueError("Invalid candle")

            price = self._number(raw.get(field), field)

            if price <= 0:
                raise ValueError("Candle prices must be positive")

            values.append((index, price))

        clusters = []

        for index, price in values:
            matched = None

            for cluster in clusters:
                if abs(price - cluster["reference_price"]) <= self.tolerance:
                    matched = cluster
                    break

            if matched is None:
                clusters.append({
                    "reference_price": price,
                    "indices": [index],
                    "prices": [price],
                })
            else:
                matched["indices"].append(index)
                matched["prices"].append(price)

        results = []

        for cluster in clusters:
            if len(cluster["indices"]) < self.minimum_touches:
                continue

            results.append({
                "direction": direction,
                "level_price": sum(cluster["prices"]) / len(
                    cluster["prices"]
                ),
                "touch_count": len(cluster["indices"]),
                "indices": cluster["indices"],
            })

        return results

    def update_level(
        self,
        level_id: str,
        candles: List[Dict[str, Any]],
        start_index: int = 0,
    ) -> Dict[str, Any]:

        if level_id not in self.levels:
            raise KeyError(f"Unknown inducement level: {level_id}")

        if not isinstance(candles, list):
            raise ValueError("candles must be a list")

        if not isinstance(start_index, int) or start_index < 0:
            raise ValueError("start_index must be non-negative")

        level = self.levels[level_id]

        if level["status"] in ("SWEPT", "BODY_BROKEN"):
            return self._result(
                level,
                "LEVEL_ALREADY_RESOLVED",
            )

        for index in range(start_index, len(candles)):

            if (
                level["last_processed_index"] is not None
                and index <= level["last_processed_index"]
            ):
                continue

            raw = candles[index]

            if not isinstance(raw, dict):
                raise ValueError("Invalid candle")

            candle = {
                field: self._number(raw.get(field), field)
                for field in ("open", "high", "low", "close")
            }

            if candle["high"] < candle["low"]:
                raise ValueError("Candle high cannot be below low")

            if not (
                candle["low"] <= candle["open"] <= candle["high"]
                and candle["low"] <= candle["close"] <= candle["high"]
            ):
                raise ValueError("Invalid candle price range")

            price = level["price"]

            if level["direction"] == "BUY_SIDE":

                touched = candle["high"] >= (
                    price - self.tolerance
                )

                swept = (
                    candle["high"] > price + self.tolerance
                    and candle["close"] < price
                )

                body_broken = candle["close"] > price

            else:

                touched = candle["low"] <= (
                    price + self.tolerance
                )

                swept = (
                    candle["low"] < price - self.tolerance
                    and candle["close"] > price
                )

                body_broken = candle["close"] < price

            if touched:
                level["touch_count"] += 1

            level["last_processed_index"] = index

            if swept:
                level["status"] = "SWEPT"
                level["sweep_index"] = index

                return self._result(
                    level,
                    "LIQUIDITY_SWEEP_DETECTED",
                )

            if body_broken:
                level["status"] = "BODY_BROKEN"
                level["break_index"] = index

                return self._result(
                    level,
                    "CANDLE_BODY_CLOSED_BEYOND_LEVEL",
                )

        return self._result(level, "UPDATE_COMPLETE")

    def update_all(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:

        results = {}

        for level_id, level in list(self.levels.items()):
            if level["status"] in ("SWEPT", "BODY_BROKEN"):
                continue

            results[level_id] = self.update_level(
                level_id,
                candles,
            )

        return results

    def get_active_levels(self) -> List[Dict[str, Any]]:
        return [
            dict(level)
            for level in self.levels.values()
            if level["status"] == "WATCHING"
        ]

    def get_status(self) -> Dict[str, Any]:

        counts = {
            "WATCHING": 0,
            "SWEPT": 0,
            "BODY_BROKEN": 0,
        }

        for level in self.levels.values():
            counts[level["status"]] += 1

        return {
            "total_levels": len(self.levels),
            "states": counts,
        }


# Shared engine instance
smc_inducement_engine = SMCInducementEngine()
