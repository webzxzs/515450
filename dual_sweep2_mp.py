#!/usr/bin/env python3
"""
双标的参数深探 Round 2 — 多进程加速版
===========================================
"""

import sys
import re
import time
import os
import itertools
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import dual_backtest as db

TOTAL_BUDGET = 5000.0
N_SIMS       = 1
SEED         = 42

OUTPUT_CSV = "dual_sweep2_full.csv"
OUTPUT_TXT = "dual_sweep2_best.txt"

# ════════════════════════════════════════════════════════
# 从第一轮结果文件读取最优参数（test修改）
# ════════════════════════════════════════════════════════

def load_best_from_txt(path="dual_sweep_best.txt"):
    """解析 dual_sweep_best.txt 中的全局最优参数。返回 dict 或 None。"""
    try:
        txt = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

    params = {}
    m = re.search(r"515450 月投: (\d+)元\s+恒科月投: (\d+)元", txt)
    if m:
        params["hldb_monthly"] = float(m.group(1))
        params["hst_monthly"]  = float(m.group(2))

    m = re.search(r"HLDB 网格: G1_SELL=(\S+)%\s+G2_SELL=(\S+)%", txt)
    if m:
        params["hldb_g1_sell"] = float(m.group(1)) / 100
        params["hldb_g2_sell"] = float(m.group(2)) / 100

    # 新版 G1_BUY / G2_BUY
    m = re.search(r"HST\s+网格:.*?G1_BUY=(\S+)%.*?G2_BUY=(\S+)%.*?G1_SELL=(\S+)%.*?G2_SELL=(\S+)%.*?SHARES=(\d+)", txt)
    if m:
        params["hst_g1_buy"]  = float(m.group(1)) / 100
        params["hst_g2_buy"]  = float(m.group(2)) / 100
        params["hst_g1_sell"] = float(m.group(3)) / 100
        params["hst_g2_sell"] = float(m.group(4)) / 100
        params["hst_shares"]  = int(m.group(5))
    else:
        m = re.search(r"HST\s+网格: BUY=(\S+)%.*?G1_SELL=(\S+)%.*?G2_SELL=(\S+)%.*?SHARES=(\d+)", txt)
        if m:
            buy = float(m.group(1)) / 100
            params["hst_g1_buy"]  = buy
            params["hst_g2_buy"]  = buy
            params["hst_g1_sell"] = float(m.group(2)) / 100
            params["hst_g2_sell"] = float(m.group(3)) / 100
            params["hst_shares"]  = int(m.group(4))

    if len(params) >= 9:
        return params
    return None


# ════════════════════════════════════════════════════════
# 参数网格定义
# ════════════════════════════════════════════════════════

_HLDB_BUY_BASE = [0.005, 0.01, 0.015, 0.02, 0.03]
HLDB_BUY_PAIRS = [(g1, g2) for g1 in _HLDB_BUY_BASE for g2 in _HLDB_BUY_BASE if g2 >= g1]

HLDB_SHARES_GRID = [600, 700, 800, 900, 1000, 1200]

_HST_BUY_BASE = [0.02, 0.025, 0.03, 0.04, 0.05, 0.06, 0.08]
HST_BUY_PAIRS = [(g1, g2) for g1 in _HST_BUY_BASE for g2 in _HST_BUY_BASE if g2 >= g1]

HST_SELL_PAIRS = [
    (0.15, 0.30), (0.15, 0.40), (0.15, 0.50),
    (0.20, 0.30), (0.20, 0.40), (0.20, 0.50),
    (0.25, 0.30), (0.25, 0.40), (0.25, 0.50),
    (0.30, 0.40), (0.30, 0.50),
]

HST_SHARES_GRID = [100, 200, 300]
BUDGET_GRID = list(range(2000, 4801, 200))


# ════════════════════════════════════════════════════════
# 单次回测（可在多进程中调用）
# ════════════════════════════════════════════════════════

