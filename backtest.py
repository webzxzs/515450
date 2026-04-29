#!/usr/bin/env python3
"""
515450 红利低波ETF 网格交易回测

策略: 双网格 + 月度定投, 布朗桥蒙特卡洛日内模拟
"""

import akshare as ak
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import warnings, os
import argparse
from collections import deque

import config as cfg
from iwencai_etf_selector import IwencaiETFError, select_top_etf

warnings.filterwarnings("ignore")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = cfg.OUTPUT_DIR

# ═══════════════════════ 参数配置 ═══════════════════════
SYMBOL = cfg.SYMBOL
GRID1_BUY_PCT = cfg.GRID1_BUY_PCT; GRID1_SELL_PCT = cfg.GRID1_SELL_PCT; GRID1_SHARES = cfg.GRID1_SHARES
GRID2_BUY_PCT = cfg.GRID2_BUY_PCT; GRID2_SELL_PCT = cfg.GRID2_SELL_PCT; GRID2_SHARES = cfg.GRID2_SHARES
MONTHLY_TARGET = cfg.MONTHLY_TARGET
COMMISSION = cfg.COMMISSION; MIN_COMMISSION = cfg.MIN_COMMISSION
BUY_FEE_RATE = cfg.BUY_FEE_RATE; SELL_FEE_RATE = cfg.SELL_FEE_RATE
REDEEM_FEE_LT7D = cfg.REDEEM_FEE_LT7D; REDEEM_FEE_HOLD_DAYS = cfg.REDEEM_FEE_HOLD_DAYS
STEPS_PER_SEG = cfg.STEPS_PER_SEG; N_SIMS = cfg.N_SIMS
NOISE_RATIO = cfg.NOISE_RATIO; REACH_MIN = cfg.REACH_MIN; REACH_MAX = cfg.REACH_MAX
LOCAL_CSV = cfg.LOCAL_CSV
PRICE_ADJUST_MODE = cfg.PRICE_ADJUST_MODE


# ═══════════════════════ 通用工具 ═══════════════════════
def calc_metrics(port_values, invested_series, days):
    """从日市值序列和累计投入序列计算 ann_ret, sharpe, max_dd"""
    pv  = np.asarray(port_values, dtype=float)
    inv = np.asarray(invested_series, dtype=float)
    inv = np.clip(inv, 1, None)

    net_inv = inv[-1]
    fv      = pv[-1]
    pnl     = fv - net_inv
    years   = max(days / 365.25, 0.01)
    ann_ret = (1 + pnl / max(net_inv, 1)) ** (1 / years) - 1 if net_inv > 0 else 0.0

    # 夏普 (年化 √242)  ── 用 市值/投入 比值的日变化，排除资金流入噪声
    ratio_s = pd.Series(pv / inv)
    dr = ratio_s.pct_change().dropna()
    dr = dr[np.isfinite(dr)]
    sharpe = dr.mean() / max(dr.std(), 1e-9) * np.sqrt(242) if len(dr) > 30 else 0.0

    # 最大回撤 (市值/投入 比值)
    ratio = pv / inv
    peak  = np.maximum.accumulate(ratio)
    with np.errstate(divide='ignore', invalid='ignore'):
        dd = np.where(peak > 0, (ratio - peak) / peak, 0.0)
    dd = np.clip(dd, -1, 0)
    max_dd = float(np.nanmin(dd))

    return dict(pnl=pnl, ann_ret=ann_ret, sharpe=sharpe, max_dd=max_dd, years=years)


def calc_xirr(cashflows, guess=0.1):
    """用不规则现金流计算 XIRR。cashflows: [(pd.Timestamp, amount), ...]"""
    cfs = [(pd.Timestamp(d), float(v)) for d, v in cashflows if np.isfinite(v) and abs(v) > 1e-12]
    if len(cfs) < 2:
        return np.nan
    if not any(v > 0 for _, v in cfs) or not any(v < 0 for _, v in cfs):
        return np.nan

    t0 = min(d for d, _ in cfs)
    years = np.array([(d - t0).days / 365.25 for d, _ in cfs], dtype=float)
    amts = np.array([v for _, v in cfs], dtype=float)

    def npv(rate):
        if rate <= -0.999999:
            return np.inf
        return np.sum(amts / np.power(1.0 + rate, years))

    def d_npv(rate):
        if rate <= -0.999999:
            return np.inf
        return np.sum(-years * amts / np.power(1.0 + rate, years + 1.0))

    r = guess
    for _ in range(50):
        f, df = npv(r), d_npv(r)
        if not np.isfinite(f) or not np.isfinite(df) or abs(df) < 1e-12:
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


