#!/usr/bin/env python3
"""
双仓组合回测: 515450双网格 + 513130恒科双网格 (杠铃策略)

策略:
    - 515450: 双网格 + 月末补仓, 月预算 4000元 (稳健底仓)
    - 513130: 双网格 + 月末补仓, 月预算 1000元 (高弹性卫星仓)
    - 恒科参数更保守: 买入触发更深、每格更小, 优先控制回撤
  - 数据: 两只标的均使用后复权(hfq)价格, 布朗桥日内模拟

命令行示例:
    python dual_backtest.py --monthly-total 5000 --hldb-monthly 3800
    python dual_backtest.py --monthly-total 5000 --hldb-monthly 4000 --hst-buy-pct 0.03 --hst-shares 200
"""

import argparse
import os
from collections import deque

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import warnings

import config as cfg

warnings.filterwarnings("ignore")
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = cfg.OUTPUT_DIR

HLDB_MONTHLY   = 4500                         # 优化后: 4500 -> 515450
HST_MONTHLY    = 500                          # 优化后: 500  -> 513130
MONTHLY_BUDGET = HLDB_MONTHLY + HST_MONTHLY  # 5000 总月预算

COMMISSION_ETF     = cfg.COMMISSION
MIN_COMM           = cfg.MIN_COMMISSION
BUY_FEE_RATE       = cfg.BUY_FEE_RATE
SELL_FEE_RATE      = cfg.SELL_FEE_RATE
REDEEM_FEE_LT7D    = cfg.REDEEM_FEE_LT7D
REDEEM_FEE_HOLD_DAYS = cfg.REDEEM_FEE_HOLD_DAYS
STEPS_PER_SEG      = cfg.STEPS_PER_SEG
NOISE_RATIO        = cfg.NOISE_RATIO
REACH_MIN          = cfg.REACH_MIN
REACH_MAX          = cfg.REACH_MAX
N_SIMS             = cfg.N_SIMS

# 515450 网格参数 (Round 2 最优: G1_BUY=2%, G2_BUY=3%, G1_SELL=15%, G2_SELL=50%, SHARES=1200)
HLDB_G1_BUY  = 0.020
HLDB_G1_SELL = 0.15
HLDB_G1_SH   = 1200
HLDB_G2_BUY  = 0.030
HLDB_G2_SELL = 0.50
HLDB_G2_SH   = 1200

# 513130 网格参数 (Round 2 最优, 9:1预算下: 买入8%, G1卖出20%, G2卖出50%)
HST_G1_BUY  = 0.08
HST_G1_SELL = 0.20
HST_G1_SH   = 100
HST_G2_BUY  = 0.08
HST_G2_SELL = 0.50
HST_G2_SH   = 100

HLDB_CSV       = "index_data_hfq.csv"   # 515450 后复权
HST_CSV        = "hst_hfq.csv"          # 513130 后复权
HLDB_INDEX_CSV = "index_data.csv"        # 515450 底层指数 (用于向前拟合扩展)
HST_INDEX_CSV  = "index_hstech.csv"      # 513130 底层指数 (恒生科技, 用于向前拟合扩展)

COL_MAP = {
    "日期": "date", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
}


# ═══════════════════════ XIRR ═══════════════════════
def calc_xirr(cashflows, guess=0.1):
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
        f, df_ = npv(r), d_npv(r)
        if not np.isfinite(f) or not np.isfinite(df_) or abs(df_) < 1e-12:
            break
        nr = r - f / df_
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


