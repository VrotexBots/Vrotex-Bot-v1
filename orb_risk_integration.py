"""Vrotex Bot V1 - ORB Shared Risk Integration.

Uses the existing risk_manager.py singleton. ORB remains independently
authorized by CentralAuthorizationEngine; this module applies the shared
account risk checks and calculates volume only from broker-supplied
value-per-price-unit-per-lot data. It never submits an order.
"""

from __future__ import annotations


class ORBRiskIntegrationError(ValueError):
    """Raised when ORB risk inputs are malformed or unavailable."""


class ORBSharedRiskGate:
    VERSION = "2.0"

    def __init__(self, manager=None):
        if manager is None:
            from risk_manager import risk_manager
            manager = risk_manager
        self.risk_manager = manager

    @staticmethod
    def _read(value, key, default=None):
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _positive(value, name):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ORBRiskIntegrationError(
                f"{name} must be a positive finite number."
            )
        if number <= 0 or number != number or number in (float("inf"), float("-inf")):
            raise ORBRiskIntegrationError(
                f"{name} must be a positive finite number."
            )
        return number

    def evaluate_authorized_candidate(
        self,
        authorization,
        *,
        account_equity,
        value_per_price_unit_per_lot,
        spread,
        maximum_spread=None,
        spread_valid=None,
    ):
        if not isinstance(authorization, dict):
            raise ORBRiskIntegrationError("authorization must be a dictionary.")

        if (
            authorization.get("strategy") != "ORB"
            or authorization.get("strategy_authorized") is not True
        ):
            return {
                "success": False,
                "strategy": "ORB",
                "risk_approved": False,
                "execution_authorized": False,
                "reason": "ORB_CENTRAL_STRATEGY_AUTHORIZATION_REQUIRED",
            }

        equity = self._positive(account_equity, "account_equity")
        unit_value = self._positive(
            value_per_price_unit_per_lot,
            "value_per_price_unit_per_lot",
        )

        risk_result = self.risk_manager.check_orb_trade(
            authorization,
            spread=spread,
            maximum_spread=maximum_spread,
            spread_valid=spread_valid,
        )

        if not isinstance(risk_result, dict) or risk_result.get("approved") is not True:
            return {
                "success": False,
                "strategy": "ORB",
                "symbol": authorization.get("symbol"),
                "risk_approved": False,
                "execution_authorized": False,
                "risk_report": risk_result,
                "reason": (
                    risk_result.get("reason", "SHARED_RISK_REJECTED")
                    if isinstance(risk_result, dict)
                    else "SHARED_RISK_REJECTED"
                ),
            }

        sizing, sizing_reason = self.risk_manager.calculate_position_size(
            account_balance=equity,
            entry_price=authorization.get("entry_price"),
            stop_loss=authorization.get("stop_loss"),
            risk_percent=risk_result.get("risk_percent"),
            value_per_price_unit_per_lot=unit_value,
        )

        if not isinstance(sizing, dict) or not sizing.get("lot_size"):
            return {
                "success": False,
                "strategy": "ORB",
                "symbol": authorization.get("symbol"),
                "risk_approved": True,
                "execution_authorized": False,
                "position_size_required": True,
                "risk_report": risk_result,
                "reason": str(sizing_reason),
            }

        return {
            "success": True,
            "strategy": "ORB",
            "symbol": str(authorization.get("symbol", "")).upper(),
            "risk_approved": True,
            "execution_authorized": False,
            "position_size_required": False,
            "volume_lots": sizing["lot_size"],
            "risk_percent": sizing["risk_percent"],
            "risk_amount": sizing["risk_amount"],
            "value_per_price_unit_per_lot": unit_value,
            "risk_report": risk_result,
            "reason": "ORB_SHARED_RISK_AND_BROKER_BASED_POSITION_SIZING_PASSED",
        }


orb_shared_risk_gate = ORBSharedRiskGate()
