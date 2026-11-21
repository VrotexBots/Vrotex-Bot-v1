"""
Vrotex Bot V1 — Strategy & Knowledge Library
--------------------------------------------
Purpose:
    Store approved strategy knowledge.
    Provide searchable rules to the Intelligence Core.
    Protect strategy rules against accidental modification.

Version: V1
Trading instruments: EURUSD, GBPUSD, BTCUSD
Strategy timeframes: H1 -> M5 -> M1

No trading execution is performed in this module.
No strategy rules are automatically changed by learning.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("vrotex.strategy_knowledge_library")


class StrategyKnowledgeLibrary:
    """Central read-only library of approved Vrotex strategy knowledge."""

    VERSION = "1.0.0"

    INSTRUMENTS = (
        "EURUSD",
        "GBPUSD",
        "BTCUSD",
    )

    STRATEGY_TIMEFRAMES = (
        "H1",
        "M5",
        "M1",
    )

    # ---------------------------------------------------------
    # APPROVED STRATEGY KNOWLEDGE
    # ---------------------------------------------------------

    KNOWLEDGE = {

        "core_strategy": {
            "name": "Vrotex V1 Core Strategy",
            "description": (
                "Multi-timeframe Smart Money Concepts strategy "
                "using H1 narrative, M5 confirmation, and M1 execution."
            ),
            "timeframes": ["H1", "M5", "M1"],
            "instruments": [
                "EURUSD",
                "GBPUSD",
                "BTCUSD",
            ],
        },

        # -----------------------------------------------------
        # MARKET STRUCTURE
        # -----------------------------------------------------

        "market_structure": {

            "bullish_structure": {
                "description": "Higher Highs and Higher Lows",
                "bias": "BULLISH",
            },

            "bearish_structure": {
                "description": "Lower Highs and Lower Lows",
                "bias": "BEARISH",
            },

            "ranging_structure": {
                "description": "Market lacks confirmed directional structure",
                "bias": "RANGING",
            },

            "bos": {
                "name": "Break of Structure",
                "rule": (
                    "A BOS requires a candle BODY CLOSE beyond "
                    "the relevant structural level."
                ),
                "wick_only": False,
                "confirmation": "FULL_BODY_CLOSE",
            },

            "choch": {
                "name": "Change of Character",
                "rule": (
                    "A CHoCH requires a candle BODY CLOSE beyond "
                    "the relevant opposing structural level."
                ),
                "wick_only": False,
                "confirmation": "FULL_BODY_CLOSE",
            },

            "wick_rule": {
                "rule": (
                    "A wick breaking a level without a candle "
                    "body close beyond it is classified as a "
                    "liquidity sweep or probe, not a confirmed BOS."
                ),
            },
        },

        # -----------------------------------------------------
        # H1 NARRATIVE
        # -----------------------------------------------------

        "h1_narrative": {

            "purpose": (
                "Determine external market direction, "
                "structure, liquidity objectives, and location."
            ),

            "bullish_conditions": [
                "Bullish structural narrative",
                "Higher Highs and Higher Lows",
                "Identify strong lows",
                "Identify weak highs",
                "Identify bullish liquidity objectives",
            ],

            "bearish_conditions": [
                "Bearish structural narrative",
                "Lower Highs and Lower Lows",
                "Identify strong highs",
                "Identify weak lows",
                "Identify bearish liquidity objectives",
            ],

            "neutral_conditions": [
                "Unclear structure",
                "Conflicting directional evidence",
                "Range-bound market",
            ],

            "rule": (
                "H1 determines the external narrative. "
                "It does not independently authorize an entry."
            ),
        },

        # -----------------------------------------------------
        # PREMIUM / DISCOUNT
        # -----------------------------------------------------

        "premium_discount": {

            "equilibrium": 0.50,

            "bullish_range": {
                "description": (
                    "Strong Low to Weak High"
                ),
                "preferred_location": "DISCOUNT",
            },

            "bearish_range": {
                "description": (
                    "Strong High to Weak Low"
                ),
                "preferred_location": "PREMIUM",
            },

            "equilibrium_rule": (
                "The 50 percent level is equilibrium."
            ),

            "rule": (
                "Pro-trend setups should preferably form in "
                "the appropriate premium or discount zone."
            ),
        },

        # -----------------------------------------------------
        # POINTS OF INTEREST
        # -----------------------------------------------------

        "points_of_interest": {

            "order_block": {
                "enabled": True,
                "requirement": (
                    "Identify a relevant structural order block."
                ),
            },

            "fair_value_gap": {
                "enabled": True,
                "requirement": (
                    "Identify displacement-created imbalance."
                ),
            },

            "inverse_fvg": {
                "enabled": True,
            },

            "breaker_block": {
                "enabled": True,
            },

            "mitigation_block": {
                "enabled": True,
            },

            "liquidity": {
                "enabled": True,
                "types": [
                    "Equal Highs",
                    "Equal Lows",
                    "Internal Liquidity",
                    "External Liquidity",
                    "Inducement",
                    "Liquidity Sweeps",
                ],
            },

            "quality_requirements": [
                "Relevant to market structure",
                "Location is justified",
                "Liquidity context is identified",
                "Avoid treating every zone as valid",
            ],
        },

        # -----------------------------------------------------
        # PRO-TREND STRATEGY
        # -----------------------------------------------------

        "pro_trend_strategy": {

            "enabled": True,

            "workflow": [
                "Determine H1 directional narrative",
                "Identify external liquidity",
                "Identify valid H1 POI",
                "Wait for liquidity interaction",
                "Move to M5 for confirmation",
                "Confirm M5 structure and displacement",
                "Move to M1 for execution",
            ],

            "entry_models": [

                {
                    "id": "PT_M1_CHOCH_FVG",
                    "name": "CHoCH + FVG",
                    "timeframe": "M1",
                    "enabled": True,
                },

                {
                    "id": "PT_M1_SWEEP_ENGULFING",
                    "name": "Sweep + Engulfing",
                    "timeframe": "M1",
                    "enabled": True,
                },

                {
                    "id": "PT_M1_BREAKER",
                    "name": "Breaker Entry",
                    "timeframe": "M1",
                    "enabled": True,
                },

                {
                    "id": "PT_M1_MSS_DISPLACEMENT",
                    "name": "MSS + Sweep + Displacement",
                    "timeframe": "M1",
                    "enabled": True,
                },

                {
                    "id": "PT_M1_ZONE_FLIP",
                    "name": "Supply-to-Demand / Demand-to-Supply Flip",
                    "timeframe": "M1",
                    "enabled": True,
                },
            ],

            "confirmation_requirements": [
                "H1 narrative supports the trade direction",
                "Relevant POI identified",
                "Liquidity context established",
                "M5 external confirmation",
                "M5 displacement",
                "M5 FVG where required by the model",
                "M1 entry model confirmed",
            ],
        },

        # -----------------------------------------------------
        # M5 CONFIRMATION
        # -----------------------------------------------------

        "m5_confirmation": {

            "required_evidence": [
                "Liquidity sweep",
                "External CHoCH",
                "Displacement",
                "Fair Value Gap",
                "Full-body candle close confirmation",
            ],

            "protected_range": True,

            "retracement_level": 0.50,

            "rule": (
                "M5 confirms the setup before the M1 entry "
                "process begins."
            ),
        },

        # -----------------------------------------------------
        # COUNTER-TREND STRATEGY
        # -----------------------------------------------------

        "counter_trend_strategy": {

            "enabled": True,

            "workflow": [
                "Identify H1 external context",
                "Identify relevant external liquidity",
                "Assess the opposing structural area",
                "Use M5 external context",
                "Wait for M5 internal confirmation",
                "Use M1 for execution confirmation",
            ],

            "entry_model_count": 3,

            "entry_models": [],

            "models_status": (
                "The three previously approved counter-trend "
                "model definitions must be loaded from the "
                "original approved strategy source. They are "
                "intentionally not invented here."
            ),

            "rule": (
                "Counter-trend setups must not be treated as "
                "ordinary pro-trend setups."
            ),
        },

        # -----------------------------------------------------
        # LIQUIDITY
        # -----------------------------------------------------

        "liquidity": {

            "enabled": True,

            "types": [
                "Equal Highs",
                "Equal Lows",
                "Previous Highs",
                "Previous Lows",
                "Internal Liquidity",
                "External Liquidity",
                "Inducement",
                "Liquidity Sweeps",
            ],

            "sessions": [
                "Asian Session",
                "London Session",
                "New York Session",
            ],

            "sweep_rule": (
                "A wick through liquidity without a confirmed "
                "body close beyond structure is a sweep/probe."
            ),
        },

        # -----------------------------------------------------
        # ENTRY QUALITY
        # -----------------------------------------------------

        "entry_quality": {

            "spread_buffer_pips": 1.0,

            "touch_rule": {
                "maximum_touches": 3,
                "description": (
                    "Apply the approved three-touch rule "
                    "when assessing POI quality."
                ),
            },

            "avoid": [
                "Unconfirmed structural breaks",
                "Chasing displacement",
                "Entering without required confirmation",
                "Ignoring opposing liquidity",
                "Ignoring spread",
                "Invalidated POIs",
            ],
        },

        # -----------------------------------------------------
        # TRADE MANAGEMENT
        # -----------------------------------------------------

        "trade_management": {

            "break_even_rule": (
                "Move to break-even after the approved "
                "M1 external structural break."
            ),

            "risk_reward": (
                "Evaluate the available opposing liquidity "
                "and trade quality before execution."
            ),
        },

        # -----------------------------------------------------
        # STRATEGY PROTECTION
        # -----------------------------------------------------

        "protection": {

            "automatic_strategy_changes": False,

            "automatic_model_additions": False,

            "automatic_model_removals": False,

            "automatic_rule_rewrites": False,

            "learning_may_improve": [
                "Pattern recognition",
                "Historical pattern comparisons",
                "Setup quality analysis",
                "Outcome analysis",
                "Market condition classification",
            ],

            "learning_must_not_change": [
                "Approved strategy rules",
                "Entry model definitions",
                "Trading instruments",
                "Risk rules",
                "Timeframes",
            ],
        },
    }

    # ---------------------------------------------------------
    # INITIALIZATION
    # ---------------------------------------------------------

    def __init__(self):

        self._knowledge = self.KNOWLEDGE

        self._loaded = False

        self._knowledge_count = 0

        self.load()

    # ---------------------------------------------------------
    # LOAD LIBRARY
    # ---------------------------------------------------------

    def load(self) -> bool:

        try:

            self._knowledge_count = len(self._knowledge)

            self._loaded = True

            logger.info(
                "Strategy Knowledge Library loaded | "
                "Version=%s | Sections=%s",
                self.VERSION,
                self._knowledge_count,
            )

            return True

        except Exception:

            logger.exception(
                "Strategy Knowledge Library failed to load"
            )

            self._loaded = False

            return False

    # ---------------------------------------------------------
    # STATUS
    # ---------------------------------------------------------

    def get_status(self) -> dict[str, Any]:

        counter_trend = self._knowledge[
            "counter_trend_strategy"
        ]

        return {

            "loaded": self._loaded,

            "version": self.VERSION,

            "sections": self._knowledge_count,

            "instruments": list(self.INSTRUMENTS),

            "strategy_timeframes": list(
                self.STRATEGY_TIMEFRAMES
            ),

            "pro_trend_models": len(
                self._knowledge[
                    "pro_trend_strategy"
                ]["entry_models"]
            ),

            "counter_trend_models": (
                counter_trend["entry_model_count"]
            ),

            "counter_trend_definitions_loaded": len(
                counter_trend["entry_models"]
            ),

            "strategy_protected": True,

            "automatic_strategy_changes": False,
        }

    # ---------------------------------------------------------
    # GET COMPLETE KNOWLEDGE
    # ---------------------------------------------------------

    def get_all(self) -> dict[str, Any]:

        return self._knowledge

    # ---------------------------------------------------------
    # GET SECTION
    # ---------------------------------------------------------

    def get_section(
        self,
        section_name: str,
    ) -> dict[str, Any] | None:

        return self._knowledge.get(section_name)

    # ---------------------------------------------------------
    # GET PRO-TREND MODELS
    # ---------------------------------------------------------

    def get_pro_trend_models(self) -> list[dict[str, Any]]:

        return self._knowledge[
            "pro_trend_strategy"
        ]["entry_models"]

    # ---------------------------------------------------------
    # GET COUNTER-TREND MODELS
    # ---------------------------------------------------------

    def get_counter_trend_models(self) -> list[dict[str, Any]]:

        return self._knowledge[
            "counter_trend_strategy"
        ]["entry_models"]

    # ---------------------------------------------------------
    # GET RULES FOR INTELLIGENCE CORE
    # ---------------------------------------------------------

    def get_strategy_context(
        self,
        instrument: str | None = None,
    ) -> dict[str, Any]:

        context = {

            "library_version": self.VERSION,

            "strategy": self._knowledge[
                "core_strategy"
            ],

            "market_structure": self._knowledge[
                "market_structure"
            ],

            "h1_narrative": self._knowledge[
                "h1_narrative"
            ],

            "premium_discount": self._knowledge[
                "premium_discount"
            ],

            "points_of_interest": self._knowledge[
                "points_of_interest"
            ],

            "pro_trend_strategy": self._knowledge[
                "pro_trend_strategy"
            ],

            "m5_confirmation": self._knowledge[
                "m5_confirmation"
            ],

            "counter_trend_strategy": self._knowledge[
                "counter_trend_strategy"
            ],

            "liquidity": self._knowledge[
                "liquidity"
            ],

            "entry_quality": self._knowledge[
                "entry_quality"
            ],

            "trade_management": self._knowledge[
                "trade_management"
            ],

            "protection": self._knowledge[
                "protection"
            ],
        }

        if instrument is not None:

            instrument = instrument.upper()

            if instrument not in self.INSTRUMENTS:

                raise ValueError(
                    f"Instrument not approved for V1: "
                    f"{instrument}"
                )

            context["instrument"] = instrument

        return context

    # ---------------------------------------------------------
    # SEARCH KNOWLEDGE
    # ---------------------------------------------------------

    def search(
        self,
        query: str,
    ) -> list[dict[str, Any]]:

        query = query.lower().strip()

        if not query:

            return []

        results = []

        def search_recursive(
            node: Any,
            path: str,
        ):

            if isinstance(node, dict):

                for key, value in node.items():

                    current_path = (
                        f"{path}.{key}"
                        if path
                        else key
                    )

                    if query in key.lower():

                        results.append({
                            "path": current_path,
                            "content": value,
                        })

                    search_recursive(
                        value,
                        current_path,
                    )

            elif isinstance(node, list):

                for index, value in enumerate(node):

                    search_recursive(
                        value,
                        f"{path}[{index}]",
                    )

            elif isinstance(node, str):

                if query in node.lower():

                    results.append({
                        "path": path,
                        "content": node,
                    })

        search_recursive(
            self._knowledge,
            "",
        )

        return results

    # ---------------------------------------------------------
    # CHECK APPROVED INSTRUMENT
    # ---------------------------------------------------------

    def is_approved_instrument(
        self,
        instrument: str,
    ) -> bool:

        return (
            instrument.upper()
            in self.INSTRUMENTS
        )

    # ---------------------------------------------------------
    # CHECK APPROVED TIMEFRAME
    # ---------------------------------------------------------

    def is_strategy_timeframe(
        self,
        timeframe: str,
    ) -> bool:

        return (
            timeframe.upper()
            in self.STRATEGY_TIMEFRAMES
        )

    # ---------------------------------------------------------
    # STRATEGY PROTECTION
    # ---------------------------------------------------------

    def validate_strategy_integrity(self) -> bool:

        required_sections = [

            "core_strategy",
            "market_structure",
            "h1_narrative",
            "premium_discount",
            "points_of_interest",
            "pro_trend_strategy",
            "m5_confirmation",
            "counter_trend_strategy",
            "liquidity",
            "entry_quality",
            "trade_management",
            "protection",
        ]

        for section in required_sections:

            if section not in self._knowledge:

                logger.error(
                    "Strategy knowledge missing: %s",
                    section,
                )

                return False

        if (
            self._knowledge[
                "protection"
            ]["automatic_strategy_changes"]
        ):

            logger.error(
                "Strategy protection violation"
            )

            return False

        return True


# -------------------------------------------------------------
# MODULE-LEVEL INSTANCE
# -------------------------------------------------------------

strategy_knowledge_library = StrategyKnowledgeLibrary()


# -------------------------------------------------------------
# SIMPLE ACCESS FUNCTIONS
# -------------------------------------------------------------

def get_strategy_knowledge():

    return strategy_knowledge_library.get_all()


def get_strategy_context(instrument=None):

    return strategy_knowledge_library.get_strategy_context(
        instrument
    )


def search_strategy_knowledge(query):

    return strategy_knowledge_library.search(query)


def get_strategy_library_status():

    return strategy_knowledge_library.get_status()


def validate_strategy_library():

    return strategy_knowledge_library.validate_strategy_integrity()
