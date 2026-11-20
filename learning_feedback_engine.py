
"""
Vrotex Bot V1 - Learning Feedback Engine

Evaluates completed trades and creates structured
feedback for the learning system.

Does not automatically modify strategy rules.
"""

import logging
from datetime import datetime, timezone

from knowledge_learning_core import knowledge_learning_core
from intelligence_registry import intelligence_registry


logger = logging.getLogger("vrotex.learning_feedback")


class LearningFeedbackEngine:

    def __init__(
        self,
        learning_core=None,
        registry=None
    ):
        self.learning_core = (
            learning_core or knowledge_learning_core
        )

        self.registry = (
            registry or intelligence_registry
        )

        self.feedback_count = 0
        self.last_feedback = None

        logger.info(
            "Learning feedback engine initialized"
        )

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _validate_trade(trade):
        if not isinstance(trade, dict):
            raise ValueError("Trade must be a dictionary")

        required = [
            "trade_id",
            "instrument",
            "setup_type",
            "pnl"
        ]

        missing = [
            field for field in required
            if field not in trade
            or trade[field] is None
            or str(trade[field]).strip() == ""
        ]

        if missing:
            raise ValueError(
                f"Missing trade fields: {missing}"
            )

        pnl = float(trade["pnl"])

        if pnl != pnl or abs(pnl) == float("inf"):
            raise ValueError("Invalid trade PnL")

        return pnl

    @staticmethod
    def _classify_result(pnl):
        if pnl > 0:
            return "WIN"

        if pnl < 0:
            return "LOSS"

        return "BREAKEVEN"

    def evaluate_trade(self, trade: dict) -> dict:
        """
        Evaluate a completed trade.

        Expected fields:
            trade_id
            instrument
            setup_type
            pnl

        Optional fields:
            entry_model
            market_condition
            entry_price
            exit_price
            stop_loss
            take_profit
            risk_percent
            outcome_reason
        """

        try:
            pnl = self._validate_trade(trade)

            outcome = self._classify_result(pnl)

            feedback = {
                "trade_id": str(trade["trade_id"]),
                "instrument": str(trade["instrument"]),
                "setup_type": str(trade["setup_type"]),
                "entry_model": trade.get(
                    "entry_model", "UNKNOWN"
                ),
                "market_condition": trade.get(
                    "market_condition", "UNKNOWN"
                ),
                "pnl": pnl,
                "outcome": outcome,
                "outcome_reason": trade.get(
                    "outcome_reason"
                ),
                "evaluated_at": self._timestamp()
            }

            self._record_feedback(feedback)

            self.registry.publish(
                key=(
                    "learning.feedback."
                    + feedback["trade_id"]
                ),
                value=feedback,
                source="learning_feedback_engine"
            )

            self.feedback_count += 1
            self.last_feedback = feedback["evaluated_at"]

            logger.info(
                "Trade feedback recorded: %s %s %s",
                feedback["trade_id"],
                feedback["instrument"],
                outcome
            )

            return {
                "success": True,
                "status": "FEEDBACK_RECORDED",
                "feedback": feedback
            }

        except ValueError as exc:
            return {
                "success": False,
                "status": "INVALID_TRADE",
                "error": str(exc)
            }

        except Exception as exc:
            logger.exception(
                "Trade feedback evaluation failed"
            )

            return {
                "success": False,
                "status": "FEEDBACK_ERROR",
                "error": str(exc)
            }

    def _record_feedback(self, feedback):
        """
        Store feedback using the existing learning core.

        This method expects the existing
        record_trade_outcome() interface.
        """

        self.learning_core.record_trade_outcome(
            trade_id=feedback["trade_id"],
            instrument=feedback["instrument"],
            setup_type=feedback["setup_type"],
            outcome=feedback["outcome"],
            pnl=feedback["pnl"],
            metadata={
                "entry_model": feedback["entry_model"],
                "market_condition": feedback["market_condition"],
                "outcome_reason": feedback["outcome_reason"],
                "evaluated_at": feedback["evaluated_at"]
            }
        )

    def evaluate_batch(self, trades: list) -> dict:
        """Evaluate multiple completed trades."""

        if not isinstance(trades, list):
            return {
                "success": False,
                "status": "INVALID_BATCH"
            }

        results = []

        for trade in trades:
            results.append(
                self.evaluate_trade(trade)
            )

        successful = sum(
            1 for result in results
            if result["success"]
        )

        return {
            "success": successful == len(results),
            "total": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "results": results,
            "evaluated_at": self._timestamp()
        }

    def get_status(self):
        return {
            "status": "ACTIVE",
            "feedback_count": self.feedback_count,
            "last_feedback": self.last_feedback,
            "strategy_auto_modification": False
        }


# Shared learning feedback engine.
learning_feedback_engine = LearningFeedbackEngine()
