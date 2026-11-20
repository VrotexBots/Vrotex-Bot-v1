from config import settings
from logging_config import get_logger

logger = get_logger("risk_manager")


class RiskManager:

    def __init__(self):

        self.max_risk_percent = settings.RISK_PERCENT
        self.max_daily_trades = settings.MAX_DAILY_TRADES
        self.max_consecutive_losses = (
            settings.MAX_CONSECUTIVE_LOSSES
        )
        self.max_daily_loss_percent = (
            settings.MAX_DAILY_LOSS_PERCENT
        )

        self.daily_trades = 0
        self.consecutive_losses = 0
        self.daily_pnl_percent = 0.0

        self.active_trades = 0
        self.locked = False
        self.lock_reason = None

    def can_trade(self):

        if self.locked:
            return False, self.lock_reason

        if self.daily_trades >= self.max_daily_trades:
            return False, "Maximum daily trades reached"

        if self.consecutive_losses >= self.max_consecutive_losses:
            return False, "Consecutive loss limit reached"

        if self.daily_pnl_percent <= -self.max_daily_loss_percent:
            return False, "Daily loss limit reached"

        if self.max_risk_percent > 1.0:
            return False, "Risk exceeds maximum allowed risk"

        return True, "Risk checks passed"

    def validate_trade_risk(self, risk_percent):

        try:
            risk = float(risk_percent)
        except (TypeError, ValueError):
            return False, "Invalid risk value"

        if risk <= 0:
            return False, "Risk must be positive"

        if risk > self.max_risk_percent:
            return False, "Trade risk exceeds configured limit"

        if risk > 1.0:
            return False, "Trade risk exceeds 1% safety cap"

        return True, "Risk approved"

    def register_trade(self):

        allowed, reason = self.can_trade()

        if not allowed:
            logger.warning("Trade blocked: %s", reason)
            return False

        self.daily_trades += 1

        logger.info(
            "Trade registered. Daily trades: %s",
            self.daily_trades
        )

        return True

    def register_win(self, pnl_percent=0.0):

        self.consecutive_losses = 0
        self.daily_pnl_percent += float(pnl_percent)

        logger.info("Winning trade recorded.")

    def register_loss(self, pnl_percent=0.0):

        self.consecutive_losses += 1
        self.daily_pnl_percent -= abs(float(pnl_percent))

        logger.warning(
            "Loss recorded. Consecutive losses: %s",
            self.consecutive_losses
        )

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.lock_trading(
                "Maximum consecutive losses reached"
            )

        if self.daily_pnl_percent <= -self.max_daily_loss_percent:
            self.lock_trading(
                "Maximum daily loss reached"
            )

    def lock_trading(self, reason):

        self.locked = True
        self.lock_reason = reason

        logger.error("TRADING LOCKED: %s", reason)

    def unlock_trading(self):

        self.locked = False
        self.lock_reason = None

        logger.warning("Trading lock manually cleared.")

    def reset_daily(self):

        self.daily_trades = 0
        self.consecutive_losses = 0
        self.daily_pnl_percent = 0.0
        self.locked = False
        self.lock_reason = None

        logger.info("Daily risk counters reset.")

    def get_status(self):

        return {
            "daily_trades": self.daily_trades,
            "max_daily_trades": self.max_daily_trades,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "daily_pnl_percent": self.daily_pnl_percent,
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "risk_per_trade_percent": self.max_risk_percent,
            "locked": self.locked,
            "lock_reason": self.lock_reason,
        }


risk_manager = RiskManager()
