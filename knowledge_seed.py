
"""
Vrotex Bot V1 - Knowledge Seed

Loads approved Vrotex V1 trading knowledge
into the persistent knowledge library.

Safe to run more than once.
Does not overwrite existing knowledge.
"""

import logging

from knowledge_library import knowledge_library


logger = logging.getLogger("vrotex.knowledge_seed")


VROTEX_KNOWLEDGE = [
    {
        "knowledge_key": "V1_TIMEFRAME_HIERARCHY",
        "category": "strategy",
        "title": "V1 Multi-Timeframe Hierarchy",
        "content": (
            "Vrotex V1 uses H1 for external market narrative, "
            "M5 for confirmation and M1 for entry execution. "
            "H4 is market-data context only and is not part "
            "of the V1 strategy decision hierarchy."
        ),
        "tags": ["H1", "M5", "M1", "timeframes"]
    },
    {
        "knowledge_key": "V1_MARKET_STRUCTURE",
        "category": "smc",
        "title": "Market Structure",
        "content": (
            "Bullish structure is identified through higher "
            "highs and higher lows. Bearish structure is "
            "identified through lower highs and lower lows. "
            "Structure must be evaluated using confirmed "
            "price action."
        ),
        "tags": ["HH", "HL", "LH", "LL", "structure"]
    },
    {
        "knowledge_key": "V1_BOS_CHOCH",
        "category": "smc",
        "title": "BOS and CHoCH Confirmation",
        "content": (
            "A valid BOS or CHoCH requires a full candle-body "
            "close beyond the relevant structure level. "
            "A wick beyond a level alone is a liquidity sweep "
            "or probe, not a confirmed structural break."
        ),
        "tags": ["BOS", "CHoCH", "candle close"]
    },
    {
        "knowledge_key": "V1_LIQUIDITY_SWEEPS",
        "category": "liquidity",
        "title": "Liquidity Sweeps",
        "content": (
            "A wick through a liquidity level followed by a "
            "close back inside the level is treated as a "
            "potential liquidity sweep. A subsequent confirmed "
            "close beyond the level must be evaluated separately "
            "as a possible liquidity run."
        ),
        "tags": ["liquidity", "sweep", "run", "wick"]
    },
    {
        "knowledge_key": "V1_PREMIUM_DISCOUNT",
        "category": "smc",
        "title": "Premium and Discount",
        "content": (
            "Use the relevant confirmed dealing range and its "
            "50 percent equilibrium. Bullish demand opportunities "
            "are preferred in discount. Bearish supply "
            "opportunities are preferred in premium."
        ),
        "tags": ["premium", "discount", "equilibrium", "50 percent"]
    },
    {
        "knowledge_key": "V1_FIBONACCI_DIRECTION",
        "category": "smc",
        "title": "Fibonacci Dealing Range Direction",
        "content": (
            "For bullish analysis, measure from the strong low "
            "toward the weak high. For bearish analysis, measure "
            "from the strong high toward the weak low. "
            "The 50 percent level represents equilibrium."
        ),
        "tags": ["fibonacci", "strong low", "weak high",
                "strong high", "weak low"]
    },
    {
        "knowledge_key": "V1_POINT_OF_INTEREST",
        "category": "smc",
        "title": "Order Blocks and Fair Value Gaps",
        "content": (
            "Prefer clean and unmitigated higher-timeframe "
            "order blocks and fair value gaps. Evaluate their "
            "relationship with liquidity, inducement, market "
            "structure and the opposing liquidity target."
        ),
        "tags": ["order block", "OB", "FVG", "mitigation", "POI"]
    },
    {
        "knowledge_key": "V1_M5_CONFIRMATION",
        "category": "entry_confirmation",
        "title": "M5 Confirmation Requirements",
        "content": (
            "After the H1 point of interest is reached following "
            "the relevant liquidity event, inspect M5 for a "
            "sweep, external CHoCH, displacement, fair value gap "
            "and full-body close confirmation. Track the "
            "protected range and its 50 percent retracement."
        ),
        "tags": ["M5", "sweep", "CHoCH", "displacement", "FVG"]
    },
    {
        "knowledge_key": "V1_M1_ENTRY_MODELS",
        "category": "entry_models",
        "title": "Approved M1 Entry Models",
        "content": (
            "Approved entry models are CHoCH plus FVG, "
            "sweep plus engulfing, breaker, MSS sweep plus "
            "displacement, and support-to-demand or "
            "demand-to-support flip models."
        ),
        "tags": ["M1", "CHoCH", "FVG", "engulfing",
                "breaker", "MSS", "S2D", "D2S"]
    },
    {
        "knowledge_key": "V1_TOUCH_RULE",
        "category": "entry_models",
        "title": "Three-Touch Rule",
        "content": (
            "Apply the approved three-touch rule when evaluating "
            "a level. Track previous interactions and avoid "
            "treating repeated touches as automatically valid "
            "fresh entry opportunities."
        ),
        "tags": ["three touch", "level", "mitigation"]
    },
    {
        "knowledge_key": "V1_SPREAD_BUFFER",
        "category": "execution",
        "title": "Spread Buffer",
        "content": (
            "Account for a one-to-two pip spread buffer when "
            "evaluating entry and stop placement. The calculation "
            "must respect the instrument's actual pip size."
        ),
        "tags": ["spread", "pip", "execution", "stop loss"]
    },
    {
        "knowledge_key": "V1_BREAK_EVEN",
        "category": "trade_management",
        "title": "Break-Even Management",
        "content": (
            "Break-even management is triggered after the "
            "approved M1 external structural break. Confirm "
            "the break before modifying the position stop."
        ),
        "tags": ["break even", "BE", "M1", "position management"]
    },
    {
        "knowledge_key": "V1_A_PLUS_THRESHOLD",
        "category": "decision_rules",
        "title": "A+ Trade Qualification",
        "content": (
            "Evaluate Structure, Point of Interest, Liquidity, "
            "Entry Models, Timeframe Alignment, Fundamentals, "
            "and Trade Quality and Risk. The minimum qualifying "
            "score is 85 out of 100. A score of 84 must be rejected."
        ),
        "tags": ["A+", "score", "85", "decision engine"]
    },
    {
        "knowledge_key": "V1_RISK_LIMITS",
        "category": "risk",
        "title": "V1 Risk Limits",
        "content": (
            "The approved baseline is one percent risk per trade, "
            "a maximum of five trades per day, and a trading stop "
            "after two consecutive losses. The daily loss limit "
            "is two percent. Risk controls must account for "
            "simultaneous open positions."
        ),
        "tags": ["risk", "1 percent", "five trades",
                "two losses", "daily loss"]
    },
    {
        "knowledge_key": "V1_INSTRUMENTS",
        "category": "instruments",
        "title": "Approved V1 Instruments",
        "content": (
            "V1 scans EURUSD, GBPUSD, USDJPY, EURJPY, EURGBP "
            "and BTCUSD only. Other instruments are outside "
            "the approved V1 scope."
        ),
        "tags": ["EURUSD", "GBPUSD", "USDJPY",
                "EURJPY", "EURGBP", "BTCUSD"]
    }
]


def seed_knowledge():
    """Insert approved V1 knowledge without overwriting records."""

    results = {
        "added": 0,
        "already_exists": 0,
        "failed": 0,
        "errors": []
    }

    for item in VROTEX_KNOWLEDGE:
        try:
            result = knowledge_library.add_knowledge(
                knowledge_key=item["knowledge_key"],
                category=item["category"],
                title=item["title"],
                content=item["content"],
                source="Vrotex Bot V1 Approved Strategy",
                tags=item["tags"],
                metadata={
                    "project": "Vrotex Bot V1",
                    "approved_strategy": True,
                    "seed_version": 1
                }
            )

            if result["status"] == "ADDED":
                results["added"] += 1
            else:
                results["already_exists"] += 1

        except Exception as exc:
            results["failed"] += 1
            results["errors"].append({
                "knowledge_key": item["knowledge_key"],
                "error": str(exc)
            })

            logger.exception(
                "Failed to seed %s",
                item["knowledge_key"]
            )

    results["total"] = len(VROTEX_KNOWLEDGE)

    logger.info(
        "Knowledge seeding completed: %s",
        results
    )

    return results


if __name__ == "__main__":
    print(seed_knowledge())
