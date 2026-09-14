#!/usr/bin/env python3
"""Default configuration for the Longbridge ETF portfolio backtest."""

# Portfolio. CLI --portfolio can replace this without editing code.
DEFAULT_PORTFOLIO = "515450.SH:0.80,513130.SH:0.20"

# Strategy cadence
MONTHLY_CONTRIBUTION = 5000.0
REBALANCE_MONTHS = 3
START_DATE = "2020-01-01"
PRICE_ADJUST = "actual"

# Trading costs
COMMISSION = 0.000087
MIN_COMMISSION = 0.1