def patch_and_run(
    merged_df,
    hldb_monthly, hst_monthly,
    hldb_g1_buy, hldb_g2_buy,
    hldb_g1_sell, hldb_g2_sell,
    hldb_shares,
    hst_g1_buy, hst_g2_buy,
    hst_g1_sell, hst_g2_sell,
    hst_shares,
    seed=SEED,
):
    db.HLDB_MONTHLY   = float(hldb_monthly)
    db.HST_MONTHLY    = float(hst_monthly)
    db.MONTHLY_BUDGET = float(hldb_monthly) + float(hst_monthly)

    db.HLDB_G1_BUY  = float(hldb_g1_buy)
    db.HLDB_G2_BUY  = float(hldb_g2_buy)
    db.HLDB_G1_SELL = float(hldb_g1_sell)
    db.HLDB_G2_SELL = float(hldb_g2_sell)
    db.HLDB_G1_SH   = int(hldb_shares)
    db.HLDB_G2_SH   = int(hldb_shares)

    db.HST_G1_BUY  = float(hst_g1_buy)
    db.HST_G2_BUY  = float(hst_g2_buy)
    db.HST_G1_SELL = float(hst_g1_sell)
    db.HST_G2_SELL = float(hst_g2_sell)
    db.HST_G1_SH   = int(hst_shares)
    db.HST_G2_SH   = int(hst_shares)

    db.N_SIMS = N_SIMS

    try:
        rng = np.random.default_rng(seed)
        bt  = db.DualGridBacktester()
        rec_df, _ = bt.run(merged_df, rng)

        if len(rec_df) < 30:
            return None

        vals = rec_df["total_val"].values
        invs = rec_df["total_inv"].values
        sharpe = db.calc_sharpe(vals, invs)
        maxdd  = db.calc_maxdd(vals, invs)
        days   = (rec_df["date"].iloc[-1] - rec_df["date"].iloc[0]).days
        pnl    = float(vals[-1]) - float(invs[-1])
        ann    = db.calc_ann(pnl, float(invs[-1]), days)
        cfs    = list(bt.cashflows)
        cfs.append((rec_df["date"].iloc[-1], float(vals[-1])))
        xirr   = db.calc_xirr(cfs)

        return dict(
            sharpe        = round(sharpe, 4),
            xirr          = round(xirr * 100, 3) if xirr and np.isfinite(xirr) else np.nan,
            ann           = round(ann * 100, 3),
            maxdd         = round(maxdd * 100, 3),
            hldb_monthly  = hldb_monthly,
            hst_monthly   = hst_monthly,
            hldb_g1_buy   = hldb_g1_buy,
            hldb_g2_buy   = hldb_g2_buy,
            hldb_g1_sell  = hldb_g1_sell,
            hldb_g2_sell  = hldb_g2_sell,
            hldb_shares   = hldb_shares,
            hst_g1_buy    = hst_g1_buy,
            hst_g2_buy    = hst_g2_buy,
            hst_g1_sell   = hst_g1_sell,
            hst_g2_sell   = hst_g2_sell,
            hst_shares    = hst_shares,
        )
    except Exception as e:
        print(f"ERROR in patch_and_run: {e}")
        traceback.print_exc()
        return None


# ════════════════════════════════════════════════════════
# 多进程扫描阶段
# ════════════════════════════════════════════════════════

def stage_a_hldb_buy_mp(merged_df, p0, max_workers=4):
    """阶段 A: HLDB 买入对 × 股数 扫描 (多进程)"""
    print("\n━━━ 阶段 A: HLDB 买入对 × 股数 扫描 (多进程) ━━━")
    combos = list(itertools.product(HLDB_BUY_PAIRS, HLDB_SHARES_GRID))
    print(f"  共 {len(combos)} 组  (买入对: {len(HLDB_BUY_PAIRS)} 种  股数: {len(HLDB_SHARES_GRID)} 种)")
    print(f"  使用 {max_workers} 个进程并行计算")
    
    results = []
    completed = 0
    t0 = time.time()
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for (hb1, hb2) in HLDB_BUY_PAIRS:
            for hsh in HLDB_SHARES_GRID:
                future = executor.submit(
                    patch_and_run,
                    merged_df,
                    p0["hldb_monthly"], p0["hst_monthly"],
                    hb1, hb2, p0["hldb_g1_sell"], p0["hldb_g2_sell"], hsh,
                    p0["hst_g1_buy"], p0["hst_g2_buy"],
                    p0["hst_g1_sell"], p0["hst_g2_sell"], p0["hst_shares"],
                )
                futures[future] = (hb1, hb2, hsh)
        
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)
            completed += 1
            if completed % 10 == 0 or completed == len(combos):
                elapsed = time.time() - t0
                eta = elapsed / completed * (len(combos) - completed) if completed > 0 else 0
                print(f"  [{completed}/{len(combos)}] elapsed={elapsed:.1f}s  eta={eta:.1f}s", end="\r")
    
    print()
    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    best = df.iloc[0]
    print(f"  ▶ 最优 HLDB买入: g1_buy={best.hldb_g1_buy:.3f}  g2_buy={best.hldb_g2_buy:.3f}"
          f"  shares={best.hldb_shares:.0f}"
          f"  Sharpe={best.sharpe:.4f}  Ann={best.ann:+.2f}%  MaxDD={best.maxdd:.2f}%")
    return df, best