# ═══════════════════════ 数据获取 ═══════════════════════
def fetch_daily_data(symbol=None, local_csv=None):
    COL_MAP = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
        "Date": "date", "Open": "open", "Close": "close",
        "High": "high", "Low": "low", "Volume": "volume", "Amount": "amount",
    }
    symbol = symbol or SYMBOL
    local_csv = local_csv or LOCAL_CSV

    if os.path.exists(local_csv):
        print(f"从本地文件加载数据: {local_csv}")
        df = pd.read_csv(local_csv)
        df = df.rename(columns={k: v for k, v in COL_MAP.items() if k in df.columns})
        df.columns = [c.lower() for c in df.columns]
        expected = cfg.LOCAL_CSV_BY_SYMBOL.get(symbol)
        if expected and os.path.basename(local_csv) != expected:
            raise ValueError(f"SYMBOL={symbol} 与数据文件不匹配: 当前 {os.path.basename(local_csv)} 应为 {expected}")
    else:
        print(f"正在从 akshare 获取 {symbol} 日线数据 ...")
        try:
            df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust=PRICE_ADJUST_MODE)
        except Exception:
            # 部分ETF不支持指定复权模式时回退 qfq，避免流程中断。
            df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
        df = df.rename(columns=COL_MAP)

    # 若存在后复权列/因子，统一到复权口径（close×factor）。
    if "adj_close" in df.columns and "close" in df.columns:
        base_close = pd.to_numeric(df["close"], errors="coerce")
        adj_close = pd.to_numeric(df["adj_close"], errors="coerce")
        ratio = (adj_close / base_close).replace([np.inf, -np.inf], np.nan)
        for c in ["open", "high", "low", "close"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce") * ratio
    elif "adj_factor" in df.columns:
        fac = pd.to_numeric(df["adj_factor"], errors="coerce")
        for c in ["open", "high", "low", "close"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce") * fac
    else:
        if PRICE_ADJUST_MODE == "hfq":
            print("提示: 已使用后复权数据（hfq），价格列已包含分红再投资。")
        else:
            print("提示: 数据未提供 adj_close/adj_factor，当前按原始价格列回测。")

    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low"]:
        df[c] = df[c].astype(float)
    df = df.sort_values("date").reset_index(drop=True)
    print(f"数据范围: {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}, 共 {len(df)} 天")
    return df


# ═══════════════════════ 布朗桥日内合成 ═══════════════════════
def _brownian_bridge(start, end, n, sigma, rng):
    t = np.linspace(0, 1, n + 1)
    linear = start + t * (end - start)
    walk = np.concatenate([[0], np.cumsum(rng.normal(0, sigma / np.sqrt(n), n))])
    return linear + walk - t * walk[-1]


def synthesize_intraday(row, rng):
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    n = STEPS_PER_SEG
    mid = (h + l) / 2.0
    reach = rng.uniform(REACH_MIN, REACH_MAX)
    h_eff = mid + (h - mid) * reach
    l_eff = mid - (mid - l) * reach

    if rng.random() < (0.6 if c >= o else 0.4):
        wp = [o, l_eff, h_eff, c]
    else:
        wp = [o, h_eff, l_eff, c]

    sigma = max(h - l, 1e-6) * NOISE_RATIO
    segs = [_brownian_bridge(wp[i], wp[i+1], n, sigma, rng)[:-1 if i < 2 else n+1]
            for i in range(3)]
    return np.clip(np.concatenate(segs), l, h)


# ═══════════════════════ 纯定投基准 ═══════════════════════
def compute_dca_benchmark(df):
    pos, cash_out, prev_m = 0, 0.0, None
    d_dates, d_vals, d_inv = [], [], []
    cashflows = []

    for idx, row in df.iterrows():
        mkey = row["date"].strftime("%Y-%m")
        if prev_m is not None and mkey != prev_m:
            pc = df.iloc[idx - 1]["close"]
            sh = max(int(MONTHLY_TARGET / pc / 100) * 100, 100)
            amt = sh * pc
            fee = max(abs(amt) * COMMISSION, MIN_COMMISSION) + abs(amt) * BUY_FEE_RATE
            pos += sh; cash_out += amt + fee
            cashflows.append((df.iloc[idx - 1]["date"], -(amt + fee)))
        prev_m = mkey
        d_dates.append(row["date"])
        d_vals.append(pos * row["close"])
        d_inv.append(cash_out)

    # 末月买入
    if prev_m:
        lc = df.iloc[-1]["close"]
        sh = max(int(MONTHLY_TARGET / lc / 100) * 100, 100)
        amt = sh * lc
        fee = max(abs(amt) * COMMISSION, MIN_COMMISSION) + abs(amt) * BUY_FEE_RATE
        pos += sh; cash_out += amt + fee
        cashflows.append((df.iloc[-1]["date"], -(amt + fee)))
        d_vals[-1] = pos * lc; d_inv[-1] = cash_out

    days = (df.iloc[-1]["date"] - df.iloc[0]["date"]).days
    m = calc_metrics(d_vals, d_inv, days)
    cashflows.append((df.iloc[-1]["date"], pos * df.iloc[-1]["close"]))
    m["xirr"] = calc_xirr(cashflows)
    return dict(
        net_invested=cash_out, final_value=pos * df.iloc[-1]["close"],
        position=pos, **m,
        daily_values=pd.Series(d_vals, index=d_dates),
    )


# ═══════════════════════ 网格交易引擎 ═══════════════════════
class GridTrader:
    def __init__(self):
        self.position = 0
        self.cash = 0.0
        self.grid1_ref = self.grid2_ref = None
        self.max_pos_cap = 0
        self.month_count = 1
        self.month_net = 0.0
        self.month_grid_trades = 0
        self.trades, self.daily_records, self.monthly_records = [], [], []
        self.cashflows = []
        self._lots = deque()

    @staticmethod
    def _comm(amount):
        return max(abs(amount) * COMMISSION, MIN_COMMISSION)

    @staticmethod
    def _buy_fee(amount):
        return abs(amount) * BUY_FEE_RATE

    @staticmethod
    def _sell_fee(amount):
        return abs(amount) * SELL_FEE_RATE

    def _redeem_fee(self, price, shares, date):
        if shares <= 0:
            return 0.0
        fee = 0.0
        remain = int(shares)
        while remain > 0 and self._lots:
            lot_date, lot_sh = self._lots[0]
            use_sh = min(remain, lot_sh)
            hold_days = (pd.Timestamp(date) - pd.Timestamp(lot_date)).days
            if hold_days < REDEEM_FEE_HOLD_DAYS:
                fee += price * use_sh * REDEEM_FEE_LT7D
            lot_sh -= use_sh
            remain -= use_sh
            if lot_sh <= 0:
                self._lots.popleft()
            else:
                self._lots[0] = (lot_date, lot_sh)
        return fee

    def _buy(self, price, shares, grid, date):
        if shares <= 0: return
        amt = price * shares
        total = amt + self._comm(amt) + self._buy_fee(amt)
        self.position += shares; self.cash -= total; self.month_net += total
        self._lots.append((pd.Timestamp(date), int(shares)))
        self.cashflows.append((pd.Timestamp(date), -total))
        if grid in {"G1", "G2"}:
            self.month_grid_trades += 1
        self.trades.append(dict(date=date, action="BUY", grid=grid,
                                price=round(price, 4), shares=shares,
                                cost=round(total, 2), position=self.position))

    def _sell(self, price, shares, grid, date):
        shares = min(shares, self.position)
        if shares <= 0: return
        amt = price * shares
        net = amt - self._comm(amt) - self._sell_fee(amt) - self._redeem_fee(price, shares, date)
        self.position -= shares; self.cash += net; self.month_net -= net
        self.cashflows.append((pd.Timestamp(date), net))
        if grid in {"G1", "G2"}:
            self.month_grid_trades += 1
        self.trades.append(dict(date=date, action="SELL", grid=grid,
                                price=round(price, 4), shares=shares,
                                cost=round(-net, 2), position=self.position))

    def _tick(self, price, date):
        if self.grid1_ref is None: self.grid1_ref = price
        if self.grid2_ref is None: self.grid2_ref = price
        for buy_pct, sell_pct, gs, ref_attr, label in [
            (GRID1_BUY_PCT, GRID1_SELL_PCT, GRID1_SHARES, "grid1_ref", "G1"),
            (GRID2_BUY_PCT, GRID2_SELL_PCT, GRID2_SHARES, "grid2_ref", "G2"),
        ]:
            ref = getattr(self, ref_attr)
            while True:
                pct = (price - ref) / ref
                if pct <= -buy_pct:
                    trig = ref * (1 - buy_pct)
                    self._buy(trig, gs, label, date)
                    ref = trig
                elif pct >= sell_pct and self.position >= gs:
                    trig = ref * (1 + sell_pct)
                    self._sell(trig, gs, label, date)
                    ref = trig
                else:
                    break
            setattr(self, ref_attr, ref)

    def _month_settle(self, price, date, mkey):
        deficit = MONTHLY_TARGET - self.month_net
        if deficit > 0:
            self._buy(price, max(100, round(deficit / price / 100) * 100), "月末补", date)
        self.max_pos_cap = max(self.max_pos_cap, self.position)
        self.month_count += 1
        self.monthly_records.append(dict(
            month=mkey, net_add=round(self.month_net, 2), position=self.position,
            max_cap=self.max_pos_cap, value=round(self.position * price, 2),
            price=round(price, 4), grid_trades=self.month_grid_trades,
            dca_paused=int(self.month_grid_trades > 0)))
        self.month_net = 0.0
        self.month_grid_trades = 0

    def run(self, df, rng=None, dca_bench=None, quiet=False):
        if rng is None: rng = np.random.default_rng(42)
        self._quiet = quiet
        prev_month = None
        for idx, row in df.iterrows():
            date, mkey = row["date"], row["date"].strftime("%Y-%m")
            if prev_month is not None and mkey != prev_month:
                pr = df.iloc[idx - 1]
                self._month_settle(pr["close"], pr["date"], prev_month)
            prev_month = mkey
            for p in synthesize_intraday(row, rng):
                self._tick(p, date)
            self.daily_records.append(dict(
                date=date, close=row["close"], position=self.position,
                port_value=round(self.position * row["close"], 2),
                cash=round(self.cash, 2),
                total_value=round(self.position * row["close"] + self.cash, 2),
                max_cap=self.max_pos_cap))
        if prev_month:
            last = df.iloc[-1]
            self._month_settle(last["close"], last["date"], prev_month)
        return self._report(dca_bench)

    def _report(self, dca_bench=None):
        quiet = getattr(self, '_quiet', False)
        tdf = pd.DataFrame(self.trades)
        ddf = pd.DataFrame(self.daily_records)
        mdf = pd.DataFrame(self.monthly_records)
        if len(ddf) == 0:
            print("无交易数据"); return tdf, ddf, mdf

        net_invested = -self.cash
        days = (ddf.iloc[-1]["date"] - ddf.iloc[0]["date"]).days
        invested = (-ddf["cash"]).clip(lower=1)
        m = calc_metrics(ddf["port_value"].values, invested.values, days)
        # XIRR 终值 = 剩余持仓按最后收盘价清算（不加cash，因buy/sell流已单独计入）
        final_mv = self.position * float(ddf.iloc[-1]["close"])
        m["xirr"] = calc_xirr(list(self.cashflows) + [(pd.Timestamp(ddf.iloc[-1]["date"]), final_mv)])

        # 回撤列 (绘图用)
        ratio = ddf["port_value"] / invested
        ddf["return_ratio"] = ratio
        ddf["return_peak"] = ratio.cummax()
        ddf["drawdown"] = ((ratio - ddf["return_peak"]) / ddf["return_peak"]).clip(lower=-1).fillna(0)

        # 打印报告
        def _p(*a, **kw):
            if not quiet: print(*a, **kw)

        fv = self.position * ddf.iloc[-1]["close"]
        _p(f"\n{'='*62}\n               回 测 结 果 汇 总\n{'='*62}")
        _p(f"  回测区间: {ddf.iloc[0]['date'].strftime('%Y-%m-%d')} → "
           f"{ddf.iloc[-1]['date'].strftime('%Y-%m-%d')}  ({days}天, {m['years']:.2f}年)")
        _p(f"  交易总次数:   {len(tdf)}")
        if len(tdf) > 0:
            _p(f"    买入: {(tdf['action']=='BUY').sum()}  |  卖出: {(tdf['action']=='SELL').sum()}")
        _p(f"  最终持仓:     {self.position:,} 股")
        _p(f"  最终市值:     {fv:,.2f} 元")
        _p(f"  累计净投入:   {net_invested:,.2f} 元")
        _p(f"  总盈亏:       {m['pnl']:,.2f} 元  ({m['pnl']/max(net_invested,1)*100:+.2f}%)")
        _p(f"  年化收益率:   {m['ann_ret']*100:+.2f}%")
        _p(f"  XIRR年化:     {m['xirr']*100:+.2f}%" if np.isfinite(m['xirr']) else "  XIRR年化:     N/A")
        _p(f"  夏普率:       {m['sharpe']:.2f}")
        _p(f"  最大回撤:     {m['max_dd']*100:.2f}%")
        _p(f"  最大持仓上限: {self.max_pos_cap:,} 股")
        if len(mdf) > 0:
            _p(f"  月均净加仓:   {mdf['net_add'].mean():,.0f} 元  "
               f"(标准差 {mdf['net_add'].std():,.0f})")
        _p("-" * 62)

        if len(tdf) > 0:
            for g in tdf["grid"].unique():
                gt = tdf[tdf["grid"] == g]
                _p(f"  [{g}]  买{(gt['action']=='BUY').sum()}次 / "
                   f"卖{(gt['action']=='SELL').sum()}次  净投入 {gt['cost'].sum():,.2f} 元")

        if dca_bench:
            da, ds, dd = dca_bench["ann_ret"], dca_bench["sharpe"], dca_bench["max_dd"]
            _p(f"{'-'*62}\n  ★ 策略 vs 纯定投对比:")
            _p(f"    纯定投累计投入:   {dca_bench['net_invested']:,.2f} 元")
            _p(f"    纯定投最终市值:   {dca_bench['final_value']:,.2f} 元")
            _p(f"    纯定投年化收益:   {da*100:+.2f}%")
            if np.isfinite(dca_bench.get("xirr", np.nan)):
                _p(f"    纯定投XIRR年化:   {dca_bench['xirr']*100:+.2f}%")
            _p(f"    纯定投夏普率:     {ds:.2f}")
            _p(f"    纯定投最大回撤:   {dd*100:.2f}%")
            _p(f"    网格策略年化收益: {m['ann_ret']*100:+.2f}%")
            if np.isfinite(m.get("xirr", np.nan)):
                _p(f"    网格策略XIRR年化: {m['xirr']*100:+.2f}%")
            _p(f"    网格策略夏普率:   {m['sharpe']:.2f}")
            _p(f"    网格策略最大回撤: {m['max_dd']*100:.2f}%")
            _p(f"    网格额外年化:     {(m['ann_ret']-da)*100:+.2f}%")
        _p("=" * 62)

        # attrs 供绘图/Excel使用
        ddf.attrs.update(net_invested=net_invested, final_value=fv, **m)
        if dca_bench:
            ddf.attrs.update(dca_ann_ret=dca_bench["ann_ret"], dca_sharpe=dca_bench["sharpe"],
                             dca_max_dd=dca_bench["max_dd"], dca_xirr=dca_bench.get("xirr", np.nan), dca_invested=dca_bench["net_invested"],
                             dca_final=dca_bench["final_value"])
        return tdf, ddf, mdf


# ═══════════════════════ 可视化 ═══════════════════════
def plot_all(tdf, ddf, mdf, price_df, all_ddf=None, dca_bench=None):
    # ---- 主图 (4子图) ----
    fig, axes = plt.subplots(4, 1, figsize=(18, 22))
    fig.suptitle(f"515450 红利低波ETF 网格回测 (蒙特卡洛 {N_SIMS}次)", fontsize=17, fontweight="bold")

    ax = axes[0]
    ax.plot(price_df["date"], price_df["close"], "k-", lw=0.8, label="收盘价")
    if len(tdf) > 0:
        for action, color, marker, label in [
            ("BUY", "red", "^", "买入"), ("SELL", "green", "v", "卖出")]:
            sub = tdf[tdf["action"] == action]
            ax.scatter(sub["date"], sub["price"], c=color, marker=marker,
                       s=12, alpha=0.5, label=f"{label} ({len(sub)})")
    ax.set_title("价格走势 & 交易点位"); ax.set_ylabel("价格 (元)")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    ax = axes[1]
    if all_ddf and len(all_ddf) > 1:
        dates = ddf["date"].values
        all_ret = []
        for d in all_ddf:
            inv_s = (-d["cash"]).clip(lower=1).values
            all_ret.append((d["total_value"].values / inv_s - 1.0) * 100)
        all_tv = np.array(all_ret)
        for lo, hi, a in [(10, 90, 0.12), (25, 75, 0.2)]:
            ax.fill_between(dates, np.percentile(all_tv, lo, axis=0),
                            np.percentile(all_tv, hi, axis=0),
                            alpha=a, color="blue", label=f"P{lo}~P{hi}")
    inv = (-ddf["cash"]).clip(lower=1)
    strat_ret = (ddf["total_value"] / inv - 1.0) * 100
    ax.plot(ddf["date"], strat_ret, "b-", lw=1, label="策略收益率")
    if dca_bench and "daily_values" in dca_bench:
        dca_s = dca_bench["daily_values"]
        dca_base = max(dca_bench.get("net_invested", 1), 1)
        dca_ret = (dca_s / dca_base - 1.0) * 100
        ax.plot(dca_s.index, dca_ret.values, color="gray", ls="-.", lw=1, alpha=0.8, label="纯定投收益率")
    ax.set_title("收益率对比 (含MC区间)"); ax.set_ylabel("收益率 (%)")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    ax = axes[2]
    ax.fill_between(ddf["date"], ddf["drawdown"] * 100, 0, color="red", alpha=0.35)
    ax.plot(ddf["date"], ddf["drawdown"] * 100, "r-", lw=0.7)
    ax.set_title("回撤曲线"); ax.set_ylabel("回撤 (%)"); ax.grid(True, alpha=0.3)

    ax = axes[3]
    ax.plot(ddf["date"], ddf["position"], color="purple", lw=1, label="持仓量")
    ax.plot(ddf["date"], ddf["max_cap"], color="orange", lw=1, ls="--", label="持仓上限")
    ax.set_title("持仓变化"); ax.set_ylabel("股数"); ax.set_xlabel("日期")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    _save_fig(fig, "single_backtest_results.png", "主图")

    # ---- 月度图 ----
    if len(mdf) > 0:
        fig2, (ax5, ax6) = plt.subplots(2, 1, figsize=(16, 10))
        fig2.suptitle("515450 红利低波ETF 月度分析", fontsize=14, fontweight="bold")
        step = max(1, len(mdf) // 20)
        colors = ["green" if abs(v - MONTHLY_TARGET) <= 1000 else "orange" for v in mdf["net_add"]]
        ax5.bar(range(len(mdf)), mdf["net_add"], color=colors, alpha=0.7)
        ax5.axhline(MONTHLY_TARGET, color="blue", ls="--", label=f"目标 {MONTHLY_TARGET} 元")
        ax5.set_title("月度净加仓金额"); ax5.set_ylabel("金额 (元)")
        ax5.set_xticks(range(0, len(mdf), step))
        ax5.set_xticklabels(mdf["month"].iloc[::step], rotation=45)
        ax5.legend(); ax5.grid(True, alpha=0.3)

        ax6.plot(range(len(mdf)), mdf["value"], "b-o", ms=3, label="月末市值")
        ax6.plot(range(len(mdf)), mdf["net_add"].cumsum(), "r--", lw=1, label="累计投入")
        ax6.set_title("月末市值 vs 累计投入"); ax6.set_ylabel("金额 (元)")
        ax6.set_xticks(range(0, len(mdf), step))
        ax6.set_xticklabels(mdf["month"].iloc[::step], rotation=45)
        ax6.legend(); ax6.grid(True, alpha=0.3)
        plt.tight_layout()
        _save_fig(fig2, "single_monthly_analysis.png", "月度图")

    # ---- 收益率分布 ----
    if len(ddf) > 30:
        fig3, ax7 = plt.subplots(figsize=(10, 5))
        inv = (-ddf["cash"]).clip(lower=1)
        dr = (ddf["total_value"].diff() / inv).dropna()
        dr = dr[np.isfinite(dr)].clip(-0.2, 0.2)
        ax7.hist(dr * 100, bins=80, color="steelblue", alpha=0.7, edgecolor="white")
        ax7.axvline(0, color="red", ls="--")
        ax7.set_title("日收益率分布"); ax7.set_xlabel("日收益率 (%)"); ax7.set_ylabel("频次")
        ax7.grid(True, alpha=0.3)
        _save_fig(fig3, "single_return_dist.png", "收益率分布")


def _save_fig(fig, name, label):
    p = os.path.join(OUTPUT_DIR, name)
    fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close(fig)
    print(f"{label}已保存: {p}")


# ═══════════════════════ 蒙特卡洛调度 ═══════════════════════
def run_monte_carlo(df):
    dca_bench = compute_dca_benchmark(df)
    print(f"纯定投基准: 投入{dca_bench['net_invested']:,.0f}元 → "
          f"市值{dca_bench['final_value']:,.0f}元  "
          f"年化{dca_bench['ann_ret']*100:+.2f}%  "
          f"XIRR{(dca_bench.get('xirr', np.nan)*100):+.2f}%  "
          f"夏普{dca_bench['sharpe']:.2f}  回撤{dca_bench['max_dd']*100:.1f}%")
    print(f"蒙特卡洛模拟: {N_SIMS} 次 × {len(df)} 交易日 ...")

    results, all_ddf = [], []
    for i in range(N_SIMS):
        trader = GridTrader()
        tdf, ddf, mdf = trader.run(df, np.random.default_rng(i * 137 + 42), quiet=True)
        a = ddf.attrs
        alpha = a["ann_ret"] * 100 - dca_bench["ann_ret"] * 100
        results.append(dict(
            sim=i, pnl=a["pnl"], pnl_pct=a["pnl"] / max(a["net_invested"], 1) * 100,
            ann_ret=a["ann_ret"] * 100, xirr=a.get("xirr", np.nan) * 100, sharpe=a["sharpe"], max_dd=a["max_dd"] * 100,
            n_trades=len(tdf), position=trader.position,
            net_invested=a["net_invested"], final_value=a["final_value"],
            grid_alpha=alpha))
        all_ddf.append(ddf)
        print(f"  #{i+1:2d}  盈亏={a['pnl']:+,.0f}  年化={a['ann_ret']*100:+.1f}%  XIRR={a.get('xirr', np.nan)*100:+.1f}%  "
              f"回撤={a['max_dd']*100:.1f}%  交易={len(tdf)}")

    rdf = pd.DataFrame(results)

    # MC 统计
    print(f"\n{'='*70}\n          蒙 特 卡 洛 统 计  ({N_SIMS}次模拟)\n{'='*70}")
    for col, label in [("pnl","总盈亏(元)"), ("pnl_pct","盈亏%"), ("ann_ret","年化%"),
                        ("sharpe","夏普率"), ("grid_alpha","网格额外年化%"),
                        ("max_dd","最大回撤%"), ("n_trades","交易次数")]:
        v = rdf[col]
        print(f"  {label:12s}  " + "  ".join(
            f"P{int(p*100)}={v.quantile(p):>+10.1f}" for p in [.1,.25,.5,.75,.9]))
    print("=" * 70)

    # 中位数详细展示
    mid_idx = (rdf["pnl"] - rdf["pnl"].median()).abs().idxmin()
    print(f"\n选取第 {mid_idx+1} 次模拟 (中位数) 做详细展示:")
    trader_m = GridTrader()
    tdf_m, ddf_m, mdf_m = trader_m.run(df, np.random.default_rng(mid_idx * 137 + 42),
                                         dca_bench=dca_bench)
    return rdf, tdf_m, ddf_m, mdf_m, all_ddf, dca_bench


# ═══════════════════════ Excel 报告导出 ═══════════════════════
def export_excel(rdf, tdf, ddf, mdf, dca_bench):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

    wb = Workbook()
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_fill = PatternFill("solid", fgColor="4472C4")
    hdr_font = Font(bold=True, size=12, color="FFFFFF")
    hdr_align = Alignment(horizontal="center", vertical="center")

    def _write_sheet(ws, headers, rows, col_widths=None):
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = hdr_font; cell.fill = hdr_fill
            cell.alignment = hdr_align; cell.border = border
        for r, row in enumerate(rows, 2):
            for c, val in enumerate(row, 1):
                cell = ws.cell(row=r, column=c, value=val)
                cell.border = border
        if col_widths:
            for letter, w in col_widths.items():
                ws.column_dimensions[letter].width = w

    # --- Sheet 1: 策略对比 ---
    a = ddf.attrs if hasattr(ddf, 'attrs') else {}
    g = {k: a.get(k, 0) for k in ["net_invested","final_value","pnl","ann_ret","xirr","sharpe","max_dd","years"]}
    d = {k: dca_bench.get(k, 0) for k in ["net_invested","final_value","ann_ret","xirr","sharpe","max_dd"]} if dca_bench else {}
    d["pnl"] = d.get("final_value", 0) - d.get("net_invested", 0)

    ws1 = wb.active; ws1.title = "策略对比"
    _write_sheet(ws1, ["指标", "网格+定投策略", "纯定投策略", "差值"], [
        ("回测年数",   f"{g['years']:.1f}",  f"{g['years']:.1f}",  ""),
        ("累计投入(元)", g["net_invested"],     d.get("net_invested",0), g["net_invested"]-d.get("net_invested",0)),
        ("最终市值(元)", g["final_value"],      d.get("final_value",0),  g["final_value"]-d.get("final_value",0)),
        ("总盈亏(元)",  g["pnl"],              d["pnl"],                g["pnl"]-d["pnl"]),
        ("盈亏比例",    g["pnl"]/max(g["net_invested"],1), d["pnl"]/max(d.get("net_invested",1),1), ""),
        ("年化收益率",  g["ann_ret"],           d.get("ann_ret",0),      g["ann_ret"]-d.get("ann_ret",0)),
        ("XIRR年化",    g["xirr"],              d.get("xirr",0),         g["xirr"]-d.get("xirr",0)),
        ("夏普率",      g["sharpe"],            d.get("sharpe",0),       g["sharpe"]-d.get("sharpe",0)),
        ("最大回撤",    g["max_dd"],            d.get("max_dd",0),       g["max_dd"]-d.get("max_dd",0)),
        ("交易次数",    len(tdf),               "",                      ""),
    ], {"A":16, "B":20, "C":20, "D":16})

    fmts = [(range(3,6), (2,3,4), '#,##0'), (range(6,7), (2,3), '0.00%'),
            (range(7,9), (2,3,4), '0.00%'), (range(9,10), (2,3,4), '#,##0.00'),
            (range(10,11), (2,3,4), '0.00%')]
    for rows_r, cols_c, fmt in fmts:
        for r in rows_r:
            for c in cols_c:
                ws1.cell(row=r, column=c).number_format = fmt

    # --- Sheet 2: 策略参数 ---
    ws2 = wb.create_sheet("策略参数")
    params = [
        ("SYMBOL", SYMBOL, "ETF代码"),
        ("GRID1_BUY_PCT", GRID1_BUY_PCT, "网格1买入阈值(跌幅)"),
        ("GRID1_SELL_PCT", GRID1_SELL_PCT, "网格1卖出阈值(涨幅)"),
        ("GRID1_SHARES", GRID1_SHARES, "网格1每次交易股数"),
        ("GRID2_BUY_PCT", GRID2_BUY_PCT, "网格2买入阈值(跌幅)"),
        ("GRID2_SELL_PCT", GRID2_SELL_PCT, "网格2卖出阈值(涨幅)"),
        ("GRID2_SHARES", GRID2_SHARES, "网格2每次交易股数"),
        ("MONTHLY_TARGET", MONTHLY_TARGET, "每月净加仓目标(元)"),
        ("COMMISSION", COMMISSION, "佣金率(万0.87)"),
        ("BUY_FEE_RATE", BUY_FEE_RATE, "申购费率"),
        ("SELL_FEE_RATE", SELL_FEE_RATE, "卖出费率"),
        ("REDEEM_FEE_LT7D", REDEEM_FEE_LT7D, "赎回费率(持有<7天)"),
        ("N_SIMS", N_SIMS, "蒙特卡洛模拟次数"),
        ("NOISE_RATIO", NOISE_RATIO, "布朗桥噪声强度"),
        ("REACH_MIN", REACH_MIN, "极值衰减下界"),
    ]
    _write_sheet(ws2, ["参数", "值", "说明"],
                 [(n, v, d) for n, v, d in params],
                 {"A":22, "B":14, "C":36})

    # --- Sheet 3: 蒙特卡洛统计 ---
    ws3 = wb.create_sheet("蒙特卡洛统计")
    mc_metrics = [("pnl","总盈亏(元)"), ("pnl_pct","盈亏%"), ("ann_ret","年化%"),
                  ("sharpe","夏普率"), ("grid_alpha","网格额外年化%"),
                  ("max_dd","最大回撤%"), ("n_trades","交易次数")]
    pcts = [0.10, 0.25, 0.50, 0.75, 0.90]
    mc_rows = []
    for col, label in mc_metrics:
        v = rdf[col]
        mc_rows.append((label,) + tuple(round(v.quantile(p), 2) for p in pcts) + (round(v.mean(), 2),))
    _write_sheet(ws3, ["指标","P10","P25","P50(中位)","P75","P90","均值"], mc_rows,
                 {chr(65+i): (18 if i==0 else 14) for i in range(7)})

    # --- Sheet 4: 月度明细 ---
    ws4 = wb.create_sheet("月度明细")
    mdf_out = mdf.copy()
    if "month" in mdf_out.columns:
        mdf_out["month"] = mdf_out["month"].astype(str)
    cols = list(mdf_out.columns)
    _write_sheet(ws4, cols,
                 [tuple(row) for row in mdf_out.itertuples(index=False)],
                 {chr(65+i): max(len(str(c))+4, 12) for i, c in enumerate(cols) if i < 26})
    if "month" in cols:
        cidx = cols.index("month") + 1
        for r in range(2, len(mdf_out) + 2):
            ws4.cell(row=r, column=cidx).number_format = "yyyy-mm-dd"

    path = os.path.join(OUTPUT_DIR, "single_backtest_report.xlsx")
    wb.save(path)
    print(f"\nExcel报告已保存: {path}")


# ═══════════════════════ 主程序 ═══════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="网格回测（支持同花顺问财ETF自动选标）")
    parser.add_argument("--auto-select-query", type=str, default="",
                        help="使用同花顺问财根据该问句自动选择ETF后回测")
    parser.add_argument("--selector-limit", type=str, default="20",
                        help="问财筛选每页返回条数")
    args = parser.parse_args()

    run_symbol = SYMBOL
    run_csv = LOCAL_CSV

    if args.auto_select_query.strip():
        try:
            picked = select_top_etf(args.auto_select_query.strip(), limit=args.selector_limit)
            run_symbol = picked["symbol"]
            run_csv = os.path.join(OUTPUT_DIR, cfg.LOCAL_CSV_BY_SYMBOL.get(run_symbol, f"etf_{run_symbol}.csv"))
            print(f"同花顺问财选标: {picked['name']} ({picked['code']})")
            print(f"使用问句: {picked['used_query']}  | 数据来源: {picked['source']}")
            print(f"TraceId: {picked['trace_id']}")
        except IwencaiETFError as e:
            print(f"问财选标失败，回退默认标的 {SYMBOL}: {e}")

    globals()["SYMBOL"] = run_symbol
    globals()["LOCAL_CSV"] = run_csv
    df = fetch_daily_data(symbol=run_symbol, local_csv=run_csv)
    print(f"共 {len(df)} 个交易日  "
          f"({df.iloc[0]['date'].strftime('%Y-%m-%d')} ~ "
          f"{df.iloc[-1]['date'].strftime('%Y-%m-%d')})")
    print(f"价格区间: {df['low'].min():.3f} ~ {df['high'].max():.3f}")

    rdf, tdf, ddf, mdf, all_ddf, dca_bench = run_monte_carlo(df)
    plot_all(tdf, ddf, mdf, df, all_ddf, dca_bench=dca_bench)
    export_excel(rdf, tdf, ddf, mdf, dca_bench)

    for name, frame in [("trades", tdf), ("daily", ddf), ("monthly", mdf), ("mc_summary", rdf)]:
        frame.to_csv(os.path.join(OUTPUT_DIR, f"{name}.csv"), index=False, encoding="utf-8-sig")
    print("\nCSV文件已保存: trades/daily/monthly/mc_summary.csv")
    print("回测完成!")
