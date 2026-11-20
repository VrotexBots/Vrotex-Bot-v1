
"""
VROTEX BOT V1
SMC OPPOSING LIQUIDITY ENGINE

Responsibilities:
- Identify buy-side and sell-side liquidity.
- Identify equal highs and equal lows.
- Identify external swing liquidity.
- Select opposing liquidity targets.
- Track swept and unswept liquidity.
- Provide target evidence to the SMC decision engine.

No trade execution is performed.
"""

from typing import Any, Dict, List, Optional


class SMCOpposingLiquidityEngine:

    def __init__(self, tolerance: float = 0.0):
        self.tolerance = max(0.0, float(tolerance))
        self.targets: List[Dict[str, Any]] = []
        self.last_result: Dict[str, Any] = {}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)
            if number != number or number in (
                float("inf"), float("-inf")
            ):
                return None
            return number
        except (TypeError, ValueError):
            return None

    def _normalise(
        self,
        candles: List[Dict[str, Any]]
    ) -> List[Dict[str, float]]:

        result = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            values = {
                key: self._number(candle.get(key))
                for key in ("open", "high", "low", "close")
            }

            if any(value is None for value in values.values()):
                continue

            if values["high"] < max(
                values["open"], values["close"]
            ):
                continue

            if values["low"] > min(
                values["open"], values["close"]
            ):
                continue

            if values["high"] < values["low"]:
                continue

            result.append(values)

        return result

    def identify_swings(
        self,
        candles: List[Dict[str, Any]],
        left: int = 2,
        right: int = 2,
    ) -> Dict[str, Any]:

        data = self._normalise(candles)
        left = max(1, int(left))
        right = max(1, int(right))

        highs = []
        lows = []

        for index in range(left, len(data) - right):

            current = data[index]

            surrounding = (
                data[index-left:index]
                + data[index+1:index+right+1]
            )

            if all(
                current["high"] > item["high"]
                for item in surrounding
            ):
                highs.append({
                    "price": current["high"],
                    "index": index,
                    "type": "BUY_SIDE",
                    "external": False,
                })

            if all(
                current["low"] < item["low"]
                for item in surrounding
            ):
                lows.append({
                    "price": current["low"],
                    "index": index,
                    "type": "SELL_SIDE",
                    "external": False,
                })

        if highs:
            highs[-1]["external"] = True

        if lows:
            lows[-1]["external"] = True

        return {
            "valid": bool(highs or lows),
            "highs": highs,
            "lows": lows,
        }

    def identify_equal_levels(
        self,
        swings: List[Dict[str, Any]],
        level_type: str,
    ) -> List[Dict[str, Any]]:

        if self.tolerance <= 0:
            return []

        clusters = []

        for swing in swings:
            price = self._number(swing.get("price"))

            if price is None:
                continue

            matched = None

            for cluster in clusters:
                average = sum(
                    item["price"] for item in cluster
                ) / len(cluster)

                if abs(price - average) <= self.tolerance:
                    matched = cluster
                    break

            if matched is None:
                clusters.append([{
                    "price": price,
                    "index": swing.get("index"),
                }])
            else:
                matched.append({
                    "price": price,
                    "index": swing.get("index"),
                })

        results = []

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            average = sum(
                item["price"] for item in cluster
            ) / len(cluster)

            results.append({
                "price": average,
                "type": level_type,
                "touch_count": len(cluster),
                "indices": [
                    item["index"] for item in cluster
                ],
                "status": "UNSWEPT",
            })

        return results

    def build_targets(
        self,
        swings: Dict[str, Any],
    ) -> List[Dict[str, Any]]:

        targets = []

        for swing in swings.get("highs", []):
            targets.append({
                **swing,
                "status": "UNSWEPT",
                "source": "SWING_HIGH",
            })

        for swing in swings.get("lows", []):
            targets.append({
                **swing,
                "status": "UNSWEPT",
                "source": "SWING_LOW",
            })

        targets.extend(
            self.identify_equal_levels(
                swings.get("highs", []),
                "BUY_SIDE",
            )
        )

        targets.extend(
            self.identify_equal_levels(
                swings.get("lows", []),
                "SELL_SIDE",
            )
        )

        self.targets = targets

        return targets

    def update_sweeps(
        self,
        candles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        data = self._normalise(candles)

        if not data:
            return {
                "valid": False,
                "status": "NO_VALID_CANDLES",
            }

        candle = data[-1]
        events = []

        for target in self.targets:

            if target.get("status") == "SWEPT":
                continue

            price = self._number(target.get("price"))

            if price is None:
                continue

            target_type = target.get("type")

            if target_type == "BUY_SIDE":
                swept = (
                    candle["high"] > price + self.tolerance
                    and candle["close"] < price
                )

            elif target_type == "SELL_SIDE":
                swept = (
                    candle["low"] < price - self.tolerance
                    and candle["close"] > price
                )

            else:
                continue

            if swept:
                target["status"] = "SWEPT"

                event = {
                    "type": "LIQUIDITY_SWEPT",
                    "liquidity_type": target_type,
                    "price": price,
                    "confirmed": True,
                    "candle_close": candle["close"],
                }

                events.append(event)

        return {
            "valid": True,
            "status": "SWEEP_ANALYSIS_COMPLETE",
            "events": events,
            "targets": self.targets,
        }

    def select_opposing_target(
        self,
        direction: str,
        current_price: float,
    ) -> Dict[str, Any]:

        direction = str(direction).upper()
        current_price = self._number(current_price)

        if direction not in ("BULLISH", "BEARISH"):
            return {
                "valid": False,
                "status": "INVALID_DIRECTION",
            }

        if current_price is None:
            return {
                "valid": False,
                "status": "INVALID_PRICE",
            }

        if direction == "BULLISH":
            target_type = "BUY_SIDE"
            candidates = [
                item for item in self.targets
                if item.get("type") == target_type
                and item.get("status") == "UNSWEPT"
                and self._number(item.get("price")) > current_price
            ]
            candidates.sort(
                key=lambda item: item["price"]
            )

        else:
            target_type = "SELL_SIDE"
            candidates = [
                item for item in self.targets
                if item.get("type") == target_type
                and item.get("status") == "UNSWEPT"
                and self._number(item.get("price")) < current_price
            ]
            candidates.sort(
                key=lambda item: item["price"],
                reverse=True,
            )

        if not candidates:
            return {
                "valid": False,
                "status": "NO_OPPOSING_LIQUIDITY_FOUND",
                "direction": direction,
                "target": None,
            }

        selected = candidates[0]

        result = {
            "valid": True,
            "status": "OPPOSING_TARGET_IDENTIFIED",
            "direction": direction,
            "target_type": target_type,
            "target": selected,
            "distance": abs(
                selected["price"] - current_price
            ),
            "confirmed": True,
        }

        return result

    def analyse(
        self,
        candles: List[Dict[str, Any]],
        direction: str,
        current_price: Optional[float] = None,
        left: int = 2,
        right: int = 2,
    ) -> Dict[str, Any]:

        data = self._normalise(candles)

        if len(data) < left + right + 3:
            return {
                "valid": False,
                "status": "INSUFFICIENT_CANDLES",
            }

        swings = self.identify_swings(
            data,
            left=left,
            right=right,
        )

        self.build_targets(swings)

        sweep_result = self.update_sweeps(data)

        price = (
            self._number(current_price)
            if current_price is not None
            else data[-1]["close"]
        )

        if price is None:
            return {
                "valid": False,
                "status": "INVALID_CURRENT_PRICE",
            }

        opposing = self.select_opposing_target(
            direction,
            price,
        )

        result = {
            "valid": True,
            "status": "ANALYSIS_COMPLETE",
            "direction": direction.upper(),
            "swings": swings,
            "targets": self.targets,
            "sweeps": sweep_result,
            "opposing_liquidity": opposing,
            "execution_authorized": False,
        }

        self.last_result = result

        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "module": "SMCOpposingLiquidityEngine",
            "target_count": len(self.targets),
            "targets": self.targets,
            "last_result": self.last_result,
        }


smc_opposing_liquidity_engine = SMCOpposingLiquidityEngine()
