"""Vrotex Bot V1 - exact broker-condition ORB position sizing.

No order submission occurs here. Position size is derived from Exness
instrument conditions and a verified quote-to-account currency conversion.
If any required value is missing, the calculation fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Optional


class ORBPositionSizingError(ValueError):
    """Raised when broker economics or sizing inputs are unsafe."""


@dataclass(frozen=True)
class ORBPositionSize:
    symbol: str
    direction: str
    entry_price: Decimal
    stop_loss: Decimal
    stop_distance: Decimal
    account_currency: str
    quote_currency: str
    quote_to_account_rate: Decimal
    contract_size: Decimal
    loss_per_lot_at_stop: Decimal
    equity: Decimal
    risk_percent: Decimal
    risk_amount: Decimal
    raw_volume_lots: Decimal
    volume_lots: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ORBPositionSizingError(f"{field} is missing or not numeric.")
    if not result.is_finite():
        raise ORBPositionSizingError(f"{field} must be finite.")
    return result


def _positive(value: Any, field: str) -> Decimal:
    result = _decimal(value, field)
    if result <= 0:
        raise ORBPositionSizingError(f"{field} must be greater than zero.")
    return result


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def calculate_orb_position_size(
    *,
    symbol: str,
    direction: str,
    entry_price: Any,
    stop_loss: Any,
    equity: Any,
    account_currency: str,
    instrument_conditions: dict,
    quote_to_account_rate: Optional[Any] = None,
    risk_percent: Any = Decimal("1"),
) -> ORBPositionSize:
    """Calculate lots using exact contract size and currency conversion.

    For a contract quoted in currency Q:
        loss/lot in Q = abs(entry - stop) * contract_size
        loss/lot in account currency = loss/lot in Q * Q-to-account rate

    The conversion rate must be supplied from a verified live broker quote
    whenever quote currency differs from account currency. No rate is guessed.
    """
    if not isinstance(instrument_conditions, dict):
        raise ORBPositionSizingError("Exness instrument conditions are required.")

    normalized_symbol = str(symbol or "").strip().upper()
    normalized_direction = str(direction or "").strip().upper()
    if not normalized_symbol:
        raise ORBPositionSizingError("Instrument symbol is required.")
    if normalized_direction not in {"BUY", "SELL", "BULLISH", "BEARISH"}:
        raise ORBPositionSizingError("Direction must be BUY/SELL or BULLISH/BEARISH.")

    if instrument_conditions.get("trade_mode") is None or str(
        instrument_conditions["trade_mode"]
    ).lower() != "enabled":
        raise ORBPositionSizingError("Exness reports this instrument is not enabled.")

    condition_symbol = str(
        instrument_conditions.get("instrument", normalized_symbol)
    ).strip().upper()
    if condition_symbol != normalized_symbol:
        raise ORBPositionSizingError("Instrument conditions belong to a different symbol.")

    required_fields = (
        "contract_size", "volume_min", "volume_max", "volume_step", "quote_currency"
    )
    missing = [
        field for field in required_fields
        if instrument_conditions.get(field) is None
        or instrument_conditions.get(field) == ""
    ]
    if missing:
        raise ORBPositionSizingError(
            "Exness instrument conditions missing: " + ", ".join(missing)
        )

    entry = _positive(entry_price, "entry_price")
    stop = _positive(stop_loss, "stop_loss")
    account_equity = _positive(equity, "equity")
    contract_size = _positive(instrument_conditions["contract_size"], "contract_size")
    volume_min = _positive(instrument_conditions["volume_min"], "volume_min")
    volume_max = _positive(instrument_conditions["volume_max"], "volume_max")
    volume_step = _positive(instrument_conditions["volume_step"], "volume_step")
    risk = _positive(risk_percent, "risk_percent")

    if volume_max < volume_min:
        raise ORBPositionSizingError("Broker volume_max is below volume_min.")
    if risk > Decimal("1"):
        raise ORBPositionSizingError("Risk per trade cannot exceed the approved 1%.")

    if normalized_direction in {"BUY", "BULLISH"} and stop >= entry:
        raise ORBPositionSizingError("A BUY stop-loss must be below entry.")
    if normalized_direction in {"SELL", "BEARISH"} and stop <= entry:
        raise ORBPositionSizingError("A SELL stop-loss must be above entry.")

    quote_currency = str(instrument_conditions["quote_currency"]).strip().upper()
    account_ccy = str(account_currency or "").strip().upper()
    if len(quote_currency) != 3 or len(account_ccy) != 3:
        raise ORBPositionSizingError("Valid three-letter quote and account currencies are required.")

    if quote_currency == account_ccy:
        conversion = Decimal("1")
        if quote_to_account_rate is not None:
            supplied_rate = _positive(quote_to_account_rate, "quote_to_account_rate")
            if supplied_rate != Decimal("1"):
                raise ORBPositionSizingError(
                    "Conversion rate must be 1 when quote and account currencies match."
                )
    else:
        if quote_to_account_rate is None:
            raise ORBPositionSizingError(
                f"Verified {quote_currency}-to-{account_ccy} conversion rate is required."
            )
        conversion = _positive(quote_to_account_rate, "quote_to_account_rate")

    distance = abs(entry - stop)
    loss_per_lot = distance * contract_size * conversion
    risk_amount = account_equity * risk / Decimal("100")
    raw_volume = risk_amount / loss_per_lot

    # Round DOWN to broker step. Never round up and breach the risk budget.
    volume = _floor_to_step(raw_volume, volume_step)
    if volume > volume_max:
        volume = _floor_to_step(volume_max, volume_step)
    if volume < volume_min:
        raise ORBPositionSizingError(
            "The risk budget produces a volume below the broker minimum; "
            "trade rejected rather than increasing risk to meet minimum volume."
        )
    if volume <= 0:
        raise ORBPositionSizingError("Calculated volume is not tradable.")

    actual_risk = volume * loss_per_lot
    if actual_risk > risk_amount:
        raise ORBPositionSizingError("Rounded volume exceeds the approved risk budget.")

    return ORBPositionSize(
        symbol=normalized_symbol,
        direction=normalized_direction,
        entry_price=entry,
        stop_loss=stop,
        stop_distance=distance,
        account_currency=account_ccy,
        quote_currency=quote_currency,
        quote_to_account_rate=conversion,
        contract_size=contract_size,
        loss_per_lot_at_stop=loss_per_lot,
        equity=account_equity,
        risk_percent=risk,
        risk_amount=risk_amount,
        raw_volume_lots=raw_volume,
        volume_lots=volume,
        volume_min=volume_min,
        volume_max=volume_max,
        volume_step=volume_step,
    )


class ORBPositionSizer:
    """Small state-free wrapper for scanner/executor integration."""

    def calculate(self, **kwargs) -> ORBPositionSize:
        return calculate_orb_position_size(**kwargs)


orb_position_sizer = ORBPositionSizer()
