#!/usr/bin/env python3
"""
获取恒生科技指数历史数据并拼接到ETF数据
"""

import json, os
import urllib.request
import akshare as ak
import pandas as pd

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def splice_index_etf(index_df, etf_df, name):
    """拼接: 指数(ETF上市前) + ETF(上市后), 在重叠日做价格缩放对齐"""
    etf_start = etf_df["date"].iloc[0]

    mask = index_df["date"] == etf_start
    if mask.any():
        idx_row = index_df[mask].iloc[0]
    else:
        idx_before = index_df[index_df["date"] <= etf_start]
        if len(idx_before) > 0:
            idx_row = idx_before.iloc[-1]
        else:
            idx_row = index_df.iloc[0]

    etf_row = etf_df.iloc[0]
    scale = etf_row["close"] / idx_row["close"]
    print(f"  {name}: 缩放因子 = {scale:.6f}")
    print(f"    指数 {idx_row['date'].date()} close={idx_row['close']:.4f}")
    print(f"    ETF  {etf_row['date'].date()} close={etf_row['close']:.4f}")

    pre_etf = index_df[index_df["date"] < etf_start].copy()
    for c in ["open", "high", "low", "close"]:
        pre_etf[c] = (pre_etf[c] * scale).round(4)

    combined = pd.concat([pre_etf, etf_df], ignore_index=True)
    combined = combined.sort_values("date").reset_index(drop=True)
    print(f"  {name}: 拼接完成 {len(combined)} 行")
    print(f"    {combined['date'].iloc[0].date()} ~ {combined['date'].iloc[-1].date()}")
    print(f"    指数部分: {len(pre_etf)} 行, ETF部分: {len(etf_df)} 行")
    return combined


def align_calendar_ffill(df):
    """按自然日对齐并前值填充，避免多标的日期错位。"""
    out = df.copy().sort_values("date").drop_duplicates("date").set_index("date")
    full_idx = pd.date_range(out.index.min(), out.index.max(), freq="D")
    out = out.reindex(full_idx).ffill().reset_index().rename(columns={"index": "date"})
    return out


def main():
    # 1. 恒生科技指数 (akshare)
    print("=" * 60)
    print("1. 获取恒生科技指数 (HSTECH)")
    print("=" * 60)
    hstech = ak.stock_hk_index_daily_sina(symbol="HSTECH")
    hstech = hstech.rename(columns={c: c.lower() for c in hstech.columns})
    hstech["date"] = pd.to_datetime(hstech["date"])
    for c in ["open", "high", "low", "close"]:
        hstech[c] = hstech[c].astype(float)
    hstech = hstech[["date", "open", "high", "low", "close"]].sort_values("date").reset_index(drop=True)
    print(f"  {len(hstech)} 行: {hstech['date'].iloc[0].date()} ~ {hstech['date'].iloc[-1].date()}")
    hstech.to_csv(os.path.join(OUTPUT_DIR, "index_hstech.csv"), index=False)

    # 2. 拼接
    print("\n" + "=" * 60)
    print("2. 拼接指数 + ETF 数据")
    print("=" * 60)

    etf_hst = pd.read_csv(os.path.join(OUTPUT_DIR, "etf_513130.csv"))
    etf_hst["date"] = pd.to_datetime(etf_hst["date"])
    for c in ["open", "high", "low", "close"]:
        etf_hst[c] = etf_hst[c].astype(float)

    print("\n恒科:")
    combined_hst = splice_index_etf(hstech, etf_hst, "恒科")
    combined_hst = align_calendar_ffill(combined_hst)
    combined_hst.to_csv(os.path.join(OUTPUT_DIR, "combined_hst.csv"), index=False)

    # 3. 双标的最大公共区间
    print("\n" + "=" * 60)
    print("3. 双标的公共区间")
    print("=" * 60)
    hldb = pd.read_csv(os.path.join(OUTPUT_DIR, "index_data.csv"))
    hldb["date"] = pd.to_datetime(hldb["date"])

    start = max(hldb["date"].iloc[0], combined_hst["date"].iloc[0])
    end = min(hldb["date"].iloc[-1], combined_hst["date"].iloc[-1])
    days = (end - start).days
    print(f"  515450: {hldb['date'].iloc[0].date()} ~ {hldb['date'].iloc[-1].date()}")
    print(f"  恒科:   {combined_hst['date'].iloc[0].date()} ~ {combined_hst['date'].iloc[-1].date()}")
    print(f"  公共区间: {start.date()} ~ {end.date()}, {days}天 ({days/365.25:.1f}年)")

    print("\n完成!")


if __name__ == "__main__":
    main()
