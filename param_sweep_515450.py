#!/usr/bin/env python3
"""
515450 网格参数扫描
- 使用日收盘价（不做日内布朗桥模拟），速度快约100倍
- 保留完整费率模型 + DCA暂停逻辑 + XIRR
- 扫描: G1/G2 的 买入触发%, 卖出触发%, 每格手数, 月定投额
- 输出: single_sweep_results.csv + 热力图 single_sweep_heatmap.png
"""

import os
import itertools
from collections import deque

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

import config as cfg

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = cfg.OUTPUT_DIR

# ═══════════════════════ 固定费率 ═══════════════════════
COMMISSION    = cfg.COMMISSION
MIN_COMM      = cfg.MIN_COMMISSION
BUY_FEE_RATE  = cfg.BUY_FEE_RATE
REDEEM_FEE    = cfg.REDEEM_FEE_LT7D
HOLD_DAYS_THR = cfg.REDEEM_FEE_HOLD_DAYS

# ═══════════════════════ 扫描空间 ═══════════════════════
# G1: 频繁小波段网格
G1_BUY_LIST  = [0.01, 0.02, 0.03, 0.05]          # 买入跌幅触发
G1_SELL_LIST = [0.08, 0.10, 0.12, 0.15, 0.20]    # 卖出涨幅目标
G1_SH_LIST   = [300, 600, 900]                    # 每格手数

# G2: 大波段网格
G2_BUY_LIST  = [0.01, 0.02, 0.03, 0.05]
G2_SELL_LIST = [0.15, 0.20, 0.25, 0.30, 0.40]
G2_SH_LIST   = [300, 600, 900]

# 月定投额
MONTHLY_LIST = [3000, 4000, 5000, 6000]

# 约束条件（过滤无效组合）
def is_valid(g1b, g1s, g2b, g2s):
    return (g2s > g1s              # G2 目标利润必须 > G1
            and g1b <= g2b         # G2 买入宽度 >= G1（G2更宽松或相同）
            and g1s < 0.30)        # G1 卖出不要超过30%（防止永远不触发）


# ═══════════════════════ 工具函数 ═══════════════════════
def _comm(amount):
    return max(abs(amount) * COMMISSION, MIN_COMM)


def _buy_fee(amount):
    return abs(amount) * BUY_FEE_RATE


def _redeem_fee(lots_dq, price, shares, date):
    fee, remain = 0.0, int(shares)
    while remain > 0 and lots_dq:
        lot_date, lot_sh = lots_dq[0]
        use_sh = min(remain, lot_sh)
        if (date - lot_date).days < HOLD_DAYS_THR:
            fee += price * use_sh * REDEEM_FEE
        lot_sh -= use_sh
        remain -= use_sh
        if lot_sh <= 0:
            lots_dq.popleft()
        else:
            lots_dq[0] = (lot_date, lot_sh)
    return fee


def calc_xirr(cashflows, guess=0.1):
    cfs = [(pd.Timestamp(d), float(v)) for d, v in cashflows
           if np.isfinite(v) and abs(v) > 1e-12]
    if len(cfs) < 2:
        return np.nan
    if not any(v > 0 for _, v in cfs) or not any(v < 0 for _, v in cfs):
        return np.nan
    t0 = min(d for d, _ in cfs)
    yrs = np.array([(d - t0).days / 365.25 for d, _ in cfs])
    amts = np.array([v for _, v in cfs])

    def npv(r):
        return np.sum(amts / (1.0 + r) ** yrs) if r > -0.9999 else np.inf

    def dnpv(r):
        return np.sum(-yrs * amts / (1.0 + r) ** (yrs + 1)) if r > -0.9999 else np.inf

    r = guess
    for _ in range(50):
        f, df = npv(r), dnpv(r)
        if not np.isfinite(f) or abs(df) < 1e-12:
            break
        nr = r - f / df
        if abs(nr - r) < 1e-10:
            return float(nr)
        r = nr
    lo, hi = -0.95, 5.0
    flo, fhi = npv(lo), npv(hi)
    if np.sign(flo) == np.sign(fhi):
        return np.nan
    for _ in range(100):
        mid = (lo + hi) / 2.0
        fm = npv(mid)
        if abs(fm) < 1e-9:
            return float(mid)
        if np.sign(fm) == np.sign(flo):
            lo, flo = mid, fm
        else:
            hi, fhi = mid, fm
    return float((lo + hi) / 2.0)


