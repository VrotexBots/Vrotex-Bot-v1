"""Vrotex Bot V1 - ORB shared risk gate and broker-based volume sizing.

This module is deliberately a gate only: it does not create signals, alter
ORB rules, submit orders, or depend on SMC/ProTrend/CounterTrend evidence.
The caller must provide a complete, current RiskSnapshot and verified broker
instrument economics/volume constraints. Missing inputs fail closed.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from risk_manager import RiskManager, RiskSnapshot
from orb_position_sizer import (
    ORBPositionSizingError, calculate_orb_position_size,
)


class ORBRiskIntegrationError(ValueError):
    """Raised when required ORB risk or broker inputs are invalid."""


class ORBSharedRiskGate:
    VERSION = "3.1"
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

    def evaluate_authorized_candidate(
        self,
        authorization: dict,
        *,
        snapshot: RiskSnapshot,
        instrument_conditions: dict,
        account_currency: str,
        quote_to_account_rate: Any = None,
        spread: Any = None,
        maximum_spread: Any = None,
        spread_valid: Optional[bool] = None,
    ) -> dict:
        """Apply shared daily/account limits and size only from verified inputs.

        Position size is calculated by orb_position_sizer from exact Exness
        instrument conditions and a verified quote-to-account conversion rate.
        The module does not accept caller-supplied loss-per-lot or volume limits.
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
            allowed, reason = self._check_orb_shared_limits(snapshot, symbol)
        except Exception as exc:
            return self._reject(symbol, f"RISK_SNAPSHOT_INVALID: {exc}")
        if not allowed:
            return self._reject(symbol, reason, risk_snapshot=snapshot_data)

        try:
            sized = calculate_orb_position_size(
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                stop_loss=stop,
                equity=snapshot.equity,
                account_currency=account_currency,
                instrument_conditions=instrument_conditions,
                quote_to_account_rate=quote_to_account_rate,
                risk_percent=self.risk_manager.risk_percent,
            )
        except ORBPositionSizingError as exc:
            return self._reject(symbol, f"POSITION_SIZING_REJECTED: {exc}")

        volume = sized.volume_lots
        actual_risk_amount = sized.volume_lots * sized.loss_per_lot_at_stop
        risk_percent = (actual_risk_amount / sized.equity) * Decimal("100")
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
            "loss_per_lot_at_stop": float(sized.loss_per_lot_at_stop),
            "stop_distance": float(sized.stop_distance),
            "position_sizing": {
                "account_currency": sized.account_currency,
                "quote_currency": sized.quote_currency,
                "quote_to_account_rate": str(sized.quote_to_account_rate),
                "contract_size": str(sized.contract_size),
                "raw_volume_lots": str(sized.raw_volume_lots),
                "volume_min": str(sized.volume_min),
                "volume_max": str(sized.volume_max),
                "volume_step": str(sized.volume_step),
            },
            "risk_snapshot": snapshot_data,
            "reason": "ORB_SHARED_RISK_AND_BROKER_VOLUME_CHECKS_PASSED",
        }

    def _check_orb_shared_limits(self, snapshot: RiskSnapshot, symbol: str) -> tuple[bool, str]:
        """Apply shared daily limits without imposing SMC's A+ requirement on ORB."""
        self.risk_manager._validate_snapshot(snapshot)
        if snapshot.daily_loss_percent >= self.risk_manager.max_daily_loss_percent:
            return False, "BLOCKED: maximum daily loss limit reached."
        if snapshot.consecutive_losses_today >= self.risk_manager.max_daily_losses:
            return False, "BLOCKED: two consecutive losses reached; learning-only until next trading day."
        if snapshot.trades_taken_today >= self.risk_manager.max_trades_per_day:
            return False, "BLOCKED: maximum daily trade count reached."
        if (self.risk_manager.max_open_trades is not None
                and snapshot.open_trade_count >= self.risk_manager.max_open_trades):
            return False, "BLOCKED: configured simultaneous open-trade limit reached."
        reserved = {item.strip().upper() for item in
                    (*snapshot.active_instruments, *snapshot.pending_instruments)}
        if symbol in reserved:
            return False, f"BLOCKED: {symbol} already has an open position or pending entry order."
        return True, "APPROVED: ORB shared risk limits passed."

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
