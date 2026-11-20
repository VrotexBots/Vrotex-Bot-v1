
"""
Vrotex Bot V1 - SMC Premium and Discount Engine

Responsibilities:
- Calculate dealing ranges
- Identify equilibrium at 50%
- Identify premium and discount zones
- Calculate Fibonacci retracement levels
- Apply bullish and bearish anchor rules
- Identify the current price's dealing-range position

Approved V1 rules:

Bullish:
Strong low -> weak high.
Prefer demand and long opportunities in discount.

Bearish:
Strong high -> weak low.
Prefer supply and short opportunities in premium.

The engine does not independently identify strong or weak
swings. Those must be supplied by confirmed market analysis.
"""

from typing import Dict, Optional


class SMCPremiumDiscountEngine:

    VERSION = "1.0"

    FIBONACCI_LEVELS = (
        0.0,
        0.236,
        0.382,
        0.5,
        0.618,
        0.705,
        0.786,
        1.0,
    )

    def __init__(self):
        self.total_analyses = 0
        self.last_result = None

    @staticmethod
    def _validate_price(value, name):
        try:
            price = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{name} must be a valid number"
            )

        if price <= 0:
            raise ValueError(
                f"{name} must be greater than zero"
            )

        return price

    def calculate_dealing_range(
        self,
        strong_price,
        weak_price,
        direction,
    ):
        direction = str(direction).upper()

        if direction not in ("BULLISH", "BEARISH"):
            raise ValueError(
                "Direction must be BULLISH or BEARISH"
            )

        strong_price = self._validate_price(
            strong_price,
            "strong_price",
        )

        weak_price = self._validate_price(
            weak_price,
            "weak_price",
        )

        if direction == "BULLISH":
            if strong_price >= weak_price:
                raise ValueError(
                    "Bullish range requires strong low "
                    "below weak high"
                )

            low = strong_price
            high = weak_price

        else:
            if strong_price <= weak_price:
                raise ValueError(
                    "Bearish range requires strong high "
                    "above weak low"
                )

            high = strong_price
            low = weak_price

        return {
            "direction": direction,
            "strong_price": strong_price,
            "weak_price": weak_price,
            "range_low": low,
            "range_high": high,
            "range_size": high - low,
            "equilibrium": (high + low) / 2,
        }

    def calculate_fibonacci(self, dealing_range):
        low = dealing_range["range_low"]
        high = dealing_range["range_high"]
        size = high - low

        levels = {}

        for ratio in self.FIBONACCI_LEVELS:

            if dealing_range["direction"] == "BULLISH":
                price = high - (size * ratio)
            else:
                price = low + (size * ratio)

            levels[f"{ratio:.3f}"] = round(
                price,
                10,
            )

        return levels

    def classify_price(
        self,
        current_price,
        dealing_range,
    ):
        current_price = self._validate_price(
            current_price,
            "current_price",
        )

        low = dealing_range["range_low"]
        high = dealing_range["range_high"]
        equilibrium = dealing_range["equilibrium"]

        if current_price < low:
            return "BELOW_DEALING_RANGE"

        if current_price > high:
            return "ABOVE_DEALING_RANGE"

        if current_price == equilibrium:
            return "EQUILIBRIUM"

        if current_price < equilibrium:
            return "DISCOUNT"

        return "PREMIUM"

    def analyze(
        self,
        direction,
        strong_price,
        weak_price,
        current_price,
    ):
        dealing_range = self.calculate_dealing_range(
            strong_price,
            weak_price,
            direction,
        )

        current_price = self._validate_price(
            current_price,
            "current_price",
        )

        fibonacci = self.calculate_fibonacci(
            dealing_range
        )

        position = self.classify_price(
            current_price,
            dealing_range,
        )

        direction = direction.upper()

        if direction == "BULLISH":
            preferred_zone = "DISCOUNT"
            preferred_action = "LOOK_FOR_BUY_SETUP"

        else:
            preferred_zone = "PREMIUM"
            preferred_action = "LOOK_FOR_SELL_SETUP"

        if position == "EQUILIBRIUM":
            recommendation = "WAIT_FOR_CLEAR_ZONE"

        elif position in (
            "BELOW_DEALING_RANGE",
            "ABOVE_DEALING_RANGE",
        ):
            recommendation = "OUTSIDE_DEALING_RANGE"

        elif position == preferred_zone:
            recommendation = preferred_action

        else:
            recommendation = "COUNTER_ZONE"

        self.total_analyses += 1

        result = {
            "status": "ANALYZED",
            "version": self.VERSION,
            "direction": direction,
            "dealing_range": dealing_range,
            "current_price": current_price,
            "position": position,
            "preferred_zone": preferred_zone,
            "recommendation": recommendation,
            "fibonacci_levels": fibonacci,
            "trade_authorized": False,
        }

        self.last_result = result

        return result

    def get_status(self):
        return {
            "component": "SMC_PREMIUM_DISCOUNT_ENGINE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "total_analyses": self.total_analyses,
            "equilibrium": 0.50,
            "fibonacci_levels": list(
                self.FIBONACCI_LEVELS
            ),
        }


smc_premium_discount_engine = SMCPremiumDiscountEngine()
