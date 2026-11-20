# Vrotex Bot V1

Automated Smart Money Concepts (SMC) scalping system.

## Project Identity

- Name: Vrotex Bot V1
- Strategy: Scalping
- Broker: Exness
- Hosting: Render
- Repository: GitHub
- Initial operating mode: DEMO

## Approved Instruments

- EURUSD
- GBPUSD
- USDJPY
- EURJPY
- EURGBP
- BTCUSD

## Strategy Timeframes

H1 -> M5 -> M1

### H1 - Narrative

- Market structure (HH, HL, LH, LL)
- BOS and CHoCH
- Liquidity and inducement
- Order Blocks
- Fair Value Gaps
- Premium and Discount
- Fibonacci
- Strong and weak highs/lows
- Directional bias

### M5 - Confirmation

- Liquidity sweep
- External CHoCH
- Displacement
- FVG
- Full candle-body confirmation
- Protected range
- 50% retracement

### M1 - Execution Models

- CHoCH + FVG
- Sweep + Engulfing
- Breaker
- MSS + Sweep + Displacement
- Supply/Demand flip

## Setup Requirements

- Minimum setup score: 85/100
- Setups scoring below 85 are rejected.
- H1, M5 and M1 alignment must be evaluated.
- Liquidity and opposing targets must be identified.
- Spread must be checked before execution.
- Risk must be calculated before any order.

## Risk Management

- Risk per trade: Maximum 1%
- Maximum daily trades: 5
- Maximum consecutive losses: 2
- Daily loss limit: 2%
- Demo mode by default
- Real trading disabled until explicitly authorized

## Market Data Timeframes

- D1
- H4
- H1
- M30
- M15
- M5
- M1

H4 is data-only and is not part of the V1 strategy narrative.

## Deployment

Hosted on Render.

The bot starts using:

    python main.py

Dependencies are installed using:

    pip install -r requirements.txt

## Security

Never upload:

- .env files
- API keys
- Private keys
- Account credentials
- Database files
- Backups

Credentials must be configured privately in Render Environment Variables.

## Project Rule

Vrotex Bot V1 remains a scalping bot.

No strategy changes, renaming, upgrades, or additional instruments
without explicit owner approval.
