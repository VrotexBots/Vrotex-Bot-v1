
"""
Vrotex Bot V1 - Risk Manager
Complete risk validation module.

Responsibilities:
    - Per-trade risk validation
    - Stop-loss validation
    - Take-profit validation
    - Reward-to-risk validation
    - Spread validation
    - Daily trade limits
    - Consecutive loss limits
    - Daily loss limits
    - Open-position tracking
    - Risk evidence for Master SMC Engine

The Master SMC Engine remains the sole scoring authority.
"""

from math import isfinite
from threading import RLock

from config import settings
from logging_config import get_logger


logger = get_logger("risk_manager")


class RiskManager:

    VERSION = "2.2"

    REQUIRED_RISK_CHECKS = (
        "spread_valid",
        "stop_loss_valid",
        "risk_within_limit",
        "daily_limit_valid",
        "consecutive_loss_limit_valid",
        "reward_risk_valid",
    )

    def __init__(self):

        self._lock = RLock()

        self.max_risk_percent = self._setting(
            "RISK_PERCENT",
            1.0,
        )

        self.max_daily_trades = int(
            self._setting("MAX_DAILY_TRADES", 5)
        )

        self.max_consecutive_losses = int(
            self._setting("MAX_CONSECUTIVE_LOSSES", 2)
        )

        self.max_daily_loss_percent = self._setting(
            "MAX_DAILY_LOSS_PERCENT",
            2.0,
        )

        # Vrotex V1 permits simultaneous positions on different instruments.
        # The per-instrument guard below prevents duplicates; a global open-
        # trade or aggregate-risk cap must not silently override that rule.
        self.max_open_trades = None
        self.max_total_open_risk_percent = None

        self.max_spread = self._first_setting(
            (
                "MAX_SPREAD",
                "MAX_SPREAD_PIPS",
                "SPREAD_LIMIT",
                "MAX_ALLOWED_SPREAD",
            )
        )

        self.minimum_reward_risk = self._first_setting(
            (
                "MIN_REWARD_RISK_RATIO",
                "MIN_RISK_REWARD_RATIO",
                "MINIMUM_REWARD_RISK",
            )
        )

        self.daily_trades = 0
        self.consecutive_losses = 0
        self.daily_pnl_percent = 0.0

        self.active_trades = 0
        self.open_trade_risks = {}
        self.pending_instruments = set()

        self.locked = False
        self.lock_reason = None

        logger.info(
            "Risk Manager V%s initialized | "
            "Risk=%.2f%% | Daily trades=%s | "
            "Consecutive losses=%s | Daily loss=%.2f%%",
            self.VERSION,
            self.max_risk_percent,
            self.max_daily_trades,
            self.max_consecutive_losses,
            self.max_daily_loss_percent,
        )

    # =====================================================
    # CONFIGURATION
    # =====================================================

    @staticmethod
    def _setting(name, default):

        value = getattr(settings, name, default)

        try:
            value = float(value)

            if not isfinite(value):
                return float(default)

            return value

        except (TypeError, ValueError, OverflowError):
            return float(default)

    @staticmethod
    def _optional_setting(name):

        value = getattr(settings, name, None)

        if value is None:
            return None

        try:
            value = float(value)

            if not isfinite(value):
                return None

            return value

        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _first_setting(cls, names):

        for name in names:

            value = cls._optional_setting(name)

            if value is not None:
                return value

        return None

    @staticmethod
    def _number(value):

        try:

            if isinstance(value, bool):
                return None

            number = float(value)

            if not isfinite(number):
                return None

            return number

        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _direction(value):

        value = str(value or "").strip().upper()

        aliases = {
            "BUY": "BUY",
            "BULL": "BUY",
            "BULLISH": "BUY",
            "LONG": "BUY",
            "SELL": "SELL",
            "BEAR": "SELL",
            "BEARISH": "SELL",
            "SHORT": "SELL",
        }

        return aliases.get(value)

    # =====================================================
    # GLOBAL TRADING LIMITS
    # =====================================================

    def can_trade(self, symbol=None):

        with self._lock:

            if self.locked:
                return False, self.lock_reason

            if self.daily_trades >= self.max_daily_trades:
                return False, "Maximum daily trades reached"

            if (
                self.consecutive_losses
                >= self.max_consecutive_losses
            ):
                return False, "Consecutive loss limit reached"

            if (
                self.daily_pnl_percent
                <= -self.max_daily_loss_percent
            ):
                return False, "Daily loss limit reached"

            if self.max_risk_percent <= 0:
                return False, "Configured trade risk is invalid"

            if self.max_risk_percent > 1.0:
                return False, "Risk exceeds 1% safety cap"

            if symbol is not None:
                key = str(symbol).strip().upper()
                if not key:
                    return False, "Invalid instrument symbol"
                if key in self.open_trade_risks:
                    return False, "An active trade already exists for this instrument"
                if key in self.pending_instruments:
                    return False, "A pending trade already exists for this instrument"

            return True, "Risk checks passed"

    # =====================================================
    # PER-TRADE RISK
    # =====================================================

    def validate_trade_risk(self, risk_percent):

        risk = self._number(risk_percent)

        if risk is None:
            return False, "Invalid or missing trade risk"

        if risk <= 0:
            return False, "Trade risk must be positive"

        if risk > self.max_risk_percent:
            return False, "Trade risk exceeds configured limit"

        if risk > 1.0:
            return False, "Trade risk exceeds 1% safety cap"

        return True, "Trade risk approved"

    # =====================================================
    # STOP-LOSS VALIDATION
    # =====================================================

    def validate_stop_loss(
        self,
        direction,
        entry_price,
        stop_loss,
    ):

        direction = self._direction(direction)
        entry = self._number(entry_price)
        stop = self._number(stop_loss)

        if direction not in ("BUY", "SELL"):
            return False, "Invalid trade direction"

        if entry is None or stop is None:
            return False, "Entry price or stop loss missing"

        if entry <= 0 or stop <= 0:
            return False, "Entry and stop loss must be positive"

        if direction == "BUY" and stop >= entry:
            return False, "BUY stop loss must be below entry"

        if direction == "SELL" and stop <= entry:
            return False, "SELL stop loss must be above entry"

        if entry == stop:
            return False, "Stop loss cannot equal entry"

        return True, "Stop loss valid"

    # =====================================================
    # TAKE-PROFIT AND REWARD-TO-RISK
    # =====================================================

    def validate_target(
        self,
        direction,
        entry_price,
        stop_loss,
        take_profit,
    ):

        direction = self._direction(direction)

        entry = self._number(entry_price)
        stop = self._number(stop_loss)
        target = self._number(take_profit)

        if direction not in ("BUY", "SELL"):
            return False, "Invalid trade direction"

        if entry is None or stop is None or target is None:
            return False, "Entry, stop loss or target missing"

        if entry <= 0 or stop <= 0 or target <= 0:
            return False, "Trade prices must be positive"

        if direction == "BUY":

            if stop >= entry:
                return False, "BUY stop loss must be below entry"

            if target <= entry:
                return False, "BUY target must be above entry"

        else:

            if stop <= entry:
                return False, "SELL stop loss must be above entry"

            if target >= entry:
                return False, "SELL target must be below entry"

        return True, "Target and stop-loss direction valid"

    def calculate_reward_risk(
        self,
        entry_price,
        stop_loss,
        take_profit,
    ):

        entry = self._number(entry_price)
        stop = self._number(stop_loss)
        target = self._number(take_profit)

        if entry is None or stop is None or target is None:
            return None

        risk_distance = abs(entry - stop)
        reward_distance = abs(target - entry)

        if risk_distance <= 0:
            return None

        return round(
            reward_distance / risk_distance,
            4,
        )

    def validate_reward_risk(
        self,
        entry_price,
        stop_loss,
        take_profit,
        minimum_ratio=None,
    ):

        ratio = self.calculate_reward_risk(
            entry_price,
            stop_loss,
            take_profit,
        )

        if ratio is None:
            return False, "Reward-to-risk cannot be calculated"

        required = (
            self.minimum_reward_risk
            if minimum_ratio is None
            else self._number(minimum_ratio)
        )

        # If no minimum ratio is configured, validate that
        # the target produces positive reward against risk.
        if required is None:
            required = 0.0

        if ratio <= 0:
            return False, "Reward-to-risk must be positive"

        if ratio < required:
            return False, (
                f"Reward-to-risk {ratio} below required "
                f"minimum {required}"
            )

        return True, f"Reward-to-risk valid: {ratio}"

    # =====================================================
    # SPREAD VALIDATION
    # =====================================================

    def validate_spread(
        self,
        spread=None,
        maximum_spread=None,
        prevalidated=None,
    ):

        if prevalidated is True:
            return True, "Spread validated upstream"

        if prevalidated is False:
            return False, "Spread rejected upstream"

        actual = self._number(spread)

        maximum = (
            self._number(maximum_spread)
            if maximum_spread is not None
            else self.max_spread
        )

        if actual is None:
            return False, "Actual spread unavailable"

        if actual < 0:
            return False, "Invalid negative spread"

        if maximum is None:
            return False, "Maximum spread limit not configured"

        if maximum < 0:
            return False, "Configured spread limit is invalid"

        if actual > maximum:
            return False, (
                f"Spread {actual} exceeds maximum {maximum}"
            )

        return True, "Spread valid"

    # =====================================================
    # POSITION SIZE CALCULATION
    # =====================================================

    def calculate_position_size(
        self,
        account_balance,
        entry_price,
        stop_loss,
        risk_percent=None,
        value_per_price_unit_per_lot=None,
    ):
        """
        Calculates lot size only when the broker-specific
        value per price unit per lot is supplied.

        This avoids assuming contract sizes or pip values
        that may differ between instruments and account types.
        """

        balance = self._number(account_balance)
        entry = self._number(entry_price)
        stop = self._number(stop_loss)

        risk = (
            self.max_risk_percent
            if risk_percent is None
            else self._number(risk_percent)
        )

        unit_value = self._number(
            value_per_price_unit_per_lot
        )

        if balance is None or balance <= 0:
            return None, "Invalid account balance"

        if entry is None or stop is None:
            return None, "Entry or stop loss missing"

        if entry <= 0 or stop <= 0:
            return None, "Invalid entry or stop-loss price"

        if unit_value is None or unit_value <= 0:
            return None, "Broker contract value unavailable"

        approved, reason = self.validate_trade_risk(risk)

        if not approved:
            return None, reason

        stop_distance = abs(entry - stop)

        if stop_distance <= 0:
            return None, "Invalid stop-loss distance"

        risk_amount = balance * risk / 100.0

        lot_size = (
            risk_amount
            / (stop_distance * unit_value)
        )

        if not isfinite(lot_size) or lot_size <= 0:
            return None, "Position size calculation failed"

        return {
            "lot_size": lot_size,
            "risk_percent": risk,
            "risk_amount": round(risk_amount, 2),
            "stop_distance": stop_distance,
            "entry_price": entry,
            "stop_loss": stop,
        }, "Position size calculated"

    # =====================================================
    # TRADE CANDIDATE EXTRACTION
    # =====================================================

    def _extract_candidate(
        self,
        market_data,
        candidate=None,
    ):

        if isinstance(candidate, dict):
            return candidate

        if not isinstance(market_data, dict):
            return {}

        for key in (
            "trade_candidate",
            "planned_trade",
            "execution_payload",
            "best_setup",
            "setup",
        ):

            value = market_data.get(key)

            if isinstance(value, dict):
                return value

        # Check technical analysis results for a supplied
        # trade plan. Do not invent missing entry/SL/TP values.
        for timeframe in ("M1", "M5", "H1"):

            tf_data = market_data.get(timeframe)

            if not isinstance(tf_data, dict):
                continue

            technical = tf_data.get("technical")

            if not isinstance(technical, dict):
                continue

            for key in (
                "trade_candidate",
                "planned_trade",
                "execution_payload",
                "best_setup",
            ):

                value = technical.get(key)

                if isinstance(value, dict):
                    return value

        return {}

    # =====================================================
    # COMPLETE TRADE VALIDATION
    # =====================================================

    def validate_trade(
        self,
        symbol,
        direction,
        entry_price,
        stop_loss,
        take_profit,
        risk_percent,
        spread=None,
        maximum_spread=None,
        spread_valid=None,
    ):

        allowed, reason = self.can_trade(symbol=symbol)

        stop_valid, stop_reason = self.validate_stop_loss(
            direction,
            entry_price,
            stop_loss,
        )

        target_valid, target_reason = self.validate_target(
            direction,
            entry_price,
            stop_loss,
            take_profit,
        )

        risk_valid, risk_reason = self.validate_trade_risk(
            risk_percent
        )

        spread_ok, spread_reason = self.validate_spread(
            spread,
            maximum_spread,
            spread_valid,
        )

        reward_valid, reward_reason = self.validate_reward_risk(
            entry_price,
            stop_loss,
            take_profit,
        )

        checks = {
            "spread_valid": spread_ok,
            "stop_loss_valid": stop_valid,
            "risk_within_limit": risk_valid,
            "daily_limit_valid": allowed,
            "consecutive_loss_limit_valid": (
                self.consecutive_losses
                < self.max_consecutive_losses
                and not self.locked
            ),
            "reward_risk_valid": (
                target_valid and reward_valid
            ),
        }

        reasons = {
            "trading_limits": reason,
            "spread": spread_reason,
            "stop_loss": stop_reason,
            "risk": risk_reason,
            "target": target_reason,
            "reward_risk": reward_reason,
        }

        approved = all(
            checks[name] is True
            for name in self.REQUIRED_RISK_CHECKS
        )

        return {
            "symbol": symbol,
            "approved": approved,
            "checks": checks,
            "reasons": reasons,
            "reward_risk_ratio": self.calculate_reward_risk(
                entry_price,
                stop_loss,
                take_profit,
            ),
            "risk_percent": self._number(risk_percent),
            "entry_price": self._number(entry_price),
            "stop_loss": self._number(stop_loss),
            "take_profit": self._number(take_profit),
        }

    # =====================================================
    # ORB SHARED RISK INTERFACE
    # =====================================================

    def check_orb_trade(self, authorization, *, spread=None,
                        maximum_spread=None, spread_valid=None):
        """Validate an independently authorized ORB candidate.

        ORB does not use Master SMC A+ scoring. It must first carry its own
        Central Authorization approval; after that, this method applies the
        same account-wide risk limits and per-trade checks used by Vrotex.
        This method does not register or execute a trade.
        """
        if not isinstance(authorization, dict):
            return {
                "status": "RISK_REJECTED",
                "available": True,
                "strategy": "ORB",
                "approved": False,
                "reason": "Invalid ORB authorization payload",
            }

        if (str(authorization.get("strategy", "")).strip().upper() != "ORB"
                or authorization.get("strategy_authorized") is not True):
            return {
                "status": "RISK_REJECTED",
                "available": True,
                "strategy": "ORB",
                "symbol": authorization.get("symbol"),
                "approved": False,
                "reason": "ORB central strategy authorization is required",
            }

        direction = self._direction(authorization.get("direction"))
        entry = authorization.get("entry_price")
        stop = authorization.get("stop_loss")
        target = authorization.get("take_profit")
        risk_percent = authorization.get(
            "risk_percent", self.max_risk_percent
        )

        result = self.validate_trade(
            symbol=authorization.get("symbol"),
            direction=direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            risk_percent=risk_percent,
            spread=(authorization.get("spread")
                    if spread is None else spread),
            maximum_spread=maximum_spread,
            spread_valid=(authorization.get("spread_valid")
                          if spread_valid is None else spread_valid),
        )

        approved = result.get("approved") is True
        response = {
            "status": "RISK_APPROVED" if approved else "RISK_REJECTED",
            "available": True,
            "strategy": "ORB",
            **result,
            "execution_authorized": False,
            "trade_registration_required": True,
        }
        logger.info(
            "ORB shared risk validation | %s | Approved=%s | Checks=%s",
            authorization.get("symbol"), approved, result.get("checks"),
        )
        return response

    # =====================================================
    # SCANNER / SMC INTERFACE
    # =====================================================

    def check_trade(
        self,
        symbol=None,
        market_data=None,
        current_price=None,
        candidate=None,
        **kwargs,
    ):
        """
        Compatible with the Market Scanner's check_trade call.

        Returns the six risk flags required by Master SMC.

        A real trade candidate must provide its actual
        direction, entry, stop loss, target and risk percent.
        """

        candidate = self._extract_candidate(
            market_data,
            candidate,
        )

        direction = (
            candidate.get("direction")
            or candidate.get("trade_direction")
        )

        entry = self._number(
            candidate.get(
                "entry_price",
                candidate.get(
                    "entry",
                    current_price,
                ),
            )
        )

        stop = candidate.get(
            "stop_loss",
            candidate.get("sl"),
        )

        target = candidate.get(
            "take_profit",
            candidate.get(
                "target",
                candidate.get("tp"),
            ),
        )

        risk_percent = candidate.get(
            "risk_percent",
            candidate.get("risk_per_trade_percent"),
        )

        spread = candidate.get(
            "spread",
            kwargs.get("spread"),
        )

        spread_valid = candidate.get(
            "spread_valid",
            kwargs.get("spread_valid"),
        )

        result = self.validate_trade(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            risk_percent=risk_percent,
            spread=spread,
            maximum_spread=kwargs.get("maximum_spread"),
            spread_valid=spread_valid,
        )

        logger.info(
            "Risk validation | %s | Approved=%s | Checks=%s",
            symbol,
            result["approved"],
            result["checks"],
        )

        return {
            "status": (
                "RISK_APPROVED"
                if result["approved"]
                else "RISK_REJECTED"
            ),
            "available": True,
            "symbol": symbol,
            **result,
        }

    # Scanner compatibility aliases.
    validate_risk = check_trade
    check_risk = check_trade
    analyze_risk = check_trade
    analyse_risk = check_trade
    get_risk_checks = check_trade

    # =====================================================
    # TRADE REGISTRATION
    # =====================================================

    def register_trade(
        self,
        symbol=None,
        risk_percent=None,
    ):

        key = str(symbol).strip().upper() if symbol is not None else None
        if symbol is not None and not key:
            return False

        with self._lock:
            # A pending reservation for this same instrument is promoted
            # atomically when its order becomes an active position.
            had_pending_reservation = key is not None and key in self.pending_instruments
            if had_pending_reservation:
                self.pending_instruments.discard(key)

            allowed, reason = self.can_trade(symbol=key)
            if not allowed:
                if had_pending_reservation:
                    self.pending_instruments.add(key)
                logger.warning("Trade registration blocked: %s", reason)
                return False

            if risk_percent is not None:
                valid, risk_reason = self.validate_trade_risk(risk_percent)
                if not valid:
                    if had_pending_reservation:
                        self.pending_instruments.add(key)
                    logger.warning("Trade registration blocked: %s", risk_reason)
                    return False

            if self.daily_trades >= self.max_daily_trades:
                if had_pending_reservation:
                    self.pending_instruments.add(key)
                logger.warning("Trade registration blocked: daily trade limit reached")
                return False

            self.daily_trades += 1
            self.active_trades += 1
            if key is not None:
                self.open_trade_risks[key] = (
                    self._number(risk_percent) if risk_percent is not None else None
                )
                self.pending_instruments.discard(key)

        logger.info(
            "Trade registered | Symbol=%s | Daily trades=%s | Active trades=%s",
            key, self.daily_trades, self.active_trades,
        )
        return True

    def reserve_pending_trade(self, symbol):
        """Reserve an instrument while an order is pending; one per symbol."""
        key = str(symbol or "").strip().upper()
        if not key:
            return False, "Invalid instrument symbol"
        with self._lock:
            allowed, reason = self.can_trade(symbol=key)
            if not allowed:
                return False, reason
            self.pending_instruments.add(key)
            return True, "Pending instrument reserved"

    def release_pending_trade(self, symbol):
        """Release a pending reservation after rejection or cancellation."""
        key = str(symbol or "").strip().upper()
        if not key:
            return False
        with self._lock:
            existed = key in self.pending_instruments
            self.pending_instruments.discard(key)
            return existed

    def register_trade_closed(self, symbol=None):
        with self._lock:
            if symbol is None:
                if self.active_trades > 0:
                    self.active_trades -= 1
                return True

            key = str(symbol).strip().upper()
            if key not in self.open_trade_risks:
                logger.warning("Ignored close for unregistered instrument: %s", key)
                return False

            self.open_trade_risks.pop(key, None)
            if self.active_trades > 0:
                self.active_trades -= 1

        logger.info(
            "Trade closed | Symbol=%s | Active trades=%s",
            key, self.active_trades,
        )
        return True

    def get_total_open_risk(self):

        with self._lock:

            return round(
                sum(
                    value
                    for value in self.open_trade_risks.values()
                    if value is not None
                ),
                4,
            )

    # =====================================================
    # WIN / LOSS RECORDING
    # =====================================================

    def register_win(self, pnl_percent=0.0):

        pnl = self._number(pnl_percent)

        if pnl is None or pnl < 0:
            logger.error("Invalid winning trade PnL")
            return False

        with self._lock:

            self.consecutive_losses = 0
            self.daily_pnl_percent += pnl

        logger.info(
            "Winning trade recorded | PnL=%.4f%%",
            pnl,
        )

        return True

    def register_loss(self, pnl_percent=0.0):

        pnl = self._number(pnl_percent)

        if pnl is None or pnl < 0:
            logger.error("Invalid losing trade PnL")
            return False

        with self._lock:

            self.consecutive_losses += 1
            self.daily_pnl_percent -= pnl

            consecutive_limit_reached = (
                self.consecutive_losses
                >= self.max_consecutive_losses
            )

            daily_limit_reached = (
                self.daily_pnl_percent
                <= -self.max_daily_loss_percent
            )

        logger.warning(
            "Loss recorded | Losses=%s | Daily PnL=%.4f%%",
            self.consecutive_losses,
            self.daily_pnl_percent,
        )

        if consecutive_limit_reached:
            self.lock_trading(
                "Maximum consecutive losses reached"
            )

        if daily_limit_reached:
            self.lock_trading(
                "Maximum daily loss reached"
            )

        return True

    # =====================================================
    # LOCK MANAGEMENT
    # =====================================================

    def lock_trading(self, reason):

        with self._lock:

            self.locked = True
            self.lock_reason = str(reason)

        logger.error(
            "TRADING LOCKED: %s",
            reason,
        )

    def unlock_trading(self):

        with self._lock:

            # Never unlock while a daily safety limit
            # remains breached.
            if (
                self.consecutive_losses
                >= self.max_consecutive_losses
            ):
                logger.warning(
                    "Unlock refused: consecutive loss limit breached"
                )
                return False

            if (
                self.daily_pnl_percent
                <= -self.max_daily_loss_percent
            ):
                logger.warning(
                    "Unlock refused: daily loss limit breached"
                )
                return False

            if self.daily_trades >= self.max_daily_trades:
                logger.warning(
                    "Unlock refused: daily trade limit reached"
                )
                return False

            self.locked = False
            self.lock_reason = None

        logger.warning("Trading lock manually cleared.")

        return True

    # =====================================================
    # DAILY RESET
    # =====================================================

    def reset_daily(self):

        with self._lock:

            # Do not reset active positions or their exposure.
            self.daily_trades = 0
            self.consecutive_losses = 0
            self.daily_pnl_percent = 0.0
            self.locked = False
            self.lock_reason = None

        logger.info("Daily risk counters reset.")

    # =====================================================
    # STATUS
    # =====================================================

    def get_status(self):

        with self._lock:

            return {
                "module": "RISK_MANAGER",
                "version": self.VERSION,

                "risk_per_trade_percent": (
                    self.max_risk_percent
                ),

                "maximum_risk_cap_percent": 1.0,

                "daily_trades": self.daily_trades,
                "max_daily_trades": self.max_daily_trades,

                "consecutive_losses": (
                    self.consecutive_losses
                ),
                "max_consecutive_losses": (
                    self.max_consecutive_losses
                ),

                "daily_pnl_percent": (
                    self.daily_pnl_percent
                ),
                "max_daily_loss_percent": (
                    self.max_daily_loss_percent
                ),

                "active_trades": self.active_trades,
                "max_open_trades": self.max_open_trades,
                "open_trade_risks": dict(
                    self.open_trade_risks
                ),
                "pending_instruments": sorted(self.pending_instruments),
                "total_open_risk_percent": (
                    self.get_total_open_risk()
                ),

                "maximum_spread": self.max_spread,
                "minimum_reward_risk": (
                    self.minimum_reward_risk
                ),

                "required_checks": list(
                    self.REQUIRED_RISK_CHECKS
                ),

                "locked": self.locked,
                "lock_reason": self.lock_reason,
            }


# =========================================================
# SINGLETON
# =========================================================

risk_manager = RiskManager()