def stage_b_hst_reverify_mp(merged_df, bestA, max_workers=4):
    """阶段 B: HST 全参数重扫（多进程）"""
    print("\n━━━ 阶段 B: HST 全参数重扫（多进程验证交互效应）━━━")
    combos = list(itertools.product(HST_BUY_PAIRS, HST_SELL_PAIRS, HST_SHARES_GRID))
    print(f"  共 {len(combos)} 组")
    print(f"  使用 {max_workers} 个进程并行计算")
    
    results = []
    completed = 0
    t0 = time.time()
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for hb1, hb2 in HST_BUY_PAIRS:
            for hs1, hs2 in HST_SELL_PAIRS:
                for hssh in HST_SHARES_GRID:
                    future = executor.submit(
                        patch_and_run,
                        merged_df,
                        bestA.hldb_monthly, bestA.hst_monthly,
                        bestA.hldb_g1_buy, bestA.hldb_g2_buy,
                        bestA.hldb_g1_sell, bestA.hldb_g2_sell, int(bestA.hldb_shares),
                        hb1, hb2, hs1, hs2, hssh,
                    )
                    futures[future] = (hb1, hb2, hs1, hs2, hssh)
        
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)
            completed += 1
            if completed % 20 == 0 or completed == len(combos):
                elapsed = time.time() - t0
                eta = elapsed / completed * (len(combos) - completed) if completed > 0 else 0
                print(f"  [{completed}/{len(combos)}] elapsed={elapsed:.1f}s  eta={eta:.1f}s", end="\r")
    
    print()
    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    best = df.iloc[0]
    print(f"  ▶ 最优 HST: g1_buy={best.hst_g1_buy:.3f}  g2_buy={best.hst_g2_buy:.3f}"
          f"  g1_sell={best.hst_g1_sell:.2f}  g2_sell={best.hst_g2_sell:.2f}"
          f"  shares={best.hst_shares:.0f}"
          f"  Sharpe={best.sharpe:.4f}  Ann={best.ann:+.2f}%  MaxDD={best.maxdd:.2f}%")
    return df, best


def stage_c_budget_fine(merged_df, bestB):
    """阶段 C: 细粒度预算扫描 (单线程，数据少)"""
    print("\n━━━ 阶段 C: 细粒度预算扫描 (200元步长) ━━━")
    print(f"  共 {len(BUDGET_GRID)} 组  预算范围 {BUDGET_GRID[0]}~{BUDGET_GRID[-1]}")
    results = []
    for hldb_m in BUDGET_GRID:
        hst_m = TOTAL_BUDGET - hldb_m
        if hst_m <= 0:
            continue
        r = patch_and_run(
            merged_df,
            hldb_m, hst_m,
            bestB.hldb_g1_buy, bestB.hldb_g2_buy,
            bestB.hldb_g1_sell, bestB.hldb_g2_sell, int(bestB.hldb_shares),
            bestB.hst_g1_buy, bestB.hst_g2_buy,
            bestB.hst_g1_sell, bestB.hst_g2_sell, int(bestB.hst_shares),
        )
        if r:
            results.append(r)
    df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    best = df.iloc[0]
    print(f"  ▶ 最优预算: 515450={best.hldb_monthly:.0f}  恒科={best.hst_monthly:.0f}"
          f"  Sharpe={best.sharpe:.4f}  Ann={best.ann:+.2f}%  MaxDD={best.maxdd:.2f}%")
    return df, best


