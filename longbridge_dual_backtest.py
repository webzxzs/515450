#!/usr/bin/env python3
"""Run the existing dual-ETF backtest with Longbridge as the ETF data source.

This intentionally leaves ``dual_backtest.py`` unchanged.  The wrapper replaces
only its ETF CSV loader, so the strategy engine, Monte Carlo simulation,
portfolio accounting, index-extension logic and CLI strategy parameters remain
identical to the legacy path.

Examples:
    python longbridge_dual_backtest.py
    python longbridge_dual_backtest.py --lb-adjust actual --n-sims 20
    python longbridge_dual_backtest.py --lb-adjust forward --hldb-monthly 4000

Longbridge-specific flags are consumed here; all other flags are forwarded to
``dual_backtest.py``.
"""

from __future__ import annotations

import argparse
import sys

import dual_backtest as db
from longbridge_data import load_daily_data


FILE_TO_SYMBOL = {
    db.HLDB_CSV: "515450.SH",
    db.HST_CSV: "513130.SH",
}


def _parse_wrapper_args(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--lb-adjust",
        choices=["actual", "forward"],
        default="actual",
        help="Longbridge price adjustment: actual (recommended for fixed-share trading) or forward",
    )
    parser.add_argument(
        "--lb-refresh",
        action="store_true",
        help="ignore Longbridge local cache and refetch the requested history",
    )
    parser.add_argument(
        "--lb-start",
        default="2020-01-01",
        help="earliest date requested from Longbridge (default: 2020-01-01)",
    )
    return parser.parse_known_args(argv)


def main():
    wrapper_args, remaining = _parse_wrapper_args(sys.argv[1:])

    original_loader = db.load_hfq_csv

    def load_from_longbridge(filename, label):
        symbol = FILE_TO_SYMBOL.get(filename)
        if symbol is None:
            return original_loader(filename, label)
        print(f"  {label}: 使用 Longbridge {symbol} ({wrapper_args.lb_adjust})")
        return load_daily_data(
            symbol,
            start=wrapper_args.lb_start,
            adjust=wrapper_args.lb_adjust,
            refresh=wrapper_args.lb_refresh,
        )

    db.load_hfq_csv = load_from_longbridge

    # dual_backtest.py owns the strategy CLI.  Remove wrapper-only flags before
    # handing control to it so all existing arguments keep working unchanged.
    sys.argv = [sys.argv[0], *remaining]
    db.main()


if __name__ == "__main__":
    main()
