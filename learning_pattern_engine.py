
"""
Vrotex Bot V1 - Learning Pattern Engine

Identifies recurring patterns in completed trades.

Analyses:
- Instrument performance
- Entry-model performance
- Setup-type performance
- Market-condition performance
- Winning and losing patterns

Does not modify approved strategy rules.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from intelligence_registry import intelligence_registry


logger = logging.getLogger("vrotex.learning_pattern")


class LearningPatternEngine:

    GROUP_FIELDS = (
        "instrument",
        "setup_type",
        "entry_model",
        "market_condition"
    )

    def __init__(
        self,
        registry=None,
        minimum_sample_size=5
    ):
        self.registry = (
            registry or intelligence_registry
        )

        self.minimum_sample_size = max(
            2, int(minimum_sample_size)
        )

        self.analysis_count = 0
        self.last_analysis = None

        logger.info(
            "Learning pattern engine initialized"
        )

    @staticmethod
    def _timestamp():
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _number(value):
        number = float(value)

        if number != number or abs(number) == float("inf"):
            raise ValueError("Invalid numeric trade result")

        return number

    @staticmethod
    def _normalise(value):
        if value is None:
            return "UNKNOWN"

        value = str(value).strip()

        return value if value else "UNKNOWN"

    def _group_trades(self, trades, field):
        groups = defaultdict(list)

        for trade in trades:
            group_value = self._normalise(
                trade.get(field)
            )

            groups[group_value].append(trade)

        return groups

    def _calculate_performance(self, trades):
        results = [
            self._number(trade["pnl"])
            for trade in trades
        ]

        total = len(results)

        wins = sum(
            1 for result in results if result > 0
        )

        losses = sum(
            1 for result in results if result < 0
        )

        breakeven = sum(
            1 for result in results if result == 0
        )

        total_profit = sum(
            result for result in results if result > 0
        )

        total_loss = abs(sum(
            result for result in results if result < 0
        ))

        win_rate = wins / total * 100 if total else 0

        average_result = (
            sum(results) / total if total else 0
        )

        profit_factor = (
            total_profit / total_loss
            if total_loss > 0
            else None
        )

        return {
            "sample_size": total,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate_percent": round(win_rate, 2),
            "average_result": round(average_result, 6),
            "total_result": round(sum(results), 6),
            "profit_factor": (
                round(profit_factor, 4)
                if profit_factor is not None
                else None
            )
        }

    def analyse_patterns(
        self,
        trades: list,
        group_fields: Optional[list] = None
    ) -> dict:
        """
        Analyse completed trades.

        Each trade must contain:
            pnl: numeric net trade result

        Optional grouping fields:
            instrument
            setup_type
            entry_model
            market_condition

        PnL values must use a consistent unit.
        """

        if not isinstance(trades, list):
            return {
                "success": False,
                "status": "INVALID_TRADE_DATA"
            }

        if not trades:
            return {
                "success": True,
                "status": "NO_TRADE_DATA",
                "patterns": {}
            }

        fields = group_fields or list(
            self.GROUP_FIELDS
        )

        invalid_fields = [
            field for field in fields
            if field not in self.GROUP_FIELDS
        ]

        if invalid_fields:
            return {
                "success": False,
                "status": "INVALID_GROUP_FIELDS",
                "invalid_fields": invalid_fields
            }

        try:
            valid_trades = []

            for trade in trades:

                if not isinstance(trade, dict):
                    continue

                if "pnl" not in trade:
                    continue

                self._number(trade["pnl"])
                valid_trades.append(trade)

            if not valid_trades:
                return {
                    "success": False,
                    "status": "NO_VALID_COMPLETED_TRADES"
                }

            patterns = {}

            for field in fields:

                groups = self._group_trades(
                    valid_trades,
                    field
                )

                field_patterns = {}

                for group_name, group_trades in groups.items():

                    performance = (
                        self._calculate_performance(
                            group_trades
                        )
                    )

                    sample_size = (
                        performance["sample_size"]
                    )

                    field_patterns[group_name] = {
                        **performance,
                        "evidence_status": (
                            "SUFFICIENT_SAMPLE"
                            if sample_size >= self.minimum_sample_size
                            else "INSUFFICIENT_SAMPLE"
                        )
                    }

                patterns[field] = field_patterns

            result = {
                "success": True,
                "status": "ANALYSIS_COMPLETED",
                "trades_analysed": len(valid_trades),
                "minimum_sample_size": (
                    self.minimum_sample_size
                ),
                "patterns": patterns,
                "analysed_at": self._timestamp()
            }

            self.registry.publish(
                key="learning.detected_patterns",
                value=result,
                source="learning_pattern_engine"
            )

            self.analysis_count += 1
            self.last_analysis = result["analysed_at"]

            logger.info(
                "Pattern analysis completed: %s trades",
                len(valid_trades)
            )

            return result

        except (ValueError, TypeError, KeyError) as exc:
            logger.warning(
                "Invalid pattern analysis data: %s",
                exc
            )

            return {
                "success": False,
                "status": "INVALID_TRADE_DATA",
                "error": str(exc)
            }

        except Exception:
            logger.exception(
                "Unexpected pattern analysis failure"
            )

            return {
                "success": False,
                "status": "ANALYSIS_ERROR"
            }

    def get_latest_patterns(self):
        """Retrieve the latest published pattern analysis."""

        return self.registry.get(
            "learning.detected_patterns"
        )

    def get_status(self):
        return {
            "status": "ACTIVE",
            "analysis_count": self.analysis_count,
            "minimum_sample_size": (
                self.minimum_sample_size
            ),
            "last_analysis": self.last_analysis,
            "strategy_auto_modification": False
        }


# Shared engine instance.
learning_pattern_engine = LearningPatternEngine()
