#!/usr/bin/env python3
"""项目配置: 统一管理标的、费用和回测参数。"""

import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 标的数据源
SYMBOL = "515450"
LOCAL_CSV_BY_SYMBOL = {
    "515450": "index_data_hfq.csv",  # 后复权数据 (akshare hfq)
    "513130": "etf_513130.csv",
}
LOCAL_CSV = os.path.join(OUTPUT_DIR, LOCAL_CSV_BY_SYMBOL.get(SYMBOL, "index_data.csv"))
PRICE_ADJUST_MODE = "hfq"
CONTRIBUTION_DAY = 1

# 网格参数 (最优夏普组合: 扫描7920组, Sharpe=0.48, XIRR=+10.28%, 最大回撤=-19.74%)
GRID1_BUY_PCT = 0.01
GRID1_SELL_PCT = 0.20
GRID1_SHARES = 900

GRID2_BUY_PCT = 0.01
GRID2_SELL_PCT = 0.40
GRID2_SHARES = 900

# 资金参数
MONTHLY_TARGET = 3000

# 交易成本
COMMISSION = 0.000087
MIN_COMMISSION = 0.1
BUY_FEE_RATE = 0.0012
SELL_FEE_RATE = 0.0
REDEEM_FEE_LT7D = 0.005
REDEEM_FEE_HOLD_DAYS = 7

# 蒙特卡洛参数
STEPS_PER_SEG = 60
N_SIMS = 10
NOISE_RATIO = 0.25
REACH_MIN = 0.70
REACH_MAX = 1.00
