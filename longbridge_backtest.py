#!/usr/bin/env python3
"""Run the existing single-ETF engine with Longbridge daily K-lines.

The original ``backtest.py`` remains the legacy/AkShare entrypoint.  This file
reuses its strategy, Monte Carlo, charts and Excel export while sourcing OHLCV
from Longbridge.
"""

from __future__ import annotations

import argparse
import os

import backtest as bt
from longbridge_data import load_daily_data, resolve_symbol


def main():
    parser = argparse.ArgumentParser(description="515450 single backtest using Longbridge data")
    parser.add_argument("--symbol", default=bt.SYMBOL, help="project code or Longbridge symbol, e.g. 515450 or 515450.SH")
    parser.add_argument("--lb-adjust", choices=["actual", "forward"], default="actual")
    parser.add_argument("--lb-start", default="2000-01-01")
    parser.add_argument("--lb-refresh", action="store_true")
    args = parser.parse_args()

    symbol = resolve_symbol(args.symbol)
    df = load_daily_data(
        symbol,
        start=args.lb_start,
        adjust=args.lb_adjust,
        refresh=args.lb_refresh,
    )

    bt.SYMBOL = args.symbol.split(".", 1)[0]
    print(
        f"共 {len(df)} 个交易日 "
        f"({df.iloc[0]['date'].strftime('%Y-%m-%d')} ~ {df.iloc[-1]['date'].strftime('%Y-%m-%d')})"
    )
    print(f"价格区间: {df['low'].min():.3f} ~ {df['high'].max():.3f}")

    rdf, tdf, ddf, mdf, all_ddf, dca_bench = bt.run_monte_carlo(df)
    bt.plot_all(tdf, ddf, mdf, df, all_ddf, dca_bench=dca_bench)
    bt.export_excel(rdf, tdf, ddf, mdf, dca_bench)

    for name, frame in [("trades", tdf), ("daily", ddf), ("monthly", mdf), ("mc_summary", rdf)]:
        frame.to_csv(os.path.join(bt.OUTPUT_DIR, f"{name}.csv"), index=False, encoding="utf-8-sig")

    print("\nCSV文件已保存: trades/daily/monthly/mc_summary.csv")
    print("Longbridge 回测完成!")


if __name__ == "__main__":
    main()
