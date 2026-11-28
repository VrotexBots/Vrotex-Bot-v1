"""Vrotex Bot V1 - ORB shared risk gate and broker-based volume sizing.

This module is deliberately a gate only: it does not create signals, alter
ORB rules, submit orders, or depend on SMC/ProTrend/CounterTrend evidence.
The caller must provide a complete, current RiskSnapshot and verified broker
instrument economics/volume constraints. Missing inputs fail closed.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Optional

from risk_management import RiskManager, RiskSnapshot


class ORBRiskIntegrationError(ValueError):
    """Raised when required ORB risk or broker inputs are invalid."""


class ORBSharedRiskGate:
    VERSION = "3.0"
    APPROVED_SYMBOLS = frozenset({"EURUSD", "GBPUSD", "BTCUSD"})

    def __init__(self, risk_manager: Optional[RiskManager] = None):
        self.risk_manager = risk_manager or RiskManager()

    @staticmethod
    def _decimal(value: Any, name: str, *, allow_zero: bool = False) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ORBRiskIntegrationError(f"{name} is missing or invalid.")
        if not result.is_finite() or (result < 0 if allow_zero else result <= 0):
            qualifier = "non-negative" if allow_zero else "greater than zero"
            raise ORBRiskIntegrationError(f"{name} must be finite and {qualifier}.")
        return result

    @staticmethod
    def _snapshot_dict(snapshot: RiskSnapshot) -> dict:
        if not isinstance(snapshot, RiskSnapshot):
            raise ORBRiskIntegrationError("A complete risk_management.RiskSnapshot is required.")
        return asdict(snapshot)

    @staticmethod
    def _floor_to_step(volume: Decimal, step: Decimal) -> Decimal:
        units = (volume / step).to_integral_value(rounding=ROUND_DOWN)
        return units * step

    def evaluate_authorized_candidate(
        self,
        authorization: dict,
        *,
        snapshot: RiskSnapshot,
        loss_per_lot_at_stop: Any,
        broker_volume_min: Any,
        broker_volume_max: Any,
        broker_volume_step: Any,
        spread: Any = None,
        maximum_spread: Any = None,
        spread_valid: Optional[bool] = None,
    ) -> dict:
        """Apply shared daily/account limits and size only from verified inputs.

        `loss_per_lot_at_stop` is the account-currency loss for 1.0 lot at the
        candidate stop, including contract/tick economics and currency conversion.
        It must be obtained from broker data; this module never guesses it.
        """
        if not isinstance(authorization, dict):
            raise ORBRiskIntegrationError("authorization must be a dictionary.")
        symbol = str(authorization.get("symbol", "")).strip().upper()
        if authorization.get("strategy") != "ORB" or authorization.get("strategy_authorized") is not True:
            return self._reject(symbol, "ORB_CENTRAL_STRATEGY_AUTHORIZATION_REQUIRED")
        if symbol not in self.APPROVED_SYMBOLS:
            return self._reject(symbol, "INSTRUMENT_NOT_APPROVED_FOR_V1")

        entry = self._decimal(authorization.get("entry_price"), "entry_price")
        stop = self._decimal(authorization.get("stop_loss"), "stop_loss")
        direction = str(authorization.get("direction", "")).strip().upper()
        if direction == "BULLISH" and stop >= entry:
            return self._reject(symbol, "BULLISH_STOP_MUST_BE_BELOW_ENTRY")
        if direction == "BEARISH" and stop <= entry:
            return self._reject(symbol, "BEARISH_STOP_MUST_BE_ABOVE_ENTRY")
        if direction not in {"BULLISH", "BEARISH"}:
            return self._reject(symbol, "INVALID_ORB_DIRECTION")

        if spread_valid is False:
            return self._reject(symbol, "SPREAD_VALIDATION_FAILED")
        if maximum_spread is not None:
            actual_spread = self._decimal(spread, "spread", allow_zero=True)
            spread_limit = self._decimal(maximum_spread, "maximum_spread")
            if actual_spread > spread_limit:
                return self._reject(symbol, "MAXIMUM_SPREAD_EXCEEDED")
        elif spread_valid is not True:
            return self._reject(symbol, "SPREAD_VALIDATION_NOT_CONFIRMED")

        try:
            snapshot_data = self._snapshot_dict(snapshot)
            allowed, reason = self.risk_manager.can_open_orb_trade(
                snapshot,
                strategy_authorized=True,
                instrument=symbol,
            )
        except Exception as exc:
            return self._reject(symbol, f"RISK_SNAPSHOT_INVALID: {exc}")
        if not allowed:
            return self._reject(symbol, reason, risk_snapshot=snapshot_data)

        loss_per_lot = self._decimal(loss_per_lot_at_stop, "loss_per_lot_at_stop")
        volume_min = self._decimal(broker_volume_min, "broker_volume_min")
        volume_max = self._decimal(broker_volume_max, "broker_volume_max")
        volume_step = self._decimal(broker_volume_step, "broker_volume_step")
        if volume_max < volume_min:
            raise ORBRiskIntegrationError("Broker maximum volume is below minimum volume.")

        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            return self._reject(symbol, "STOP_DISTANCE_INVALID")

        sized = self.risk_manager.calculate_position_size(
            equity=float(snapshot.equity),
            stop_loss_distance=float(stop_distance),
            loss_per_lot_at_stop=float(loss_per_lot),
        )
        raw_volume = Decimal(str(sized.volume_lots))
        volume = self._floor_to_step(min(raw_volume, volume_max), volume_step)
        if volume < volume_min:
            return self._reject(
                symbol,
                "RISK_SIZED_VOLUME_BELOW_BROKER_MINIMUM",
                raw_volume=str(raw_volume),
                broker_volume_min=str(volume_min),
            )
        if volume <= 0 or volume > volume_max:
            return self._reject(symbol, "BROKER_VOLUME_CONSTRAINT_FAILED")

        actual_risk_amount = volume * loss_per_lot
        risk_percent = (actual_risk_amount / Decimal(str(snapshot.equity))) * Decimal("100")
        if risk_percent > Decimal(str(self.risk_manager.risk_percent)):
            return self._reject(symbol, "ROUNDED_VOLUME_EXCEEDS_APPROVED_RISK")

        return {
            "success": True,
            "strategy": "ORB",
            "symbol": symbol,
            "risk_approved": True,
            # Final execution authorization is assigned only by the caller
            # after assembling this result with strategy authorization.
            "execution_authorized": False,
            "position_size_required": False,
            "volume_lots": float(volume),
            "risk_percent": float(risk_percent),
            "risk_amount": float(actual_risk_amount),
            "loss_per_lot_at_stop": float(loss_per_lot),
            "stop_distance": float(stop_distance),
            "broker_volume": {
                "minimum": str(volume_min),
                "maximum": str(volume_max),
                "step": str(volume_step),
            },
            "risk_snapshot": snapshot_data,
            "reason": "ORB_SHARED_RISK_AND_BROKER_VOLUME_CHECKS_PASSED",
        }

    @staticmethod
    def _reject(symbol: str, reason: str, **details: Any) -> dict:
        return {
            "success": False,
            "strategy": "ORB",
            "symbol": symbol,
            "risk_approved": False,
            "execution_authorized": False,
            "position_size_required": True,
            "reason": reason,
            **details,
        }


orb_shared_risk_gate = ORBSharedRiskGate()