# ═══════════════════════ 快速回测 (日收盘) ═══════════════════════
def fast_backtest(df, g1b, g1s, g1sh, g2b, g2s, g2sh, monthly):
    """
    在日收盘价序列上运行网格+DCA回测。
    不使用布朗桥日内模拟，大幅提升扫描速度。
    返回: dict(xirr, ann, sharpe, max_dd, n_trades, n_buy, n_sell, final_mv, invested)
    """
    pos = 0
    cash = 0.0
    g1_ref = g2_ref = None
    lots = deque()
    cashflows = []
    port_vals, invest_vals = [], []

    month_net = 0.0
    month_grid = 0
    prev_month = None

    def do_buy(price, shares, date, is_grid):
        nonlocal pos, cash, month_net, month_grid
        if shares <= 0:
            return 0
        amt = price * shares
        total = amt + _comm(amt) + _buy_fee(amt)
        pos += shares
        cash -= total
        month_net += total
        lots.append((date, int(shares)))
        cashflows.append((date, -total))
        if is_grid:
            month_grid += 1
        return 1

    n_trades = n_buy = n_sell = 0

    def do_sell(price, shares, date):
        nonlocal pos, cash, month_net, month_grid
        shares = min(shares, pos)
        if shares <= 0:
            return 0
        amt = price * shares
        net = amt - _comm(amt) - _redeem_fee(lots, price, shares, date)
        pos -= shares
        cash += net
        month_net -= net
        cashflows.append((date, net))
        month_grid += 1
        return 1

    dates = df["date"].values
    closes = df["close"].values

    for i, (date_np, close) in enumerate(zip(dates, closes)):
        date = pd.Timestamp(date_np)
        mkey = date.strftime("%Y-%m")

        # 月末换月: 结算上月
        if prev_month is not None and mkey != prev_month:
            # DCA: 月末补足缺口（无论网格是否触发）
            deficit = monthly - month_net
            if deficit > 0 and close > 0:
                sh = max(int(deficit / close / 100) * 100, 100)
                if deficit >= close * 100:
                    n_buy += do_buy(close, sh, date, is_grid=False)
            month_net = 0.0
            month_grid = 0

        prev_month = mkey

        # 初始化参考价
        if g1_ref is None:
            g1_ref = close
        if g2_ref is None:
            g2_ref = close

        # G1 网格触发
        ref = g1_ref
        while True:
            pct = (close - ref) / ref
            if pct <= -g1b:
                trig = ref * (1 - g1b)
                n_buy += do_buy(trig, g1sh, date, is_grid=True)
                ref = trig
            elif pct >= g1s and pos >= g1sh:
                trig = ref * (1 + g1s)
                n_sell += do_sell(trig, g1sh, date)
                ref = trig
            else:
                break
        g1_ref = ref

        # G2 网格触发
        ref = g2_ref
        while True:
            pct = (close - ref) / ref
            if pct <= -g2b:
                trig = ref * (1 - g2b)
                n_buy += do_buy(trig, g2sh, date, is_grid=True)
                ref = trig
            elif pct >= g2s and pos >= g2sh:
                trig = ref * (1 + g2s)
                n_sell += do_sell(trig, g2sh, date)
                ref = trig
            else:
                break
        g2_ref = ref

        port_v = pos * close
        inv_v = max(-cash, 1.0)
        port_vals.append(port_v)
        invest_vals.append(inv_v)

    # 末月结算
    if prev_month and len(dates) > 0:
        close = float(closes[-1])
        deficit = monthly - month_net
        if deficit > 0 and close > 0:
            sh = max(int(deficit / close / 100) * 100, 100)
            if deficit >= close * 100:
                n_buy += do_buy(close, sh, pd.Timestamp(dates[-1]), is_grid=False)
        port_vals[-1] = pos * close
        invest_vals[-1] = max(-cash, 1.0)

    n_trades = n_buy + n_sell

    if len(port_vals) < 10:
        return None

    pv = np.array(port_vals, float)
    iv = np.array(invest_vals, float)
    days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
    yrs = max(days / 365.25, 0.01)

    invested = iv[-1]
    final_mv = pos * float(closes[-1])
    pnl = final_mv - invested
    ann = (1 + pnl / max(invested, 1)) ** (1 / yrs) - 1

    # 夏普
    ratio = pd.Series(pv / iv)
    dr = ratio.pct_change().dropna()
    dr = dr[np.isfinite(dr)]
    sharpe = dr.mean() / max(dr.std(), 1e-9) * np.sqrt(242) if len(dr) > 30 else 0.0

    # 最大回撤
    peak = np.maximum.accumulate(pv / iv)
    dd = np.where(peak > 0, (pv / iv - peak) / peak, 0.0)
    max_dd = float(np.nanmin(np.clip(dd, -1, 0)))

    # XIRR
    xirr = calc_xirr(cashflows + [(pd.Timestamp(dates[-1]), final_mv)])

    return dict(
        xirr=xirr, ann=ann, sharpe=sharpe, max_dd=max_dd,
        n_trades=n_trades, n_buy=n_buy, n_sell=n_sell,
        final_mv=final_mv, invested=invested,
    )