# ═══════════════════════ 数据加载 ═══════════════════════
def load_hfq_csv(filename, label):
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label} 数据文件不存在: {path}")
    df = pd.read_csv(path)
    df = df.rename(columns={k: v for k, v in COL_MAP.items() if k in df.columns})
    df.columns = [c.lower() for c in df.columns]
    for col in ["date", "open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"{label} 缺少 {col} 列 (文件: {filename})")
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = (df.dropna(subset=["date", "open", "high", "low", "close"])
            .sort_values("date").reset_index(drop=True))
    print(f"  {label} (后复权): {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}, {len(df)} 天")
    return df


def load_with_index_extension(etf_csv, index_csv, etf_label, fit_window=120):
    """
    加载 ETF 后复权数据，并用底层指数的对数线性回归向前拟合扩展。

    策略:
      1. 取 ETF 与指数重叠区间的最近 fit_window 个交易日
      2. OLS: log(etf_close) = a + b * log(index_close)
      3. 对指数早于 ETF 上市的日期，合成 OHLC = exp(a + b * log(index_OHLC))
      4. 拼接在 ETF 数据前端
    """
    etf_df    = load_hfq_csv(etf_csv, etf_label)
    etf_start = etf_df["date"].min()

    idx_path = os.path.join(OUTPUT_DIR, index_csv)
    if not os.path.exists(idx_path):
        print(f"  [{etf_label}] 指数文件不存在 ({index_csv})，跳过拟合扩展")
        return etf_df

    idx_df = pd.read_csv(idx_path)
    idx_df["date"] = pd.to_datetime(idx_df["date"])
    for c in ["open", "high", "low", "close"]:
        idx_df[c] = pd.to_numeric(idx_df[c], errors="coerce")
    idx_df = (idx_df.dropna(subset=["date","open","high","low","close"])
                    .sort_values("date").reset_index(drop=True))

    pre_idx = idx_df[idx_df["date"] < etf_start].copy()
    if len(pre_idx) == 0:
        print(f"  [{etf_label}] 指数无更早数据，不做扩展")
        return etf_df

    # 用重叠区间末尾 fit_window 个交易日拟合
    overlap = pd.merge(
        etf_df[["date","close"]].rename(columns={"close":"etf_c"}),
        idx_df[["date","close"]].rename(columns={"close":"idx_c"}),
        on="date"
    ).tail(fit_window)

    if len(overlap) < 20:
        print(f"  [{etf_label}] 重叠区间不足20天，跳过拟合扩展")
        return etf_df

    # log-linear OLS: log(etf) = a + b * log(idx)
    x = np.log(overlap["idx_c"].values)
    y = np.log(overlap["etf_c"].values)
    b_coef, a_coef = np.polyfit(x, y, 1)  # y = a + b*x

    # 合成前置 OHLC
    synth = pre_idx[["date","open","high","low","close"]].copy()
    for col in ["open", "high", "low", "close"]:
        synth[col] = np.exp(a_coef + b_coef * np.log(synth[col].values.clip(1e-9)))

    n_ext = len(synth)
    print(f"  [{etf_label}] 指数拟合扩展: +{n_ext}天 "
          f"({synth['date'].min().date()} ~ {etf_start.date() - pd.Timedelta(days=1)}), "
          f"b={b_coef:.3f} a={a_coef:.4f}")

    cols   = ["date","open","high","low","close"]
    result = pd.concat([synth[cols], etf_df[cols]], ignore_index=True)
    return result.sort_values("date").reset_index(drop=True)


def align_ffill(df, prefix):
    """扩展为自然日序列, ffill 填充非交易日, 列名加前缀。"""
    out = df[["date", "open", "high", "low", "close"]].drop_duplicates("date").set_index("date")
    idx = pd.date_range(out.index.min(), out.index.max(), freq="D")
    out = out.reindex(idx).ffill().reset_index().rename(columns={"index": "date"})
    out = out.rename(columns={c: f"{prefix}_{c}" for c in ["open", "high", "low", "close"]})
    return out


def build_aligned(hldb_df, hst_df):
    a = align_ffill(hldb_df, "hldb")
    b = align_ffill(hst_df, "hst")
    m = pd.merge(a, b, on="date", how="inner").sort_values("date").reset_index(drop=True)
    return m


# ═══════════════════════ 布朗桥日内合成 (515450用) ═══════════════════════
def _brownian_bridge(start, end, n, sigma, rng):
    t = np.linspace(0, 1, n + 1)
    linear = start + t * (end - start)
    walk = np.concatenate([[0], np.cumsum(rng.normal(0, sigma / np.sqrt(n), n))])
    return linear + walk - t * walk[-1]


def synthesize_intraday(o, h, l, c, rng):
    n = STEPS_PER_SEG
    mid = (h + l) / 2.0
    reach = rng.uniform(REACH_MIN, REACH_MAX)
    h_eff = mid + (h - mid) * reach
    l_eff = mid - (mid - l) * reach
    wp = [o, l_eff, h_eff, c] if rng.random() < (0.6 if c >= o else 0.4) else [o, h_eff, l_eff, c]
    sigma = max(h - l, 1e-6) * NOISE_RATIO
    segs = [_brownian_bridge(wp[i], wp[i + 1], n, sigma, rng)[:-1 if i < 2 else n + 1] for i in range(3)]
    return np.clip(np.concatenate(segs), l, h)


# ═══════════════════════ 回测引擎 ═══════════════════════
class DualGridBacktester:
    """515450 双网格 + 513130 双网格, 独立运作"""

    def __init__(self):
        # ── 515450 状态 ──────────────────────────────────
        self.hldb_pos        = 0
        self.hldb_cash       = 0.0
        self.hldb_month_net  = 0.0
        self.hldb_month_grid = 0
        self.hldb_g1_ref     = None
        self.hldb_g2_ref     = None
        self.lots_hldb       = deque()
        # ── 513130 状态 ──────────────────────────────────
        self.hst_pos         = 0
        self.hst_cash        = 0.0
        self.hst_month_net   = 0.0
        self.hst_month_grid  = 0
        self.hst_g1_ref      = None
        self.hst_g2_ref      = None
        self.lots_hst        = deque()
        # ── 公共 ────────────────────────────────────────
        self.cashflows = []
        self.records   = []
        self.monthly   = []

    @staticmethod
    def _comm(amount):
        return max(abs(amount) * COMMISSION_ETF, MIN_COMM)

    @staticmethod
    def _buy_fee(amount):
        return abs(amount) * BUY_FEE_RATE

    def _redeem_fee(self, lots_dq, price, shares, date):
        if shares <= 0: return 0.0
        fee, remain = 0.0, int(shares)
        while remain > 0 and lots_dq:
            lot_date, lot_sh = lots_dq[0]
            use_sh = min(remain, lot_sh)
            if (pd.Timestamp(date) - pd.Timestamp(lot_date)).days < REDEEM_FEE_HOLD_DAYS:
                fee += price * use_sh * REDEEM_FEE_LT7D
            lot_sh -= use_sh; remain -= use_sh
            if lot_sh <= 0: lots_dq.popleft()
            else: lots_dq[0] = (lot_date, lot_sh)
        return fee

    # ── 515450 买卖 ──────────────────────────────────────
    def _buy_hldb(self, price, shares, date, is_grid=False):
        if shares <= 0: return
        amt   = price * shares
        total = amt + self._comm(amt) + self._buy_fee(amt)
        self.hldb_pos += shares; self.hldb_cash -= total
        self.hldb_month_net += total
        self.lots_hldb.append((pd.Timestamp(date), int(shares)))
        self.cashflows.append((pd.Timestamp(date), -total))
        if is_grid: self.hldb_month_grid += 1

    def _sell_hldb(self, price, shares, date):
        shares = min(shares, self.hldb_pos)
        if shares <= 0: return
        amt = price * shares
        net = amt - self._comm(amt) - self._redeem_fee(self.lots_hldb, price, shares, date)
        self.hldb_pos -= shares; self.hldb_cash += net
        self.hldb_month_net -= net
        self.cashflows.append((pd.Timestamp(date), net))
        self.hldb_month_grid += 1

    # ── 513130 买卖 ──────────────────────────────────────
    def _buy_hst(self, price, shares, date, is_grid=False):
        if shares <= 0: return
        amt   = price * shares
        total = amt + self._comm(amt) + self._buy_fee(amt)
        self.hst_pos += shares; self.hst_cash -= total
        self.hst_month_net += total
        self.lots_hst.append((pd.Timestamp(date), int(shares)))
        self.cashflows.append((pd.Timestamp(date), -total))
        if is_grid: self.hst_month_grid += 1

    def _sell_hst(self, price, shares, date):
        shares = min(shares, self.hst_pos)
        if shares <= 0: return
        amt = price * shares
        net = amt - self._comm(amt) - self._redeem_fee(self.lots_hst, price, shares, date)
        self.hst_pos -= shares; self.hst_cash += net
        self.hst_month_net -= net
        self.cashflows.append((pd.Timestamp(date), net))
        self.hst_month_grid += 1

    # ── 515450 网格 tick ──────────────────────────────────
    def _tick_hldb(self, price, date):
        if self.hldb_g1_ref is None: self.hldb_g1_ref = price
        if self.hldb_g2_ref is None: self.hldb_g2_ref = price
        for buy_pct, sell_pct, gs, attr in [
            (HLDB_G1_BUY, HLDB_G1_SELL, HLDB_G1_SH, "hldb_g1_ref"),
            (HLDB_G2_BUY, HLDB_G2_SELL, HLDB_G2_SH, "hldb_g2_ref"),
        ]:
            ref = getattr(self, attr)
            while True:
                pct = (price - ref) / ref
                if pct <= -buy_pct:
                    self._buy_hldb(ref * (1 - buy_pct), gs, date, is_grid=True)
                    ref = ref * (1 - buy_pct)
                elif pct >= sell_pct and self.hldb_pos >= gs:
                    self._sell_hldb(ref * (1 + sell_pct), gs, date)
                    ref = ref * (1 + sell_pct)
                else:
                    break
            setattr(self, attr, ref)

    # ── 513130 网格 tick ──────────────────────────────────
    def _tick_hst(self, price, date):
        if self.hst_g1_ref is None: self.hst_g1_ref = price
        if self.hst_g2_ref is None: self.hst_g2_ref = price
        for buy_pct, sell_pct, gs, attr in [
            (HST_G1_BUY, HST_G1_SELL, HST_G1_SH, "hst_g1_ref"),
            (HST_G2_BUY, HST_G2_SELL, HST_G2_SH, "hst_g2_ref"),
        ]:
            ref = getattr(self, attr)
            while True:
                pct = (price - ref) / ref
                if pct <= -buy_pct:
                    self._buy_hst(ref * (1 - buy_pct), gs, date, is_grid=True)
                    ref = ref * (1 - buy_pct)
                elif pct >= sell_pct and self.hst_pos >= gs:
                    self._sell_hst(ref * (1 + sell_pct), gs, date)
                    ref = ref * (1 + sell_pct)
                else:
                    break
            setattr(self, attr, ref)

    # ── 月末结算 ─────────────────────────────────────────
    def _month_settle(self, mkey, hldb_price, hst_price, date):
        # 515450: 补足缺口至 HLDB_MONTHLY
        hldb_deficit = HLDB_MONTHLY - self.hldb_month_net
        hldb_dca = False
        if hldb_deficit > 0 and hldb_price >= 0.01:
            sh = max(int(hldb_deficit / hldb_price / 100) * 100, 100)
            if hldb_deficit >= hldb_price * 100:
                self._buy_hldb(hldb_price, sh, date, is_grid=False)
                hldb_dca = True
        # 513130: 补足缺口至 HST_MONTHLY
        hst_deficit = HST_MONTHLY - self.hst_month_net
        hst_dca = False
        if hst_deficit > 0 and hst_price >= 0.01:
            sh = max(int(hst_deficit / hst_price / 100) * 100, 100)
            if hst_deficit >= hst_price * 100:
                self._buy_hst(hst_price, sh, date, is_grid=False)
                hst_dca = True
        self.monthly.append(dict(
            month        = mkey,
            hldb_spent   = round(self.hldb_month_net, 2),
            hldb_grid    = self.hldb_month_grid,
            hldb_dca     = int(hldb_dca),
            hst_spent    = round(self.hst_month_net, 2),
            hst_grid     = self.hst_month_grid,
            hst_dca      = int(hst_dca),
            hldb_pos     = self.hldb_pos,
            hst_pos      = self.hst_pos,
        ))
        self.hldb_month_net  = 0.0; self.hldb_month_grid = 0
        self.hst_month_net   = 0.0; self.hst_month_grid  = 0

    # ── 主循环 ───────────────────────────────────────────
    def run(self, merged_df, rng):
        prev_month = None
        for idx, row in merged_df.iterrows():
            date = row["date"]
            mkey = date.strftime("%Y-%m")
            if prev_month is not None and mkey != prev_month:
                pr = merged_df.iloc[idx - 1]
                self._month_settle(prev_month, pr["hldb_close"], pr["hst_close"], pr["date"])
            prev_month = mkey
            for p in synthesize_intraday(
                row["hldb_open"], row["hldb_high"], row["hldb_low"], row["hldb_close"], rng
            ):
                self._tick_hldb(p, date)
            for p in synthesize_intraday(
                row["hst_open"], row["hst_high"], row["hst_low"], row["hst_close"], rng
            ):
                self._tick_hst(p, date)
            hldb_val  = self.hldb_pos * row["hldb_close"]
            hst_val   = self.hst_pos  * row["hst_close"]
            total_inv = -(self.hldb_cash + self.hst_cash)
            self.records.append(dict(
                date      = date,
                hldb_val  = round(hldb_val, 2),
                hst_val   = round(hst_val, 2),
                total_val = round(hldb_val + hst_val, 2),
                total_inv = round(total_inv, 2),
            ))
        if prev_month and len(merged_df) > 0:
            last = merged_df.iloc[-1]
            self._month_settle(prev_month, last["hldb_close"], last["hst_close"], last["date"])
            hldb_val  = self.hldb_pos * last["hldb_close"]
            hst_val   = self.hst_pos  * last["hst_close"]
            total_inv = -(self.hldb_cash + self.hst_cash)
            self.records[-1].update(
                hldb_val=round(hldb_val,2), hst_val=round(hst_val,2),
                total_val=round(hldb_val+hst_val,2), total_inv=round(total_inv,2),
            )
        return pd.DataFrame(self.records), pd.DataFrame(self.monthly)


# ═══════════════════════ 工具函数 ═══════════════════════
def calc_ann(pnl, invested, days):
    yrs = max(days / 365.25, 0.01)
    return (1 + pnl / max(invested, 1)) ** (1 / yrs) - 1


def calc_sharpe(vals, invs):
    vals = np.asarray(vals, float)
    invs = np.clip(np.asarray(invs, float), 1, None)
    dr = pd.Series(vals / invs).pct_change().dropna()
    dr = dr[np.isfinite(dr)]
    return dr.mean() / max(dr.std(), 1e-9) * np.sqrt(242) if len(dr) > 30 else 0.0


def calc_maxdd(vals, invs):
    vals = np.asarray(vals, float)
    invs = np.clip(np.asarray(invs, float), 1, None)
    ratio = vals / invs
    peak = np.maximum.accumulate(ratio)
    dd = np.where(peak > 0, (ratio - peak) / peak, 0.0)
    return float(np.nanmin(np.clip(dd, -1, 0)))


def dca_single(df, budget, label):
    pos, cash_out, prev_m = 0, 0.0, None
    vals, invs, cfs = [], [], []
    for idx, row in df.iterrows():
        mkey = row["date"].strftime("%Y-%m")
        if prev_m is not None and mkey != prev_m:
            pc = df.iloc[idx - 1]["close"]
            sh = max(int(budget / pc / 100) * 100, 100)
            amt = sh * pc
            fee = max(abs(amt) * COMMISSION_ETF, MIN_COMM) + abs(amt) * BUY_FEE_RATE
            pos += sh; cash_out += amt + fee
            cfs.append((df.iloc[idx - 1]["date"], -(amt + fee)))
        prev_m = mkey
        vals.append(pos * row["close"])
        invs.append(cash_out)
    if prev_m:
        lc = df.iloc[-1]["close"]
        sh = max(int(budget / lc / 100) * 100, 100)
        amt = sh * lc
        fee = max(abs(amt) * COMMISSION_ETF, MIN_COMM) + abs(amt) * BUY_FEE_RATE
        pos += sh; cash_out += amt + fee
        cfs.append((df.iloc[-1]["date"], -(amt + fee)))
        vals[-1] = pos * lc; invs[-1] = cash_out
    days = (df.iloc[-1]["date"] - df.iloc[0]["date"]).days
    pnl = vals[-1] - invs[-1]
    ann = calc_ann(pnl, cash_out, days)
    cfs.append((df.iloc[-1]["date"], pos * df.iloc[-1]["close"]))
    xirr = calc_xirr(cfs)
    print(f"  {label}: 年化{ann*100:+.2f}%  XIRR{xirr*100:+.2f}%  投入{cash_out:,.0f}  市值{vals[-1]:,.0f}")
    return dict(ann_ret=ann, xirr=xirr, invested=cash_out, final=vals[-1],
                pnl=pnl, days=days, vals=np.array(vals), invs=np.array(invs))


# ═══════════════════════ Excel 导出 ═══════════════════════
def export_dual_excel(resdf, rdf_mid, mdf_mid, out_xlsx):
    from openpyxl import Workbook
    wb = Workbook()

    def write_sheet(ws, df):
        for c, name in enumerate(df.columns, 1):
            ws.cell(row=1, column=c, value=name)
        for r, row in enumerate(df.itertuples(index=False), 2):
            for c, v in enumerate(row, 1):
                ws.cell(row=r, column=c, value=v)

    ws1 = wb.active; ws1.title = "MC汇总"
    write_sheet(ws1, resdf)

    ws2 = wb.create_sheet("日明细")
    write_sheet(ws2, rdf_mid)
    if "date" in rdf_mid.columns:
        ci = rdf_mid.columns.get_loc("date") + 1
        for r in range(2, len(rdf_mid) + 2):
            ws2.cell(row=r, column=ci).number_format = "yyyy-mm-dd"

    ws3 = wb.create_sheet("月明细")
    write_sheet(ws3, mdf_mid)
    if "month" in mdf_mid.columns:
        ci = mdf_mid.columns.get_loc("month") + 1
        for r in range(2, len(mdf_mid) + 2):
            ws3.cell(row=r, column=ci).number_format = "yyyy-mm-dd"

    wb.save(out_xlsx)


def parse_args():
    parser = argparse.ArgumentParser(
        description="515450 + 513130 双网格回测 (支持预算与网格参数命令行覆盖)"
    )
    parser.add_argument("--monthly-total", type=float, default=5000,
                        help="组合总月预算, 默认 5000")
    parser.add_argument("--hldb-monthly", type=float, default=4500,
                        help="515450 月预算, 默认 4500")
    parser.add_argument("--hst-monthly", type=float, default=None,
                        help="513130 月预算; 不传则自动=总预算-515450预算")
    parser.add_argument("--n-sims", type=int, default=N_SIMS,
                        help=f"蒙特卡洛次数, 默认 {N_SIMS}")

    parser.add_argument("--hst-buy-pct", type=float, default=HST_G1_BUY,
                        help=f"恒科买入触发比例(两层共用), 默认 {HST_G1_BUY}")
    parser.add_argument("--hst-g1-sell-pct", type=float, default=HST_G1_SELL,
                        help=f"恒科G1卖出比例, 默认 {HST_G1_SELL}")
    parser.add_argument("--hst-g2-sell-pct", type=float, default=HST_G2_SELL,
                        help=f"恒科G2卖出比例, 默认 {HST_G2_SELL}")
    parser.add_argument("--hst-shares", type=int, default=HST_G1_SH,
                        help=f"恒科每格手数(两层共用), 默认 {HST_G1_SH}")
    return parser.parse_args()


def apply_runtime_args(args):
    global HLDB_MONTHLY, HST_MONTHLY, MONTHLY_BUDGET, N_SIMS
    global HST_G1_BUY, HST_G2_BUY, HST_G1_SELL, HST_G2_SELL, HST_G1_SH, HST_G2_SH

    total = float(args.monthly_total)
    hldb = float(args.hldb_monthly)
    hst = float(args.hst_monthly) if args.hst_monthly is not None else (total - hldb)

    if total <= 0:
        raise ValueError("--monthly-total 必须 > 0")
    if hldb < 0 or hst < 0:
        raise ValueError("--hldb-monthly / --hst-monthly 不能为负")
    if abs((hldb + hst) - total) > 1e-6:
        raise ValueError("预算不一致: hldb + hst 必须等于 monthly-total")
    if args.n_sims <= 0:
        raise ValueError("--n-sims 必须 > 0")

    hst_buy = float(args.hst_buy_pct)
    hst_s1 = float(args.hst_g1_sell_pct)
    hst_s2 = float(args.hst_g2_sell_pct)
    hst_sh = int(args.hst_shares)

    if hst_buy <= 0:
        raise ValueError("--hst-buy-pct 必须 > 0")
    if hst_s1 <= 0 or hst_s2 <= 0:
        raise ValueError("恒科卖出触发比例必须 > 0")
    if hst_s2 <= hst_s1:
        raise ValueError("恒科参数要求: --hst-g2-sell-pct 必须 > --hst-g1-sell-pct")
    if hst_sh <= 0:
        raise ValueError("--hst-shares 必须 > 0")

    HLDB_MONTHLY = hldb
    HST_MONTHLY = hst
    MONTHLY_BUDGET = total
    N_SIMS = int(args.n_sims)

    HST_G1_BUY = hst_buy
    HST_G2_BUY = hst_buy
    HST_G1_SELL = hst_s1
    HST_G2_SELL = hst_s2
    HST_G1_SH = hst_sh
    HST_G2_SH = hst_sh


# ═══════════════════════ 主程序 ═══════════════════════
def main():
    args = parse_args()
    apply_runtime_args(args)

    print("加载后复权数据 + 指数拟合扩展 ...")
    hldb_raw = load_with_index_extension(HLDB_CSV, HLDB_INDEX_CSV, "515450红利低波")
    hst_raw  = load_with_index_extension(HST_CSV,  HST_INDEX_CSV,  "513130恒科ETF")

    merged = build_aligned(hldb_raw, hst_raw)
    days   = (merged.iloc[-1]["date"] - merged.iloc[0]["date"]).days
    print(f"\n对齐区间: {merged.iloc[0]['date'].date()} ~ {merged.iloc[-1]['date'].date()}"
          f", {days}天 ({days/365.25:.1f}年)")
    print(f"月预算: {MONTHLY_BUDGET}元  (515450网格: {HLDB_MONTHLY}元  513130网格: {HST_MONTHLY}元)")
    print(f"515450网格: G1={HLDB_G1_BUY*100:.0f}%/{HLDB_G1_SELL*100:.0f}%/{HLDB_G1_SH}手  "
          f"G2={HLDB_G2_BUY*100:.0f}%/{HLDB_G2_SELL*100:.0f}%/{HLDB_G2_SH}手")
    print(f"513130网格: G1={HST_G1_BUY*100:.0f}%/{HST_G1_SELL*100:.0f}%/{HST_G1_SH}手  "
          f"G2={HST_G2_BUY*100:.0f}%/{HST_G2_SELL*100:.0f}%/{HST_G2_SH}手")

    hldb_daily = merged[["date","hldb_close"]].rename(columns={"hldb_close":"close"}).copy()
    hst_daily  = merged[["date","hst_close" ]].rename(columns={"hst_close" :"close"}).copy()

    print(f"\n混合定投基准 ({HLDB_MONTHLY}元515450 + {HST_MONTHLY}元恒科):")
    dca_hldb = dca_single(hldb_daily, HLDB_MONTHLY, f"515450纯定投({HLDB_MONTHLY}元)")
    dca_hst  = dca_single(hst_daily,  HST_MONTHLY,  f"513130纯定投({HST_MONTHLY}元)")

    print(f"\n515450双网格 + 513130双网格  蒙特卡洛 {N_SIMS} 次 ...")
    all_results, all_rdfs = [], []
    for i in range(N_SIMS):
        rng = np.random.default_rng(i * 137 + 42)
        bt  = DualGridBacktester()
        rdf, _ = bt.run(merged, rng)
        all_rdfs.append(rdf)

        r      = rdf.iloc[-1]
        pnl    = r["total_val"] - r["total_inv"]
        ann    = calc_ann(pnl, r["total_inv"], days)
        sharpe = calc_sharpe(rdf["total_val"].values, rdf["total_inv"].values)
        maxdd  = calc_maxdd(rdf["total_val"].values, rdf["total_inv"].values)
        final_mv = (bt.hldb_pos * merged.iloc[-1]["hldb_close"]
                    + bt.hst_pos  * merged.iloc[-1]["hst_close"])
        xirr = calc_xirr(bt.cashflows + [(rdf.iloc[-1]["date"], final_mv)])

        hldb_inv = -bt.hldb_cash; hst_inv = -bt.hst_cash
        hldb_ann = calc_ann(r["hldb_val"] - hldb_inv, hldb_inv, days) if hldb_inv > 0 else 0
        hst_ann  = calc_ann(r["hst_val"]  - hst_inv,  hst_inv,  days) if hst_inv  > 0 else 0

        all_results.append(dict(
            sim          = i + 1,
            total_inv    = round(r["total_inv"], 2),
            total_val    = round(r["total_val"], 2),
            pnl          = round(pnl, 2),
            ann_pct      = round(ann * 100, 2),
            xirr_pct     = round(xirr * 100, 2) if np.isfinite(xirr) else None,
            sharpe       = round(sharpe, 3),
            maxdd_pct    = round(maxdd * 100, 2),
            hldb_inv     = round(hldb_inv, 2),
            hldb_val     = round(r["hldb_val"], 2),
            hldb_ann_pct = round(hldb_ann * 100, 2),
            hst_inv      = round(hst_inv, 2),
            hst_val      = round(r["hst_val"], 2),
            hst_ann_pct  = round(hst_ann * 100, 2),
            hldb_pos     = bt.hldb_pos,
            hst_pos      = bt.hst_pos,
        ))
        xirr_str = f"{xirr*100:+.1f}%" if np.isfinite(xirr) else "N/A"
        print(f"  #{i+1:2d}  总年化{ann*100:+.1f}%  XIRR{xirr_str}  "
              f"回撤{maxdd*100:.1f}%  515450pos={bt.hldb_pos:,}  恒科pos={bt.hst_pos:,}")

    resdf = pd.DataFrame(all_results)
    print(f"\n{'='*70}")
    print(f"     515450双网格 + 513130双网格  蒙特卡洛统计 ({N_SIMS}次)")
    print(f"{'='*70}")
    for col, label in [
        ("ann_pct",      "组合年化%"),
        ("xirr_pct",     "组合XIRR%"),
        ("sharpe",       "夏普率"),
        ("maxdd_pct",    "最大回撤%"),
        ("hldb_ann_pct", "515450年化%"),
        ("hst_ann_pct",  "恒科年化%"),
    ]:
        v = resdf[col].dropna()
        print(f"  {label:12s}"
              + "".join(f"  P{int(p*100)}={v.quantile(p):>+8.2f}" for p in [0.1, 0.25, 0.5, 0.75, 0.9]))
    print(f"{'='*70}")

    mid_idx   = (resdf["pnl"] - resdf["pnl"].median()).abs().idxmin()
    mid       = resdf.iloc[mid_idx]
    xirr_disp = f"{mid['xirr_pct']:+.2f}%" if mid["xirr_pct"] is not None else "N/A"
    print(f"\n中位数模拟 (#{mid['sim']:.0f}):")
    print(f"  总投入:           {mid['total_inv']:>12,.0f} 元")
    print(f"  总市值:           {mid['total_val']:>12,.0f} 元")
    print(f"  总盈亏:           {mid['pnl']:>+12,.0f} 元")
    print(f"  组合年化:         {mid['ann_pct']:>+8.2f}%")
    print(f"  组合XIRR:         {xirr_disp:>10}")
    print(f"  夏普率:           {mid['sharpe']:>8.3f}")
    print(f"  最大回撤:         {mid['maxdd_pct']:>8.2f}%")
    print(f"  515450市值:       {mid['hldb_val']:>12,.0f} 元  "
          f"(持{mid['hldb_pos']:,.0f}股  年化{mid['hldb_ann_pct']:+.2f}%)")
    print(f"  恒科ETF市值:      {mid['hst_val']:>12,.0f} 元  "
          f"(持{mid['hst_pos']:,.0f}股  年化{mid['hst_ann_pct']:+.2f}%)")
    print(f"\n  参考基准 (纯定投):")
    print(f"    515450({HLDB_MONTHLY}元/月): 年化{dca_hldb['ann_ret']*100:+.2f}%  XIRR{dca_hldb['xirr']*100:+.2f}%")
    print(f"    恒科  ({HST_MONTHLY}元/月): 年化{dca_hst['ann_ret']*100:+.2f}%  XIRR{dca_hst['xirr']*100:+.2f}%")

    # ── 中位数轨迹重跑 ────────────────────────────────────
    rng_mid = np.random.default_rng(mid_idx * 137 + 42)
    bt_mid  = DualGridBacktester()
    rdf_mid, mdf_mid = bt_mid.run(merged, rng_mid)

    # ── 图表 ──────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(16, 16))
    fig.suptitle("515450双网格 + 513130恒科双网格 组合回测 (后复权, 杠铃策略)",
                 fontsize=14, fontweight="bold")

    ax = axes[0]
    # 只从首次实际投入后开始计算收益率，避免初期 inv≈0 导致 -100% 异常
    valid_mask   = rdf_mid["total_inv"] > 0
    rdf_plot     = rdf_mid[valid_mask].copy()
    inv          = rdf_plot["total_inv"]
    strategy_ret = (rdf_plot["total_val"] / inv - 1.0) * 100
    n_days = len(rdf_plot)
    h_inv = dca_hldb["invs"]; h_val = dca_hldb["vals"]
    t_inv = dca_hst["invs"];  t_val = dca_hst["vals"]
    if len(h_inv) >= n_days:
        mixed_inv = (h_inv[-n_days:] + t_inv[-n_days:])
        mixed_val = h_val[-n_days:] + t_val[-n_days:]
        mixed_mask = mixed_inv > 0
        mixed_ret = np.where(mixed_mask, (mixed_val / np.where(mixed_mask, mixed_inv, 1) - 1.0) * 100, np.nan)
        ax.plot(rdf_plot["date"], mixed_ret, color="gray", ls="-.", lw=1.0, alpha=0.8,
                label=f"混合定投基准({HLDB_MONTHLY}+{HST_MONTHLY})")
    ax.plot(rdf_plot["date"], strategy_ret, "b-", lw=1.5, label="515450+恒科双网格")
    ax.set_title("组合收益率走势"); ax.set_ylabel("收益率 (%)"); ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    months = mdf_mid["month"]
    hldb_s = mdf_mid["hldb_spent"].clip(lower=0)
    hst_s  = mdf_mid["hst_spent"].clip(lower=0)
    x = range(len(months))
    ax.bar(x, hldb_s, color="green",  alpha=0.7, label=f"515450网格(预算{HLDB_MONTHLY})")
    ax.bar(x, hst_s,  color="purple", alpha=0.6, bottom=hldb_s,
           label=f"恒科网格(预算{HST_MONTHLY})")
    ax.axhline(MONTHLY_BUDGET, color="blue", ls="--", lw=1, label=f"月总预算{MONTHLY_BUDGET}")
    step = max(1, len(months) // 20)
    ax.set_xticks(range(0, len(months), step))
    ax.set_xticklabels(months.iloc[::step], rotation=45)
    ax.set_title("月度资金分配"); ax.set_ylabel("金额 (元)")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    ax = axes[2]
    tv = rdf_mid["total_val"].clip(lower=1)
    gr = rdf_mid["hldb_val"] / tv * 100
    hr = rdf_mid["hst_val"]  / tv * 100
    ax.fill_between(rdf_mid["date"], 0,  gr,      alpha=0.5, color="green",  label="515450")
    ax.fill_between(rdf_mid["date"], gr, gr + hr, alpha=0.5, color="purple", label="恒科ETF")
    ax.set_title("资产占比"); ax.set_ylabel("%"); ax.set_ylim(0, 105)
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    out_png = os.path.join(OUTPUT_DIR, "dual_backtest.png")
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n图表已保存: {out_png}")

    out_xlsx = os.path.join(OUTPUT_DIR, "dual_backtest.xlsx")
    export_dual_excel(resdf, rdf_mid, mdf_mid, out_xlsx)
    print(f"Excel已保存: {out_xlsx}")


if __name__ == "__main__":
    main()
