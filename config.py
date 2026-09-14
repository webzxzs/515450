#!/usr/bin/env python3
"""Shared strategy/runtime configuration for the Longbridge-backed project."""

import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Trading costs
COMMISSION = 0.000087
MIN_COMMISSION = 0.1
BUY_FEE_RATE = 0.0012
SELL_FEE_RATE = 0.0
REDEEM_FEE_LT7D = 0.005
REDEEM_FEE_HOLD_DAYS = 7

# Intraday Monte Carlo synthesis
STEPS_PER_SEG = 60
N_SIMS = 10
NOISE_RATIO = 0.25
REACH_MIN = 0.70
REACH_MAX = 1.00
