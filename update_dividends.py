#!/usr/bin/env python3
"""Refresh the repo-pinned ETF dividend snapshot from independent data sources.

Data flow:

1. AKShare fund_etf_dividend_sina identifies cumulative ETF dividends quickly.
2. AKShare fund_fh_em (Eastmoney) provides record/ex/payment dates and cash/份.
3. The two sources are cross-checked before dividends.csv can be overwritten.

Backtests never call these network sources directly. They only consume the
versioned dividends.csv snapshot, so historical runs remain reproducible.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

import config as cfg
from backtest import parse_portfolio


OUTPUT = Path(__file__).resolve().with_name("dividends.csv")


def _sina_symbol(symbol: str) -> str:
    code, market = symbol.split(".")
    prefix = {"SH": "sh", "SZ": "sz"}.get(market.upper())
    if prefix is None:
        raise ValueError(f"Unsupported ETF market: {symbol}")
    return prefix + code


def _code(symbol: str) -> str:
    return symbol.split(".")[0]


def fetch_sina_events(symbol: str) -> pd.DataFrame:
    """Convert Sina cumulative dividends into per-event cash distributions."""
    raw = ak.fund_etf_dividend_sina(symbol=_sina_symbol(symbol)).copy()
    if raw.empty:
        return pd.DataFrame(columns=["symbol", "ex_date", "cash_per_share"])

    raw["日期"] = pd.to_datetime(raw["日期"], errors="raise")
    raw["累计分红"] = pd.to_numeric(raw["累计分红"], errors="raise")
    raw = raw.sort_values("日期").reset_index(drop=True)
    cash = raw["累计分红"].diff()
    cash.iloc[0] = raw["累计分红"].iloc[0]
    if (cash <= 0).any():
        raise ValueError(f"Non-positive dividend increment from Sina for {symbol}")

    return pd.DataFrame(
        {
            "symbol": symbol,
            "ex_date": raw["日期"],
            "cash_per_share": cash.astype(float),
        }
    )


def fetch_eastmoney_events(symbol: str, years: list[int]) -> pd.DataFrame:
    """Fetch detailed dividend rows from Eastmoney through AKShare."""
    code = _code(symbol)
    rows: list[pd.DataFrame] = []
    for year in years:
        raw = ak.fund_fh_em(year=str(year), page=-1)
        if raw.empty:
            continue
        hit = raw.loc[raw["基金代码"].astype(str).str.zfill(6) == code].copy()
        if hit.empty:
            continue
        rows.append(hit)

    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "record_date",
                "ex_date",
                "payment_date",
                "cash_per_share",
                "source",
            ]
        )

    raw = pd.concat(rows, ignore_index=True)
    out = pd.DataFrame(
        {
            "symbol": symbol,
            "record_date": pd.to_datetime(raw["权益登记日"], errors="raise"),
            "ex_date": pd.to_datetime(raw["除息日期"], errors="raise"),
            "payment_date": pd.to_datetime(raw["分红发放日"], errors="raise"),
            "cash_per_share": pd.to_numeric(raw["分红"], errors="raise"),
            "source": "AKShare:fund_fh_em(Eastmoney), verified by fund_etf_dividend_sina(Sina)",
        }
    )
    return (
        out.drop_duplicates(["symbol", "ex_date"], keep="last")
        .sort_values(["symbol", "ex_date"])
        .reset_index(drop=True)
    )


def cross_check(sina: pd.DataFrame, eastmoney: pd.DataFrame, symbol: str) -> None:
    """Require both providers to agree on every ex-date and cash amount."""
    if sina.empty and eastmoney.empty:
        return
    if sina.empty != eastmoney.empty:
        raise ValueError(f"Dividend source disagreement for {symbol}: one source is empty")

    a = sina[["ex_date", "cash_per_share"]].copy()
    b = eastmoney[["ex_date", "cash_per_share"]].copy()
    merged = a.merge(b, on="ex_date", how="outer", suffixes=("_sina", "_eastmoney"))
    bad = merged[
        merged["cash_per_share_sina"].isna()
        | merged["cash_per_share_eastmoney"].isna()
        | ~np.isclose(
            merged["cash_per_share_sina"],
            merged["cash_per_share_eastmoney"],
            rtol=0,
            atol=1e-9,
        )
    ]
    if not bad.empty:
        raise ValueError(
            f"Dividend source disagreement for {symbol}:\n{bad.to_string(index=False)}"
        )


def normalize_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "symbol",
        "record_date",
        "ex_date",
        "payment_date",
        "cash_per_share",
        "source",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)
    out = df[columns].copy()
    for column in ("record_date", "ex_date", "payment_date"):
        out[column] = pd.to_datetime(out[column]).dt.strftime("%Y-%m-%d")
    out["cash_per_share"] = pd.to_numeric(out["cash_per_share"])
    return out.sort_values(["symbol", "ex_date"]).reset_index(drop=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验/更新 ETF 现金分红快照")
    parser.add_argument(
        "--write",
        action="store_true",
        help="校验通过后覆盖 dividends.csv；默认只检查并显示差异",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = list(parse_portfolio(cfg.DEFAULT_PORTFOLIO))
    all_events: list[pd.DataFrame] = []

    for symbol in symbols:
        sina = fetch_sina_events(symbol)
        if sina.empty:
            print(f"{symbol}: no cash dividends from Sina")
            continue

        first_year = int(sina["ex_date"].dt.year.min())
        years = list(range(first_year, date.today().year + 1))
        eastmoney = fetch_eastmoney_events(symbol, years)
        cross_check(sina, eastmoney, symbol)
        all_events.append(eastmoney)
        print(
            f"{symbol}: {len(eastmoney)} events | "
            f"cash total={eastmoney['cash_per_share'].sum():.6f}"
        )

    fetched = normalize_snapshot(
        pd.concat(all_events, ignore_index=True)
        if all_events
        else pd.DataFrame()
    )
    local = normalize_snapshot(pd.read_csv(OUTPUT) if OUTPUT.exists() else pd.DataFrame())

    compare_cols = ["symbol", "record_date", "ex_date", "payment_date", "cash_per_share"]
    same = (
        list(fetched.columns) == list(local.columns)
        and len(fetched) == len(local)
        and fetched[compare_cols].equals(local[compare_cols])
    )

    if same:
        print(f"Snapshot is up to date: {OUTPUT.name}")
    else:
        print("\nFetched snapshot:")
        print(fetched.to_string(index=False))
        print("\nLocal snapshot:")
        print(local.to_string(index=False))
        if not args.write:
            raise SystemExit("dividends.csv differs; rerun with --write after review")

    if args.write:
        fetched.to_csv(OUTPUT, index=False, encoding="utf-8")
        print(f"Wrote {len(fetched)} dividend events to {OUTPUT}")


if __name__ == "__main__":
    main()
