"""Vrotex Bot V1 - ORB Shared Risk Integration (Integration 5).

Connects ORB's independent Central Authorization result to the existing
RiskManager and RiskSnapshot. It does not calculate strategy signals, alter
SMC/ProTrend/CounterTrend authorization, place orders, or invent broker
contract/tick economics.
"""

from __future__ import annotations

from typing import Optional

from risk_management import (
    RiskManager,
    RiskSnapshot,
    RiskManagementError,
    PositionSizeResult,
)


class ORBRiskIntegrationError(ValueError):
    """Raised when ORB risk integration inputs are malformed."""


class ORBSharedRiskGate:
    VERSION = "1.0"

    def __init__(self, risk_manager: Optional[RiskManager] = None):
        self.risk_manager = risk_manager or RiskManager()

    @staticmethod
    def _finite_positive(value, field):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ORBRiskIntegrationError(f"{field} must be a positive finite number.")
        if number <= 0 or number != number or number == float("inf") or number == float("-inf"):
            raise ORBRiskIntegrationError(f"{field} must be a positive finite number.")
        return number

    def evaluate_authorized_candidate(
        self,
        authorization: dict,
        snapshot: RiskSnapshot,
        *,
        loss_per_lot_at_stop: Optional[float] = None,
    ) -> dict:
        """Apply shared risk checks to an ORB candidate already approved centrally.

        If verified broker loss-per-lot data is supplied, position size is
        calculated at the manager's configured risk percentage (capped at 1%).
        Otherwise the candidate remains blocked from execution pending that
        instrument-specific broker data.
        """
        if not isinstance(authorization, dict):
            raise ORBRiskIntegrationError("authorization must be a dictionary.")
        if not isinstance(snapshot, RiskSnapshot):
            raise ORBRiskIntegrationError("snapshot must be a RiskSnapshot.")

        if authorization.get("strategy") != "ORB" or authorization.get("strategy_authorized") is not True:
            return {
                "success": False,
                "strategy": "ORB",
                "risk_approved": False,
                "execution_authorized": False,
                "reason": "ORB_CENTRAL_STRATEGY_AUTHORIZATION_REQUIRED",
            }

        symbol = str(authorization.get("symbol", "")).strip().upper()
        direction = str(authorization.get("direction", "")).strip().upper()
        entry = self._finite_positive(authorization.get("entry_price"), "entry_price")
        stop = self._finite_positive(authorization.get("stop_loss"), "stop_loss")
        if direction not in ("BULLISH", "BEARISH"):
            raise ORBRiskIntegrationError("ORB direction must be BULLISH or BEARISH.")
        if not symbol:
            raise ORBRiskIntegrationError("ORB symbol is required.")

        broker_direction = "buy" if direction == "BULLISH" else "sell"
        self.risk_manager.validate_stop_loss(
            entry_price=entry,
            stop_loss_price=stop,
            direction=broker_direction,
        )

        approved, reason = self.risk_manager.can_open_orb_trade(
            snapshot,
            strategy_authorized=True,
            instrument=symbol,
        )
        if not approved:
            return {
                "success": False,
                "strategy": "ORB",
                "symbol": symbol,
                "risk_approved": False,
                "execution_authorized": False,
                "reason": reason,
            }

        if loss_per_lot_at_stop is None:
            return {
                "success": True,
                "strategy": "ORB",
                "symbol": symbol,
                "risk_approved": True,
                "execution_authorized": False,
                "position_size_required": True,
                "risk_percent": self.risk_manager.risk_percent,
                "reason": "SHARED_RISK_LIMITS_PASSED; VERIFIED_BROKER_LOSS_PER_LOT_REQUIRED_FOR_POSITION_SIZE",
            }

        loss_per_lot = self._finite_positive(loss_per_lot_at_stop, "loss_per_lot_at_stop")
        size: PositionSizeResult = self.risk_manager.calculate_position_size(
            equity=snapshot.equity,
            stop_loss_distance=abs(entry - stop),
            loss_per_lot_at_stop=loss_per_lot,
        )
        return {
            "success": True,
            "strategy": "ORB",
            "symbol": symbol,
            "risk_approved": True,
            "execution_authorized": False,
            "position_size_required": False,
            "risk_percent": size.risk_percent,
            "risk_amount": size.risk_amount,
            "loss_per_lot_at_stop": size.loss_per_lot_at_stop,
            "volume_lots": size.volume_lots,
            "reason": "SHARED_RISK_LIMITS_PASSED; POSITION_SIZE_CALCULATED; BROKER_VOLUME_RULES_AND_EXECUTION_APPROVAL_STILL_REQUIRED",
        }


orb_shared_risk_gate = ORBSharedRiskGate()
