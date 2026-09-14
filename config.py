#!/usr/bin/env python3
"""Default configuration for the Longbridge ETF portfolio backtest."""

# Portfolio. CLI --portfolio can replace this without editing code.
DEFAULT_PORTFOLIO = "513180.SH:0.25,515450.SH:0.25,513300.SH:0.25,159783.SZ:0.25"

# Strategy cadence
MONTHLY_CONTRIBUTION = 5000.0
REBALANCE_MONTHS = 3
START_DATE = "2020-01-01"

# Price basis
# Research/optimization should compare total-return-like histories, so the
# shared research default is Longbridge forward-adjusted prices. Longbridge
# documents forward adjustment as accounting for splits/dividends.
PRICE_ADJUST = "forward"
# The executable ledger uses unadjusted market prices so lot sizing, fees, and
# cash affordability are not calculated from synthetic adjusted prices.
EXECUTION_PRICE_ADJUST = "actual"

# Trading costs
COMMISSION = 0.000087
MIN_COMMISSION = 0.1