# ════════════════════════════════════════════════════════
# 主程序
# ════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("双标的参数深探 Round 2 — 多进程加速版")
    print("=" * 60)

    # 自动检测 CPU 核心数
    cpu_count = os.cpu_count() or 1
    MAX_WORKERS = max(cpu_count - 1, 1)  # 留出一个核给系统
    print(f"\n[系统信息] CPU 核心数: {cpu_count}, 进程数设置: {MAX_WORKERS}\n")

    p0 = load_best_from_txt("dual_sweep_best.txt")
    if p0:
        print("\n[读取第一轮最优参数]")
        print(f"  HLDB 月投={p0['hldb_monthly']:.0f}  HST 月投={p0['hst_monthly']:.0f}")
        print(f"  HLDB sell: G1={p0['hldb_g1_sell']:.2f}  G2={p0['hldb_g2_sell']:.2f}")
        print(f"  HST  buy:  G1={p0['hst_g1_buy']:.3f}  G2={p0['hst_g2_buy']:.3f}")
        print(f"  HST  sell: G1={p0['hst_g1_sell']:.2f}  G2={p0['hst_g2_sell']:.2f}  SH={p0['hst_shares']}")
    else:
        print("\n[未找到 dual_sweep_best.txt，使用已知最优值]")
        p0 = dict(
            hldb_monthly=4500, hst_monthly=500,
            hldb_g1_sell=0.15, hldb_g2_sell=0.50,
            hst_g1_buy=0.05,  hst_g2_buy=0.05,
            hst_g1_sell=0.15, hst_g2_sell=0.40,
            hst_shares=100,
        )

    print("\n[数据加载]")
    hldb_df   = db.load_with_index_extension(db.HLDB_CSV, db.HLDB_INDEX_CSV, "515450(HLDB)")
    hst_df    = db.load_with_index_extension(db.HST_CSV,  db.HST_INDEX_CSV,  "513130(HST)")
    merged_df = db.build_aligned(hldb_df, hst_df)
    print(f"  对齐后区间: {merged_df['date'].iloc[0].date()} ~ {merged_df['date'].iloc[-1].date()}, {len(merged_df)} 天")

    # 多进程数（自动检测 CPU 核心数）
    cpu_count = os.cpu_count() or 1
    MAX_WORKERS = max(cpu_count - 1, 1)  # 留出一个核给系统
    print(f"[CPU 多核加速] 检测到 {cpu_count} 核心，将使用 {MAX_WORKERS} 个进程")
    
    dfA, bestA = stage_a_hldb_buy_mp(merged_df, p0, max_workers=MAX_WORKERS)
    dfB, bestB = stage_b_hst_reverify_mp(merged_df, bestA, max_workers=MAX_WORKERS)
    dfC, bestC = stage_c_budget_fine(merged_df, bestB)

    # 合并输出
    all_df = pd.concat([dfA, dfB, dfC], ignore_index=True)
    all_df = all_df.drop_duplicates().sort_values("sharpe", ascending=False)
    all_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n全部 {len(all_df)} 组结果已保存到: {OUTPUT_CSV}")

    top20 = all_df.head(20)
    lines = [
        "=" * 96,
        "双标的参数深探 Round 2  Top-20 (按夏普率排序)",
        "=" * 96,
        f"{'#':>3}  {'Sharpe':>7}  {'Ann%':>7}  {'XIRR%':>7}  {'MaxDD%':>7}  "
        f"{'HLDB_M':>7}  {'HST_M':>6}  "
        f"{'HB1':>5}  {'HB2':>5}  {'H-G1S':>6}  {'H-G2S':>6}  {'HSH':>4}  "
        f"{'TB1':>5}  {'TB2':>5}  {'T-G1S':>6}  {'T-G2S':>6}  {'TSH':>4}",
        "-" * 96,
    ]
    for rank, (_, row) in enumerate(top20.iterrows(), 1):
        lines.append(
            f"{rank:>3}  {row.sharpe:>7.4f}  {row.ann:>+7.2f}  "
            f"{row.xirr:>7.2f}  {row.maxdd:>7.2f}  "
            f"{row.hldb_monthly:>7.0f}  {row.hst_monthly:>6.0f}  "
            f"{row.hldb_g1_buy:>5.3f}  {row.hldb_g2_buy:>5.3f}  "
            f"{row.hldb_g1_sell:>6.2f}  {row.hldb_g2_sell:>6.2f}  {int(row.hldb_shares):>4}  "
            f"{row.hst_g1_buy:>5.3f}  {row.hst_g2_buy:>5.3f}  "
            f"{row.hst_g1_sell:>6.2f}  {row.hst_g2_sell:>6.2f}  {int(row.hst_shares):>4}"
        )
    lines += [
        "-" * 96,
        "",
        "★ 全局最优参数 (Round 2 多进程):",
        f"  515450 月投: {bestC.hldb_monthly:.0f}元   恒科月投: {bestC.hst_monthly:.0f}元",
        f"  HLDB 网格: G1_BUY={bestC.hldb_g1_buy:.1%}  G2_BUY={bestC.hldb_g2_buy:.1%}"
        f"  G1_SELL={bestC.hldb_g1_sell:.0%}  G2_SELL={bestC.hldb_g2_sell:.0%}  SHARES={int(bestC.hldb_shares)}",
        f"  HST  网格: G1_BUY={bestC.hst_g1_buy:.1%}  G2_BUY={bestC.hst_g2_buy:.1%}"
        f"  G1_SELL={bestC.hst_g1_sell:.0%}  G2_SELL={bestC.hst_g2_sell:.0%}  SHARES={int(bestC.hst_shares)}",
        f"  Sharpe={bestC.sharpe:.4f}  Ann={bestC.ann:+.2f}%  XIRR={bestC.xirr:.2f}%  MaxDD={bestC.maxdd:.2f}%",
    ]
    report = "\n".join(lines)
    print()
    print(report)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"\n汇总已保存到: {OUTPUT_TXT}")


if __name__ == "__main__":
    main()
