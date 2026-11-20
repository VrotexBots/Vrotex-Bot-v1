
"""
Vrotex Bot V1 - SMC Knowledge Base

Contains approved Smart Money Concepts (SMC)
rules, explanations and practical examples.

This is a knowledge reference module.
It does not execute trades or change strategy rules.
"""

from copy import deepcopy


class SMCKnowledgeBase:

    VERSION = "1.0"

    def __init__(self):
        self.rules = self._build_rules()
        self.examples = self._build_examples()

    def _build_rules(self):
        return {
            "market_structure": {
                "bullish": {
                    "sequence": ["HH", "HL"],
                    "meaning": "Higher highs and higher lows indicate bullish structure."
                },
                "bearish": {
                    "sequence": ["LH", "LL"],
                    "meaning": "Lower highs and lower lows indicate bearish structure."
                }
            },

            "bos": {
                "meaning": "Break of Structure confirms continuation in the current structural direction.",
                "confirmation": "A full candle body must close beyond the relevant structural level.",
                "wick_only": "A wick beyond the level without a body close is not a confirmed BOS."
            },

            "choch": {
                "meaning": "Change of Character indicates a possible shift in market direction.",
                "confirmation": "A full candle body must close beyond the relevant opposing structural level.",
                "warning": "A CHoCH is not automatically a trade entry."
            },

            "liquidity": {
                "types": [
                    "Equal highs",
                    "Equal lows",
                    "Previous swing highs",
                    "Previous swing lows",
                    "Buy-side liquidity",
                    "Sell-side liquidity"
                ],
                "sweep": {
                    "meaning": "Price moves beyond a liquidity level and then closes back inside.",
                    "confirmation": "A wick through the level followed by a close back inside is a sweep candidate.",
                    "warning": "A sweep alone does not confirm a reversal."
                }
            },

            "order_blocks": {
                "bullish": "A potential demand area associated with the final bearish candle before bullish displacement.",
                "bearish": "A potential supply area associated with the final bullish candle before bearish displacement.",
                "requirements": [
                    "Relevant structural context",
                    "Clear displacement",
                    "A meaningful break or shift in structure",
                    "The zone must not already be invalidated"
                ],
                "warning": "An opposing candle alone is not sufficient to confirm an order block."
            },

            "fair_value_gaps": {
                "bullish": "A three-candle imbalance where the first candle high is below the third candle low.",
                "bearish": "A three-candle imbalance where the first candle low is above the third candle high.",
                "requirements": [
                    "Correct three-candle relationship",
                    "Clear directional displacement",
                    "Relevant market structure",
                    "Check whether the gap has been mitigated"
                ]
            },

            "premium_discount": {
                "equilibrium": 0.50,
                "bullish": "Prefer demand and long opportunities in discount.",
                "bearish": "Prefer supply and short opportunities in premium.",
                "rule": "Use the relevant confirmed dealing range."
            },

            "fibonacci": {
                "bullish": "Measure from the strong low toward the weak high.",
                "bearish": "Measure from the strong high toward the weak low.",
                "equilibrium": 0.50
            },

            "timeframe_model": {
                "H1": "External market narrative, structure, liquidity and major POIs.",
                "M5": "Sweep, external CHoCH, displacement, FVG and confirmation.",
                "M1": "Entry confirmation and execution model.",
                "H4": "Market data only; excluded from the V1 strategy."
            },

            "entry_models": [
                "CHoCH plus FVG",
                "Liquidity sweep plus engulfing candle",
                "Breaker block",
                "MSS sweep plus displacement",
                "Supply-to-demand flip",
                "Demand-to-supply flip"
            ],

            "execution_rules": {
                "minimum_score": 85,
                "spread_buffer_pips": {
                    "minimum": 1,
                    "maximum": 2
                },
                "touch_limit": 3,
                "break_even": "Move to break-even after the confirmed M1 external break."
            }
        }

    def _build_examples(self):
        return {
            "bullish_example": {
                "name": "Bullish liquidity sweep and continuation",
                "steps": [
                    "H1 establishes bullish HH and HL structure.",
                    "Price trades into a clean demand or bullish FVG area in discount.",
                    "Price sweeps relevant sell-side liquidity.",
                    "M5 confirms an external bullish CHoCH with a full-body close.",
                    "Bullish displacement creates an FVG.",
                    "Price retraces toward the M5 confirmation area.",
                    "M1 confirms an approved entry model.",
                    "The complete setup is scored against the 85-point threshold."
                ],
                "expected_direction": "BUY",
                "validity": "Valid only when every required confirmation is present."
            },

            "bearish_example": {
                "name": "Bearish liquidity sweep and continuation",
                "steps": [
                    "H1 establishes bearish LH and LL structure.",
                    "Price trades into a clean supply or bearish FVG area in premium.",
                    "Price sweeps relevant buy-side liquidity.",
                    "M5 confirms an external bearish CHoCH with a full-body close.",
                    "Bearish displacement creates an FVG.",
                    "Price retraces toward the M5 confirmation area.",
                    "M1 confirms an approved entry model.",
                    "The complete setup is scored against the 85-point threshold."
                ],
                "expected_direction": "SELL",
                "validity": "Valid only when every required confirmation is present."
            },

            "invalid_wick_break": {
                "name": "Wick beyond structure without body close",
                "steps": [
                    "Price wicks beyond a structural high.",
                    "The candle closes back below the structural high."
                ],
                "expected_result": "NOT_CONFIRMED",
                "reason": "A wick alone does not confirm BOS or CHoCH."
            },

            "invalid_low_score": {
                "name": "Setup below minimum score",
                "score": 84,
                "minimum_required": 85,
                "expected_result": "REJECTED",
                "reason": "The setup does not meet the approved minimum score."
            },

            "invalid_unconfirmed_sweep": {
                "name": "Sweep without M5 confirmation",
                "steps": [
                    "Price sweeps liquidity.",
                    "No confirmed M5 external CHoCH follows.",
                    "No valid displacement confirmation appears."
                ],
                "expected_result": "WAIT",
                "reason": "A liquidity sweep alone is not an entry signal."
            }
        }

    def get_all_rules(self):
        return deepcopy(self.rules)

    def get_rule(self, category):
        if category not in self.rules:
            return None

        return deepcopy(self.rules[category])

    def get_all_examples(self):
        return deepcopy(self.examples)

    def get_example(self, example_name):
        if example_name not in self.examples:
            return None

        return deepcopy(self.examples[example_name])

    def validate_setup_score(self, score):
        try:
            score = float(score)
        except (TypeError, ValueError):
            return False

        return 0 <= score <= 100 and score >= 85

    def validate_structure_break(
        self,
        candle_body_closed_beyond_level
    ):
        return candle_body_closed_beyond_level is True

    def validate_entry_timeframe(self, timeframe):
        return timeframe == "M1"

    def get_timeframe_sequence(self):
        return ["H1", "M5", "M1"]

    def get_status(self):
        return {
            "component": "SMC_KNOWLEDGE_BASE",
            "status": "ACTIVE",
            "version": self.VERSION,
            "rule_categories": len(self.rules),
            "examples": len(self.examples),
            "strategy_timeframes": self.get_timeframe_sequence(),
            "minimum_setup_score": 85
        }


smc_knowledge_base = SMCKnowledgeBase()
