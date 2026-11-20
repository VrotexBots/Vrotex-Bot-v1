
"""
VROTEX BOT V1
SMC Order Block Engine
Version 2.0

Detects:
- Bullish order blocks
- Bearish order blocks
- Displacement away from the order block
- Zone boundaries and midpoint
- Partial and full mitigation
- Clean, unmitigated order-block candidates

Bullish OB:
The last bearish candle before a qualifying bullish
displacement move.

Bearish OB:
The last bullish candle before a qualifying bearish
displacement move.

A candidate is not automatically a confirmed trade POI.
Additional structure, liquidity and timeframe validation
must be performed by the master SMC engine.

This module does not execute trades.
"""

from typing import Any, Dict, List, Optional


class SMCOrderBlockEngine:

    VERSION = "2.0"

    def __init__(
        self,
        lookback: int = 100,
        displacement_atr_multiple: float = 1.0,
        atr_period: int = 14,
        mitigation_tolerance: float = 0.0
    ):
        self.lookback = max(10, int(lookback))
        self.displacement_atr_multiple = max(
            0.0, float(displacement_atr_multiple)
        )
        self.atr_period = max(2, int(atr_period))
        self.mitigation_tolerance = max(
            0.0, float(mitigation_tolerance)
        )

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # HELPERS
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

            open_price = self._number(candle.get("open"))
            high = self._number(candle.get("high"))
            low = self._number(candle.get("low"))
            close = self._number(candle.get("close"))

            if None in (
                open_price, high, low, close
            ):
                continue

            if high < low:
                continue

            if not (
                low <= open_price <= high
                and low <= close <= high
            ):
                continue

            validated.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close
            })

        return validated

    @staticmethod
    def _true_range(
        current: Dict[str, float],
        previous: Optional[Dict[str, float]]
    ) -> float:

        if previous is None:
            return current["high"] - current["low"]

        return max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

    def _calculate_atr(
        self,
        candles: List[Dict[str, float]],
        index: int
    ) -> Optional[float]:

        start = max(0, index - self.atr_period + 1)

        ranges = []

        for position in range(start, index + 1):
            previous = (
                candles[position - 1]
                if position > 0
                else None
            )

            ranges.append(
                self._true_range(
                    candles[position],
                    previous
                )
            )

        if not ranges:
            return None

        return sum(ranges) / len(ranges)

    # ---------------------------------------------------------
    # DISPLACEMENT VALIDATION
    # ---------------------------------------------------------

    def _validate_displacement(
        self,
        candles: List[Dict[str, float]],
        index: int,
        direction: str
    ) -> Dict[str, Any]:

        candle = candles[index]

        atr = self._calculate_atr(
            candles,
            index
        )

        body = abs(
            candle["close"] - candle["open"]
        )

        if atr is None or atr <= 0:
            return {
                "confirmed": False,
                "reason": "ATR_UNAVAILABLE",
                "atr": atr,
                "body_size": body
            }

        required_body = (
            atr * self.displacement_atr_multiple
        )

        if direction == "BUY":
            directional_close = (
                candle["close"] > candle["open"]
            )
        else:
            directional_close = (
                candle["close"] < candle["open"]
            )

        confirmed = (
            directional_close
            and body >= required_body
        )

        return {
            "confirmed": confirmed,
            "direction": direction,
            "atr": atr,
            "body_size": body,
            "required_body_size": required_body,
            "body_atr_ratio": body / atr
        }

    # ---------------------------------------------------------
    # ORDER BLOCK CANDIDATE DETECTION
    # ---------------------------------------------------------

    def _find_order_blocks(
        self,
        candles: List[Dict[str, float]]
    ) -> List[Dict[str, Any]]:

        candidates = []

        start = max(
            1,
            len(candles) - self.lookback
        )

        for index in range(start, len(candles)):

            candle = candles[index]

            bullish_candle = (
                candle["close"] > candle["open"]
            )

            bearish_candle = (
                candle["close"] < candle["open"]
            )

            # A bearish candle can be the origin of a
            # subsequent bullish displacement.
            if bearish_candle:

                displacement = self._validate_displacement(
                    candles,
                    index + 1,
                    "BUY"
                ) if index + 1 < len(candles) else {
                    "confirmed": False,
                    "reason": "NO_FOLLOWING_CANDLE"
                }

                if displacement["confirmed"]:
                    candidates.append({
                        "id": f"BULLISH_OB_{index}",
                        "type": "BULLISH_ORDER_BLOCK",
                        "direction": "BUY",
                        "lower": candle["low"],
                        "upper": candle["high"],
                        "midpoint": (
                            candle["low"] + candle["high"]
                        ) / 2.0,
                        "formation_index": index,
                        "displacement_index": index + 1,
                        "displacement": displacement,
                        "origin_candle": dict(candle)
                    })

            # A bullish candle can be the origin of a
            # subsequent bearish displacement.
            if bullish_candle:

                displacement = self._validate_displacement(
                    candles,
                    index + 1,
                    "SELL"
                ) if index + 1 < len(candles) else {
                    "confirmed": False,
                    "reason": "NO_FOLLOWING_CANDLE"
                }

                if displacement["confirmed"]:
                    candidates.append({
                        "id": f"BEARISH_OB_{index}",
                        "type": "BEARISH_ORDER_BLOCK",
                        "direction": "SELL",
                        "lower": candle["low"],
                        "upper": candle["high"],
                        "midpoint": (
                            candle["low"] + candle["high"]
                        ) / 2.0,
                        "formation_index": index,
                        "displacement_index": index + 1,
                        "displacement": displacement,
                        "origin_candle": dict(candle)
                    })

        return candidates

    # ---------------------------------------------------------
    # MITIGATION
    # ---------------------------------------------------------

    def _check_mitigation(
        self,
        order_block: Dict[str, Any],
        candles: List[Dict[str, float]]
    ) -> Dict[str, Any]:

        lower = order_block["lower"]
        upper = order_block["upper"]
        midpoint = order_block["midpoint"]

        direction = order_block["direction"]
        formation_index = order_block["formation_index"]

        touched = False
        midpoint_reached = False
        fully_mitigated = False

        mitigation_index = None
        deepest_price = None

        for index in range(
            order_block["displacement_index"] + 1,
            len(candles)
        ):

            candle = candles[index]

            if direction == "BUY":

                # Bullish OB is mitigated when price
                # retraces downward into its zone.
                if candle["low"] <= upper:
                    touched = True
                    mitigation_index = index
                    deepest_price = candle["low"]

                    if candle["low"] <= midpoint:
                        midpoint_reached = True

                    if (
                        candle["low"]
                        <= lower + self.mitigation_tolerance
                    ):
                        fully_mitigated = True
                        break

            else:

                # Bearish OB is mitigated when price
                # retraces upward into its zone.
                if candle["high"] >= lower:
                    touched = True
                    mitigation_index = index
                    deepest_price = candle["high"]

                    if candle["high"] >= midpoint:
                        midpoint_reached = True

                    if (
                        candle["high"]
                        >= upper - self.mitigation_tolerance
                    ):
                        fully_mitigated = True
                        break

        if fully_mitigated:
            status = "FULLY_MITIGATED"

        elif midpoint_reached:
            status = "MIDPOINT_MITIGATED"

        elif touched:
            status = "PARTIALLY_MITIGATED"

        else:
            status = "UNMITIGATED"

        return {
            "mitigated": touched,
            "partially_mitigated": (
                touched and not fully_mitigated
            ),
            "midpoint_reached": midpoint_reached,
            "fully_mitigated": fully_mitigated,
            "mitigation_status": status,
            "mitigation_index": mitigation_index,
            "deepest_price": deepest_price
        }

    # ---------------------------------------------------------
    # ENRICH ORDER BLOCKS
    # ---------------------------------------------------------

    def _enrich_order_blocks(
        self,
        candidates: List[Dict[str, Any]],
        candles: List[Dict[str, float]]
    ) -> List[Dict[str, Any]]:

        enriched = []

        for candidate in candidates:

            item = dict(candidate)

            mitigation = self._check_mitigation(
                item,
                candles
            )

            item.update(mitigation)

            item["clean"] = (
                not item["mitigated"]
                and not item["fully_mitigated"]
            )

            item["unmitigated"] = (
                not item["mitigated"]
            )

            item["valid_candidate"] = (
                item["displacement"]["confirmed"]
            )

            enriched.append(item)

        return enriched

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        candles: Any,
        current_price: Optional[float] = None
    ) -> Dict[str, Any]:

        validated = self._validate_candles(candles)

        if len(validated) < self.atr_period + 2:
            result = {
                "status": "INSUFFICIENT_DATA",
                "version": self.VERSION,
                "order_blocks": [],
                "clean_order_blocks": [],
                "bullish_order_blocks": [],
                "bearish_order_blocks": []
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
                "order_blocks": []
            }

            self.last_result = result
            return result

        candidates = self._find_order_blocks(
            validated
        )

        enriched = self._enrich_order_blocks(
            candidates,
            validated
        )

        clean = [
            item for item in enriched
            if item["clean"]
        ]

        bullish = [
            item for item in enriched
            if item["direction"] == "BUY"
        ]

        bearish = [
            item for item in enriched
            if item["direction"] == "SELL"
        ]

        clean_bullish = [
            item for item in clean
            if item["direction"] == "BUY"
        ]

        clean_bearish = [
            item for item in clean
            if item["direction"] == "SELL"
        ]

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "candle_count": len(validated),
            "current_price": current_price,

            "order_block_count": len(enriched),
            "clean_order_block_count": len(clean),

            "order_blocks": enriched,
            "clean_order_blocks": clean,

            "bullish_order_blocks": bullish,
            "bearish_order_blocks": bearish,

            "clean_bullish_order_blocks": clean_bullish,
            "clean_bearish_order_blocks": clean_bearish
        }

        self.last_result = result
        return result

    # British spelling compatibility
    def analyse(
        self,
        candles: Any,
        current_price: Optional[float] = None
    ) -> Dict[str, Any]:

        return self.analyze(candles, current_price)

    # ---------------------------------------------------------
    # DIRECTIONAL POI VALIDATION
    # ---------------------------------------------------------

    def validate_directional_order_block(
        self,
        analysis: Dict[str, Any],
        trade_direction: str
    ) -> Dict[str, Any]:

        direction = str(
            trade_direction
        ).strip().upper()

        if direction in {"BUY", "BULLISH", "LONG"}:
            expected = "BUY"

        elif direction in {"SELL", "BEARISH", "SHORT"}:
            expected = "SELL"

        else:
            return {
                "valid": False,
                "reason": "INVALID_TRADE_DIRECTION",
                "matching_order_blocks": []
            }

        clean_blocks = analysis.get(
            "clean_order_blocks", []
        )

        matching = [
            item for item in clean_blocks
            if (
                isinstance(item, dict)
                and item.get("direction") == expected
                and item.get("clean") is True
                and item.get("unmitigated") is True
                and item.get("valid_candidate") is True
            )
        ]

        return {
            "valid": bool(matching),
            "trade_direction": direction,
            "matching_order_blocks": matching,
            "count": len(matching)
        }

    # ---------------------------------------------------------
    # ADAPTER-FRIENDLY POI OUTPUT
    # ---------------------------------------------------------

    def get_poi_evidence(
        self,
        analysis: Dict[str, Any],
        trade_direction: str
    ) -> Dict[str, Any]:

        validation = self.validate_directional_order_block(
            analysis,
            trade_direction
        )

        blocks = validation["matching_order_blocks"]

        if not blocks:
            return {
                "detected": False,
                "direction": self._normal_direction(
                    trade_direction
                ),
                "clean": False,
                "unmitigated": False,
                "lower": None,
                "upper": None,
                "confirmed": False
            }

        # Prefer the most recently formed qualifying block.
        selected = max(
            blocks,
            key=lambda item: item["formation_index"]
        )

        return {
            "detected": True,
            "direction": selected["direction"],
            "clean": selected["clean"],
            "unmitigated": selected["unmitigated"],
            "lower": selected["lower"],
            "upper": selected["upper"],
            "midpoint": selected["midpoint"],
            "formation_index": selected["formation_index"],
            "confirmed": True,
            "order_block_id": selected["id"]
        }

    @staticmethod
    def _normal_direction(value: str) -> Optional[str]:
        value = str(value).strip().upper()

        if value in {"BUY", "BULLISH", "LONG"}:
            return "BUY"

        if value in {"SELL", "BEARISH", "SHORT"}:
            return "SELL"

        return None

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "SMC_ORDER_BLOCK_ENGINE",
            "version": self.VERSION,
            "status": "ACTIVE"
        }


smc_order_block_engine = SMCOrderBlockEngine()
