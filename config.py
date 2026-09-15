#!/usr/bin/env python3
"""Default configuration for the Longbridge ETF portfolio backtest."""

# Baseline portfolio for quick runs only. Equal weight is NOT a recommended or
# assumed optimum; weight_sweep.py / policy_sweep.py are responsible for
# discovering robust allocations from the configured ETF universe.
#
# 518850.SH = 华夏黄金ETF. Gold is included as a distinct defensive / real-asset
# sleeve; its long-term target weight must be discovered by the research layer.
DEFAULT_PORTFOLIO = (
    "513180.SH:0.20,515450.SH:0.20,513300.SH:0.20,159783.SZ:0.20,518850.SH:0.20"
)

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
