#!/usr/bin/env python3
"""Refresh the historical 1Y China government-bond risk-free-rate snapshot."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import akshare as ak
import pandas as pd


OUTPUT = Path(__file__).resolve().with_name("risk_free.csv")
CURVE_NAME = "中债国债收益率曲线"
TENOR_COLUMN = "1年"
SOURCE = "ChinaBond via AKShare bond_china_yield"


def fetch_history(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if end < start:
        raise ValueError("end must not be before start")

    chunks: list[pd.DataFrame] = []
    cursor = start.normalize()
    while cursor <= end:
        chunk_end = min(cursor + pd.Timedelta(days=330), end)
        raw = ak.bond_china_yield(
            start_date=cursor.strftime("%Y%m%d"),
            end_date=chunk_end.strftime("%Y%m%d"),
        )
        if not raw.empty:
            part = raw.loc[raw["曲线名称"].astype(str) == CURVE_NAME, ["日期", TENOR_COLUMN]].copy()
            part = part.rename(columns={"日期": "date", TENOR_COLUMN: "annual_yield_pct"})
            chunks.append(part)
        cursor = chunk_end + pd.Timedelta(days=1)

    if not chunks:
        raise RuntimeError("ChinaBond query returned no 1Y government-bond yield observations")

    out = pd.concat(chunks, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["annual_yield_pct"] = pd.to_numeric(out["annual_yield_pct"], errors="coerce")
    out = out.dropna().sort_values("date").drop_duplicates("date", keep="last")
    out = out.loc[(out["date"] >= start) & (out["date"] <= end)].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out["curve"] = CURVE_NAME
    out["tenor"] = "1Y"
    out["source"] = SOURCE
    return out.reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    out = fetch_history(start, end)
    output = Path(args.output)
    out.to_csv(output, index=False, encoding="utf-8-sig")
    print(
        f"saved {len(out)} observations to {output} | "
        f"{out.iloc[0]['date']} ~ {out.iloc[-1]['date']} | "
        f"1Y yield {out['annual_yield_pct'].min():.4f}% ~ {out['annual_yield_pct'].max():.4f}%"
    )


if __name__ == "__main__":
    main()
