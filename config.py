#!/usr/bin/env python3
"""Default configuration for the Longbridge ETF portfolio backtest."""

# Baseline portfolio for quick runs only. 25/25/25/25 is NOT a recommended or
# assumed optimum; weight_sweep.py / policy_sweep.py are responsible for
# discovering robust allocations from the configured ETF universe.
DEFAULT_PORTFOLIO = "513180.SH:0.25,515450.SH:0.25,513300.SH:0.25,159783.SZ:0.25"

# Strategy cadence
MONTHLY_CONTRIBUTION = 5000.0
REBALANCE_MONTHS = 3
START_DATE = "2020-01-01"

# Price basis
# Longbridge documents forward adjustment as accounting for splits/dividends.
# The project therefore defaults to forward-adjusted prices for long-horizon
# return research. Use `--adjust actual` when you want an unadjusted execution-
# price sensitivity check for lot sizing / fees / raw market-price behavior.
PRICE_ADJUST = "forward"

# Trading costs
COMMISSION = 0.000087
MIN_COMMISSION = 0.1
