
"""
VROTEX BOT V1
SMC Premium / Discount Engine
Version 2.0

Responsibilities:
- Calculate dealing-range equilibrium.
- Identify premium and discount zones.
- Validate bullish and bearish location.
- Calculate Fibonacci retracement levels.
- Support bullish and bearish range anchors.

Bullish dealing range:
Strong low -> weak high.

Bearish dealing range:
Strong high -> weak low.

BUY setups should form in discount.
SELL setups should form in premium.

This module does not execute trades.
"""

from typing import Any, Dict, Optional


class SMCPremiumDiscountEngine:

    VERSION = "2.0"

    def __init__(
        self,
        equilibrium: float = 0.50,
        premium_threshold: float = 0.50,
        discount_threshold: float = 0.50
    ):
        self.equilibrium = float(equilibrium)
        self.premium_threshold = float(premium_threshold)
        self.discount_threshold = float(discount_threshold)

        self.last_result: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            number = float(value)

            if number != number:
                return None

            return number

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _direction(value: Any) -> Optional[str]:
        if value is None:
            return None

        value = str(value).strip().upper()

        if value in {"BUY", "BULLISH", "LONG"}:
            return "BUY"

        if value in {"SELL", "BEARISH", "SHORT"}:
            return "SELL"

        return None

    # ---------------------------------------------------------
    # RANGE VALIDATION
    # ---------------------------------------------------------

    def _validate_range(
        self,
        range_high: Any,
        range_low: Any
    ) -> Optional[Dict[str, float]]:

        high = self._number(range_high)
        low = self._number(range_low)

        if high is None or low is None:
            return None

        if low <= 0 or high <= low:
            return None

        return {
            "high": high,
            "low": low,
            "size": high - low
        }

    # ---------------------------------------------------------
    # FIBONACCI LEVELS
    # ---------------------------------------------------------

    def calculate_fibonacci(
        self,
        range_high: float,
        range_low: float,
        direction: str
    ) -> Dict[str, float]:

        size = range_high - range_low

        if direction == "BUY":
            return {
                "0.0": range_low,
                "0.236": range_low + size * 0.236,
                "0.382": range_low + size * 0.382,
                "0.5": range_low + size * 0.5,
                "0.618": range_low + size * 0.618,
                "0.705": range_low + size * 0.705,
                "0.786": range_low + size * 0.786,
                "1.0": range_high
            }

        return {
            "0.0": range_high,
            "0.236": range_high - size * 0.236,
            "0.382": range_high - size * 0.382,
            "0.5": range_high - size * 0.5,
            "0.618": range_high - size * 0.618,
            "0.705": range_high - size * 0.705,
            "0.786": range_high - size * 0.786,
            "1.0": range_low
        }

    # ---------------------------------------------------------
    # LOCATION CLASSIFICATION
    # ---------------------------------------------------------

    def classify_location(
        self,
        current_price: float,
        range_high: float,
        range_low: float
    ) -> Dict[str, Any]:

        size = range_high - range_low

        if size <= 0:
            return {
                "valid": False,
                "reason": "INVALID_RANGE"
            }

        equilibrium = range_low + size * self.equilibrium

        position = (
            current_price - range_low
        ) / size

        if position < self.discount_threshold:
            location = "DISCOUNT"

        elif position > self.premium_threshold:
            location = "PREMIUM"

        else:
            location = "EQUILIBRIUM"

        return {
            "valid": True,
            "location": location,
            "position_percent": position * 100,
            "equilibrium": equilibrium,
            "range_high": range_high,
            "range_low": range_low,
            "range_size": size
        }

    # ---------------------------------------------------------
    # MAIN ANALYSIS
    # ---------------------------------------------------------

    def analyze(
        self,
        range_high: Any,
        range_low: Any,
        current_price: Any,
        direction: str,
        range_source: str = "STRUCTURAL"
    ) -> Dict[str, Any]:

        direction = self._direction(direction)

        validated_range = self._validate_range(
            range_high,
            range_low
        )

        price = self._number(current_price)

        if direction is None:
            result = {
                "status": "INVALID_DIRECTION",
                "version": self.VERSION,
                "valid": False
            }

            self.last_result = result
            return result

        if validated_range is None:
            result = {
                "status": "INVALID_RANGE",
                "version": self.VERSION,
                "valid": False
            }

            self.last_result = result
            return result

        if price is None or price <= 0:
            result = {
                "status": "INVALID_CURRENT_PRICE",
                "version": self.VERSION,
                "valid": False
            }

            self.last_result = result
            return result

        high = validated_range["high"]
        low = validated_range["low"]

        location = self.classify_location(
            price,
            high,
            low
        )

        fibonacci = self.calculate_fibonacci(
            high,
            low,
            direction
        )

        if direction == "BUY":
            directional_valid = (
                location["location"] == "DISCOUNT"
            )

        else:
            directional_valid = (
                location["location"] == "PREMIUM"
            )

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "valid": True,

            "direction": direction,
            "range_source": range_source,

            "range": validated_range,
            "current_price": price,

            "location": location["location"],
            "position_percent": location[
                "position_percent"
            ],

            "equilibrium": location["equilibrium"],

            "premium": {
                "upper": high,
                "lower": location["equilibrium"]
            },

            "discount": {
                "upper": location["equilibrium"],
                "lower": low
            },

            "fibonacci": fibonacci,

            "directional_location_valid": (
                directional_valid
            ),

            "setup_location_confirmed": (
                directional_valid
            )
        }

        self.last_result = result
        return result

    # British spelling compatibility
    def analyse(
        self,
        range_high: Any,
        range_low: Any,
        current_price: Any,
        direction: str,
        range_source: str = "STRUCTURAL"
    ) -> Dict[str, Any]:

        return self.analyze(
            range_high,
            range_low,
            current_price,
            direction,
            range_source
        )

    # ---------------------------------------------------------
    # ADAPTER-FRIENDLY POI LOCATION CHECK
    # ---------------------------------------------------------

    def validate_setup_location(
        self,
        analysis: Dict[str, Any],
        direction: str
    ) -> Dict[str, Any]:

        expected = self._direction(direction)

        if expected is None:
            return {
                "valid": False,
                "reason": "INVALID_DIRECTION"
            }

        location = analysis.get("location")

        if expected == "BUY":
            valid = location == "DISCOUNT"

        else:
            valid = location == "PREMIUM"

        return {
            "valid": valid,
            "direction": expected,
            "location": location,
            "equilibrium": analysis.get("equilibrium"),
            "reason": (
                "CORRECT_DIRECTIONAL_LOCATION"
                if valid
                else "PRICE_NOT_IN_REQUIRED_ZONE"
            )
        }

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_last_result(self) -> Dict[str, Any]:
        return dict(self.last_result)

    def get_status(self) -> Dict[str, Any]:
        return {
            "component": "SMC_PREMIUM_DISCOUNT_ENGINE",
            "version": self.VERSION,
            "status": "ACTIVE"
        }


smc_premium_discount_engine = SMCPremiumDiscountEngine()
