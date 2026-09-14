#!/usr/bin/env python3
"""Default configuration for the Longbridge ETF portfolio backtest."""

# Portfolio. CLI --portfolio can replace this without editing code.
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