# ═══════════════════════ 主程序 ═══════════════════════
def main():
    csv_path = os.path.join(OUTPUT_DIR, "index_data_hfq.csv")
    print(f"加载后复权数据: {csv_path}")
    raw = pd.read_csv(csv_path)
    raw = raw.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                               "最高": "high", "最低": "low"})
    raw.columns = [c.lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw["date"])
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
    raw["open"]  = pd.to_numeric(raw["open"],  errors="coerce")
    raw = raw.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    print(f"数据: {raw['date'].iloc[0].date()} ~ {raw['date'].iloc[-1].date()}, {len(raw)} 天")

    # DCA 基准 (月5000元)
    dca_xirr = _dca_benchmark(raw, 5000)
    print(f"\nDCA 基准 (月5000元): XIRR {dca_xirr*100:+.2f}%\n")

    # 构建参数组合
    combos = []
    for g1b, g1s, g1sh, g2b, g2s, g2sh, monthly in itertools.product(
        G1_BUY_LIST, G1_SELL_LIST, G1_SH_LIST,
        G2_BUY_LIST, G2_SELL_LIST, G2_SH_LIST,
        MONTHLY_LIST
    ):
        if is_valid(g1b, g1s, g2b, g2s):
            combos.append((g1b, g1s, g1sh, g2b, g2s, g2sh, monthly))

    total = len(combos)
    print(f"有效参数组合: {total} 个, 开始扫描...")

    results = []
    for idx, (g1b, g1s, g1sh, g2b, g2s, g2sh, monthly) in enumerate(combos):
        if (idx + 1) % 500 == 0:
            print(f"  进度: {idx+1}/{total}")
        r = fast_backtest(raw, g1b, g1s, g1sh, g2b, g2s, g2sh, monthly)
        if r is None:
            continue
        results.append(dict(
            g1_buy=g1b, g1_sell=g1s, g1_sh=g1sh,
            g2_buy=g2b, g2_sell=g2s, g2_sh=g2sh,
            monthly=monthly,
            xirr=round(r["xirr"] * 100, 3) if np.isfinite(r["xirr"]) else np.nan,
            ann=round(r["ann"] * 100, 3),
            sharpe=round(r["sharpe"], 4),
            max_dd=round(r["max_dd"] * 100, 2),
            n_trades=r["n_trades"],
            n_buy=r["n_buy"],
            n_sell=r["n_sell"],
            final_mv=round(r["final_mv"], 0),
            invested=round(r["invested"], 0),
            xirr_vs_dca=round((r["xirr"] - dca_xirr) * 100, 3) if np.isfinite(r["xirr"]) else np.nan,
        ))

    df_res = pd.DataFrame(results).dropna(subset=["xirr"])
    df_res = df_res.sort_values("xirr", ascending=False).reset_index(drop=True)

    out_csv = os.path.join(OUTPUT_DIR, "single_sweep_results.csv")
    df_res.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n扫描完成, 结果已保存: {out_csv}")
    print(f"有效结果: {len(df_res)} 条\n")

    # ── 打印 Top 20 ────────────────────────────────────
    print(f"{'='*95}")
    print(f"  Top 20 参数组合 (按 XIRR 排序)")
    print(f"{'='*95}")
    cols = ["g1_buy","g1_sell","g1_sh","g2_buy","g2_sell","g2_sh","monthly",
            "xirr","ann","sharpe","max_dd","n_trades","xirr_vs_dca"]
    hdr = f"{'排名':>4}  {'G1买%':>5} {'G1卖%':>5} {'G1手':>4}  {'G2买%':>5} {'G2卖%':>5} {'G2手':>4}  " \
          f"{'月投':>5}  {'XIRR%':>7} {'年化%':>6} {'夏普':>5} {'回撤%':>7} {'交易次':>5} {'超DCA%':>7}"
    print(hdr)
    print("-" * 95)
    for i, row in df_res.head(20).iterrows():
        print(f"  {i+1:3d}  {row.g1_buy*100:>4.0f}% {row.g1_sell*100:>4.0f}% {row.g1_sh:>4.0f}  "
              f"{row.g2_buy*100:>4.0f}% {row.g2_sell*100:>4.0f}% {row.g2_sh:>4.0f}  "
              f"{row.monthly:>5.0f}  "
              f"{row.xirr:>+7.2f} {row.ann:>+6.2f} {row.sharpe:>5.2f} "
              f"{row.max_dd:>+7.2f} {row.n_trades:>5.0f} {row.xirr_vs_dca:>+7.2f}")
    print("=" * 95)

    # ── 当前默认参数的排名 ────────────────────────────────
    default_mask = (
        (df_res["g1_buy"] == cfg.GRID1_BUY_PCT) &
        (df_res["g1_sell"] == cfg.GRID1_SELL_PCT) &
        (df_res["g1_sh"] == cfg.GRID1_SHARES) &
        (df_res["g2_buy"] == cfg.GRID2_BUY_PCT) &
        (df_res["g2_sell"] == cfg.GRID2_SELL_PCT) &
        (df_res["g2_sh"] == cfg.GRID2_SHARES) &
        (df_res["monthly"] == cfg.MONTHLY_TARGET)
    )
    default_rows = df_res[default_mask]
    if not default_rows.empty:
        dr = default_rows.iloc[0]
        rank = default_rows.index[0] + 1
        print(f"\n当前默认参数排名: #{rank} / {len(df_res)}")
        print(f"  G1买={dr.g1_buy*100:.0f}%  G1卖={dr.g1_sell*100:.0f}%  G1手={dr.g1_sh:.0f}")
        print(f"  G2买={dr.g2_buy*100:.0f}%  G2卖={dr.g2_sell*100:.0f}%  G2手={dr.g2_sh:.0f}")
        print(f"  月投={dr.monthly:.0f}  XIRR={dr.xirr:+.2f}%  超DCA={dr.xirr_vs_dca:+.2f}%")

    # ── 热力图: G1卖出% × G2卖出% (最优XIRR) ─────────────
    _plot_heatmaps(df_res, dca_xirr)

    # ── 输出最优参数组合建议 ───────────────────────────────
    best = df_res.iloc[0]
    print(f"\n★ 推荐参数组合 (XIRR最高):")
    print(f"  G1买入触发: -{best.g1_buy*100:.0f}%  G1卖出目标: +{best.g1_sell*100:.0f}%  G1每格: {best.g1_sh:.0f}手")
    print(f"  G2买入触发: -{best.g2_buy*100:.0f}%  G2卖出目标: +{best.g2_sell*100:.0f}%  G2每格: {best.g2_sh:.0f}手")
    print(f"  月定投额:   {best.monthly:.0f}元")
    print(f"  XIRR: {best.xirr:+.2f}%  年化: {best.ann:+.2f}%  夏普: {best.sharpe:.2f}  "
          f"最大回撤: {best.max_dd:.2f}%  交易次数: {best.n_trades:.0f}")
    print(f"  vs DCA 超额XIRR: {best.xirr_vs_dca:+.2f}%")

    # Top 5 by Sharpe (XIRR > DCA)
    top_sharpe = df_res[df_res["xirr_vs_dca"] > 0].nlargest(5, "sharpe")
    if not top_sharpe.empty:
        print(f"\n★ 夏普最高前5 (XIRR须超DCA):")
        for i, row in top_sharpe.iterrows():
            print(f"  G1:{row.g1_buy*100:.0f}%/{row.g1_sell*100:.0f}%/{row.g1_sh:.0f}手  "
                  f"G2:{row.g2_buy*100:.0f}%/{row.g2_sell*100:.0f}%/{row.g2_sh:.0f}手  "
                  f"月{row.monthly:.0f}  XIRR{row.xirr:+.2f}%  夏普{row.sharpe:.2f}  回撤{row.max_dd:.2f}%")


