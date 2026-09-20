#!/usr/bin/env python3
"""Default configuration for the Longbridge ETF portfolio backtest."""

# Current stored research allocation. It follows the latest completed
# explicit-dividend policy_sweep joint leader rather than preserving a prior
# hand-picked default. Re-run the research stack before changing it again as
# market history grows.
#
# 518850.SH = 华夏黄金ETF. Gold is included as a distinct defensive / real-asset
# sleeve; its long-term target weight must be discovered by the research layer.
DEFAULT_PORTFOLIO = (
    "513180.SH:0.10,515450.SH:0.15,513300.SH:0.35,159783.SZ:0.10,518850.SH:0.30"
)

# Default research bounds. Symbols omitted here fall back to the CLI/global
# min/max used by weight_sweep.py and policy_sweep.py. Gold is deliberately
# allowed to reach 0% so the research can test whether it is needed at all,
# rather than forcing a minimum allocation by construction.
WEIGHT_BOUNDS = {
    "518850.SH": (0.00, 0.30),
}

# Strategy cadence
MONTHLY_CONTRIBUTION = 5000.0
REBALANCE_MONTHS = 1
START_DATE = "2020-01-01"

# Price basis
# Long-horizon research defaults to Longbridge actual market prices plus the
# repo-maintained explicit ETF cash-dividend schedule. This avoids relying on
# Longbridge ForwardAdjust as a black-box total-return proxy.
# Use --adjust actual for raw-price execution sensitivity and
# --adjust forward only for Longbridge adjustment diagnostics.
PRICE_ADJUST = "total_return"

# Trading costs
COMMISSION = 0.000087
MIN_COMMISSION = 0.1
