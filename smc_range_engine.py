
"""
VROTEX BOT V1
SMC RANGE AND DEALING-RANGE ENGINE

Responsibilities:
- Identify the active dealing range.
- Calculate equilibrium (50%).
- Identify premium and discount zones.
- Track range highs and lows.
- Confirm range breaks using candle-body closes.
- Distinguish wick sweeps from confirmed breaks.

No broker execution is performed by this module.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class DealingRange:
    high: float
    low: float
    midpoint: float
    range_size: float
    premium_start: float
    discount_end: float
    source: str
    valid: bool


class SMCRangeEngine:

    def __init__(
        self,
        minimum_candles: int = 20,
        equilibrium: float = 0.50,
        premium_threshold: float = 0.50,
        discount_threshold: float = 0.50,
    ):
        self.minimum_candles = max(5, int(minimum_candles))
        self.equilibrium = float(equilibrium)
        self.premium_threshold = float(premium_threshold)
        self.discount_threshold = float(discount_threshold)

        self.last_result: Dict[str, Any] = {}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
            if result != result or result in (float("inf"), float("-inf")):
                return None
            return result
        except (TypeError, ValueError):
            return None

    def _normalise_candles(
        self,
        candles: List[Dict[str, Any]]
    ) -> List[Dict[str, float]]:

        result = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            high = self._number(candle.get("high"))
            low = self._number(candle.get("low"))
            close = self._number(candle.get("close"))
            open_price = self._number(candle.get("open"))

            if None in (high, low, close, open_price):
                continue

            if high < low:
                continue

            if high < max(open_price, close):
                continue

            if low > min(open_price, close):
                continue

            result.append({
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
            })

        return result

    def calculate_range(
        self,
        candles: List[Dict[str, Any]],
        lookback: Optional[int] = None,
        source: str = "H1"
    ) -> Dict[str, Any]:

        normalised = self._normalise_candles(candles)

        period = max(
            self.minimum_candles,
            int(lookback or self.minimum_candles)
        )

        if len(normalised) < period:
            return self._failure(
                "INSUFFICIENT_CANDLES",
                len(normalised),
                period
            )

        selected = normalised[-period:]

        range_high = max(c["high"] for c in selected)
        range_low = min(c["low"] for c in selected)

        size = range_high - range_low

        if size <= 0:
            return self._failure(
                "INVALID_RANGE",
                len(normalised),
                period
            )

        midpoint = range_low + size * self.equilibrium

        premium_start = (
            range_low + size * self.premium_threshold
        )

        discount_end = (
            range_low + size * self.discount_threshold
        )

        dealing_range = DealingRange(
            high=range_high,
            low=range_low,
            midpoint=midpoint,
            range_size=size,
            premium_start=premium_start,
            discount_end=discount_end,
            source=str(source).upper(),
            valid=True,
        )

        result = {
            "valid": True,
            "status": "RANGE_IDENTIFIED",
            "source": dealing_range.source,
            "candles_used": period,
            "range": asdict(dealing_range),
            "equilibrium": midpoint,
            "premium": {
                "from": premium_start,
                "to": range_high,
            },
            "discount": {
                "from": range_low,
                "to": discount_end,
            },
            "price_position": None,
        }

        self.last_result = result
        return result

    def classify_price(
        self,
        price: float,
        range_data: Dict[str, Any]
    ) -> Dict[str, Any]:

        price = self._number(price)

        if price is None:
            return {
                "valid": False,
                "error": "INVALID_PRICE",
            }

        if not range_data.get("valid"):
            return {
                "valid": False,
                "error": "INVALID_DEALING_RANGE",
            }

        data = range_data["range"]

        high = data["high"]
        low = data["low"]
        midpoint = data["midpoint"]

        if price > high:
            zone = "ABOVE_RANGE"
        elif price < low:
            zone = "BELOW_RANGE"
        elif price > midpoint:
            zone = "PREMIUM"
        elif price < midpoint:
            zone = "DISCOUNT"
        else:
            zone = "EQUILIBRIUM"

        position = (
            (price - low) / (high - low)
            if high > low else None
        )

        return {
            "valid": True,
            "price": price,
            "zone": zone,
            "position_percent": round(position * 100, 2)
            if position is not None else None,
            "equilibrium": midpoint,
            "bullish_location": zone == "DISCOUNT",
            "bearish_location": zone == "PREMIUM",
        }

    def detect_range_break(
        self,
        candles: List[Dict[str, Any]],
        range_data: Dict[str, Any]
    ) -> Dict[str, Any]:

        normalised = self._normalise_candles(candles)

        if not normalised:
            return {
                "valid": False,
                "status": "NO_CANDLE_DATA",
            }

        if not range_data.get("valid"):
            return {
                "valid": False,
                "status": "INVALID_RANGE",
            }

        candle = normalised[-1]
        high = range_data["range"]["high"]
        low = range_data["range"]["low"]

        if candle["close"] > high:
            direction = "BULLISH"
            confirmed = True
            sweep = False

        elif candle["close"] < low:
            direction = "BEARISH"
            confirmed = True
            sweep = False

        elif candle["high"] > high and candle["close"] <= high:
            direction = "BULLISH"
            confirmed = False
            sweep = True

        elif candle["low"] < low and candle["close"] >= low:
            direction = "BEARISH"
            confirmed = False
            sweep = True

        else:
            direction = "NONE"
            confirmed = False
            sweep = False

        if confirmed:
            status = "BODY_CLOSE_BREAK_CONFIRMED"
        elif sweep:
            status = "WICK_SWEEP_ONLY"
        else:
            status = "INSIDE_RANGE"

        return {
            "valid": True,
            "status": status,
            "direction": direction,
            "confirmed": confirmed,
            "wick_sweep": sweep,
            "close": candle["close"],
            "range_high": high,
            "range_low": low,
        }

    def analyse(
        self,
        candles: List[Dict[str, Any]],
        current_price: Optional[float] = None,
        lookback: Optional[int] = None,
        source: str = "H1"
    ) -> Dict[str, Any]:

        range_result = self.calculate_range(
            candles=candles,
            lookback=lookback,
            source=source,
        )

        if not range_result.get("valid"):
            return range_result

        normalised = self._normalise_candles(candles)

        price = (
            self._number(current_price)
            if current_price is not None
            else normalised[-1]["close"]
        )

        if price is None:
            return self._failure(
                "INVALID_CURRENT_PRICE",
                len(normalised),
                lookback or self.minimum_candles
            )

        position = self.classify_price(
            price,
            range_result
        )

        breakout = self.detect_range_break(
            candles,
            range_result
        )

        result = {
            "valid": True,
            "status": "ANALYSIS_COMPLETE",
            "source": str(source).upper(),
            "range": range_result["range"],
            "price_position": position,
            "breakout": breakout,
            "rules": {
                "equilibrium": self.equilibrium,
                "premium_threshold": self.premium_threshold,
                "discount_threshold": self.discount_threshold,
                "wick_only_is_not_confirmed_break": True,
                "body_close_required": True,
            },
        }

        self.last_result = result
        return result

    def _failure(
        self,
        reason: str,
        received: int,
        required: int
    ) -> Dict[str, Any]:

        result = {
            "valid": False,
            "status": reason,
            "candles_received": received,
            "candles_required": required,
        }

        self.last_result = result
        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "module": "SMCRangeEngine",
            "ready": True,
            "last_analysis": self.last_result,
        }


smc_range_engine = SMCRangeEngine()