def _dca_benchmark(df, monthly):
    """纯定投基准XIRR。"""
    pos, cash_out, prev_m = 0, 0.0, None
    cfs = []
    for idx, row in df.iterrows():
        mkey = row["date"].strftime("%Y-%m")
        if prev_m is not None and mkey != prev_m:
            pc = float(df.iloc[idx - 1]["close"])
            sh = max(int(monthly / pc / 100) * 100, 100)
            amt = sh * pc
            fee = max(abs(amt) * COMMISSION, MIN_COMM) + abs(amt) * BUY_FEE_RATE
            pos += sh; cash_out += amt + fee
            cfs.append((df.iloc[idx - 1]["date"], -(amt + fee)))
        prev_m = mkey
    if prev_m:
        lc = float(df.iloc[-1]["close"])
        sh = max(int(monthly / lc / 100) * 100, 100)
        amt = sh * lc
        fee = max(abs(amt) * COMMISSION, MIN_COMM) + abs(amt) * BUY_FEE_RATE
        pos += sh; cash_out += amt + fee
        cfs.append((df.iloc[-1]["date"], -(amt + fee)))
    cfs.append((df.iloc[-1]["date"], pos * float(df.iloc[-1]["close"])))
    return calc_xirr(cfs)


def _plot_heatmaps(df_res, dca_xirr):
    """生成 G1卖%×G2卖% 热力图（取该格内最优XIRR）。"""
    g1s_vals = sorted(df_res["g1_sell"].unique())
    g2s_vals = sorted(df_res["g2_sell"].unique())

    mat_xirr   = np.full((len(g2s_vals), len(g1s_vals)), np.nan)
    mat_sharpe = np.full((len(g2s_vals), len(g1s_vals)), np.nan)

    for i, g2s in enumerate(g2s_vals):
        for j, g1s in enumerate(g1s_vals):
            sub = df_res[(df_res["g1_sell"] == g1s) & (df_res["g2_sell"] == g2s)]
            if not sub.empty:
                mat_xirr[i, j]   = sub["xirr"].max()
                mat_sharpe[i, j] = sub["sharpe"].max()

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("515450 参数扫描热力图 (各格取最优值)", fontsize=13, fontweight="bold")

    for ax, mat, title, cmap in [
        (axes[0], mat_xirr,   "最优XIRR% (按G1卖出% × G2卖出%)", "YlOrRd"),
        (axes[1], mat_sharpe, "最优夏普率 (按G1卖出% × G2卖出%)", "YlGnBu"),
    ]:
        im = ax.imshow(mat, cmap=cmap, aspect="auto", origin="lower")
        ax.set_xticks(range(len(g1s_vals)))
        ax.set_xticklabels([f"{v*100:.0f}%" for v in g1s_vals])
        ax.set_yticks(range(len(g2s_vals)))
        ax.set_yticklabels([f"{v*100:.0f}%" for v in g2s_vals])
        ax.set_xlabel("G1卖出触发%")
        ax.set_ylabel("G2卖出触发%")
        ax.set_title(title)
        plt.colorbar(im, ax=ax)
        # 标注数值
        for i in range(len(g2s_vals)):
            for j in range(len(g1s_vals)):
                if not np.isnan(mat[i, j]):
                    ax.text(j, i, f"{mat[i,j]:.2f}", ha="center", va="center",
                            fontsize=7, color="black")

    plt.tight_layout()
    out_png = os.path.join(OUTPUT_DIR, "single_sweep_heatmap.png")
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n热力图已保存: {out_png}")


if __name__ == "__main__":
    main()
