#!/usr/bin/env python3
"""Run the multiprocessing dual-ETF parameter sweep with Longbridge market data."""

from __future__ import annotations

import argparse

import dual_backtest as db
from longbridge_data import load_daily_data


FILE_TO_SYMBOL = {
    db.HLDB_CSV: "515450.SH",
    db.HST_CSV: "513130.SH",
}


def main():
    parser = argparse.ArgumentParser(description="Longbridge-backed multiprocessing parameter sweep")
    parser.add_argument("--lb-adjust", choices=["actual", "forward"], default="actual")
    parser.add_argument("--lb-start", default="2000-01-01")
    parser.add_argument("--lb-refresh", action="store_true")
    args = parser.parse_args()

    original_loader = db.load_hfq_csv

    def load_from_longbridge(filename, label):
        symbol = FILE_TO_SYMBOL.get(filename)
        if symbol is None:
            return original_loader(filename, label)
        return load_daily_data(
            symbol,
            start=args.lb_start,
            adjust=args.lb_adjust,
            refresh=args.lb_refresh,
        )

    db.load_hfq_csv = load_from_longbridge

    import dual_sweep2_mp as sweep

    sweep.main()


if __name__ == "__main__":
    main()
