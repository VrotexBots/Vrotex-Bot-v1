import uuid
from datetime import datetime, timezone

from logging_config import get_logger
from storage import storage
from risk_manager import risk_manager
from state_manager import state_manager

logger = get_logger("trade_manager")


class TradeManager:

    def __init__(self):

        self.active_trades = {}

    @staticmethod
    def utc_now():

        return datetime.now(timezone.utc).isoformat()

    def register_trade(self, trade):

        if not isinstance(trade, dict):
            return False, "Invalid trade data"

        symbol = trade.get("symbol")
        direction = trade.get("direction")

        if not symbol or direction not in ("BUY", "SELL"):
            return False, "Invalid symbol or direction"

        if not risk_manager.register_trade():
            return False, "Risk manager blocked trade"

        trade_id = trade.get("trade_id") or str(uuid.uuid4())

        record = dict(trade)

        record["trade_id"] = trade_id
        record["status"] = "OPEN"
        record["opened_at"] = self.utc_now()
        record.setdefault("pnl", 0.0)

        try:

            storage.save_trade(record)

            self.active_trades[trade_id] = record

            state_manager.set_active_trades(
                len(self.active_trades)
            )

            logger.info(
                "Trade registered: %s | %s | %s",
                trade_id,
                symbol,
                direction
            )

            return True, trade_id

        except Exception:

            logger.exception("Trade registration failed")

            return False, "Trade registration error"

    def update_trade(self, trade_id, updates):

        if trade_id not in self.active_trades:
            return False

        trade = self.active_trades[trade_id]

        trade.update(updates)

        storage.update_trade(trade_id, updates)

        return True

    def close_trade(self, trade_id, pnl, pnl_percent=0.0):

        trade = self.active_trades.get(trade_id)

        if trade is None:
            return False, "Trade not found"

        pnl = float(pnl)
        pnl_percent = float(pnl_percent)

        closed_at = self.utc_now()

        updates = {
            "status": "CLOSED",
            "pnl": pnl,
            "closed_at": closed_at,
        }

        storage.update_trade(trade_id, updates)

        trade.update(updates)

        del self.active_trades[trade_id]

        state_manager.set_active_trades(
            len(self.active_trades)
        )

        if pnl > 0:

            risk_manager.register_win(pnl_percent)

        elif pnl < 0:

            risk_manager.register_loss(pnl_percent)

        state_manager.set_consecutive_losses(
            risk_manager.consecutive_losses
        )

        state_manager.set_daily_trades(
            risk_manager.daily_trades
        )

        logger.info(
            "Trade closed: %s | PnL: %.2f",
            trade_id,
            pnl
        )

        return True, "Trade closed"

    def get_trade(self, trade_id):

        if trade_id in self.active_trades:
            return dict(self.active_trades[trade_id])

        return storage.get_trade(trade_id)

    def get_active_trades(self):

        return [
            dict(trade)
            for trade in self.active_trades.values()
        ]

    def get_trade_history(self, limit=100):

        return storage.get_trades(limit)

    def get_status(self):

        return {
            "active_trades": len(self.active_trades),
            "trades": self.get_active_trades(),
            "risk": risk_manager.get_status(),
        }


trade_manager = TradeManager()
