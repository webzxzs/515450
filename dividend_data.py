#!/usr/bin/env python3
"""Explicit ETF cash-dividend data and total-return reconstruction.

Long-horizon research uses Longbridge actual market prices plus this
auditable dividend table. The synthetic total-return close assumes cash
distributions are reinvested on the ex-dividend date.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


DIVIDEND_FILE = Path(__file__).resolve().with_name("dividends.csv")
REQUIRED_COLUMNS = {
    "symbol",
    "record_date",
    "ex_date",
    "payment_date",
    "cash_per_share",
    "source",
}


def load_dividend_events(symbol: str | None = None) -> pd.DataFrame:
    """Load the repo-maintained cash-dividend schedule."""
    if not DIVIDEND_FILE.exists():
        raise FileNotFoundError(f"Dividend data file not found: {DIVIDEND_FILE}")

    events = pd.read_csv(DIVIDEND_FILE)
    missing = REQUIRED_COLUMNS.difference(events.columns)
    if missing:
        raise ValueError(f"Dividend data missing columns: {sorted(missing)}")

    events["symbol"] = events["symbol"].astype(str)
    for column in ("record_date", "ex_date", "payment_date"):
        events[column] = pd.to_datetime(events[column], errors="raise")
    events["cash_per_share"] = pd.to_numeric(events["cash_per_share"], errors="raise")
    if (events["cash_per_share"] <= 0).any():
        raise ValueError("Dividend cash_per_share must be positive")

    duplicates = events.duplicated(["symbol", "ex_date"], keep=False)
    if duplicates.any():
        dup = events.loc[duplicates, ["symbol", "ex_date"]].astype(str).to_dict("records")
        raise ValueError(f"Duplicate dividend events: {dup}")

    if symbol is not None:
        events = events.loc[events["symbol"] == str(symbol)]
    return events.sort_values(["symbol", "ex_date"]).reset_index(drop=True)


def apply_explicit_total_return(
    daily: pd.DataFrame,
    symbol: str,
    *,
    events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Replace close with an explicit cash-dividend total-return series."""
    if "date" not in daily.columns or "close" not in daily.columns:
        raise ValueError("daily must contain date and close")

    out = daily.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.sort_values("date").reset_index(drop=True)
    if out.empty:
        return out

    selected = load_dividend_events(symbol) if events is None else events.copy()
    if selected.empty:
        return out

    valid = out["close"].notna() & (out["close"] > 0)
    if not valid.any():
        raise ValueError(f"No positive actual close values for {symbol}")
    first_valid = int(np.flatnonzero(valid.to_numpy())[0])
    if (~valid.iloc[first_valid:]).any():
        raise ValueError(f"Invalid actual close values after listing for {symbol}")

    active = out.loc[valid].copy().reset_index()

    selected["ex_date"] = pd.to_datetime(selected["ex_date"])
    selected["cash_per_share"] = pd.to_numeric(selected["cash_per_share"], errors="raise")

    first_date = pd.Timestamp(active["date"].iloc[0])
    last_date = pd.Timestamp(active["date"].iloc[-1])
    in_range = selected.loc[
        (selected["ex_date"] >= first_date) & (selected["ex_date"] <= last_date)
    ].copy()
    observed_dates = set(pd.to_datetime(active["date"]))
    missing_dates = sorted(
        pd.Timestamp(value)
        for value in in_range["ex_date"]
        if pd.Timestamp(value) not in observed_dates
    )
    if missing_dates:
        raise ValueError(
            f"Dividend ex-dates missing from actual price history for {symbol}: "
            + ", ".join(str(d.date()) for d in missing_dates)
        )

    dividends = (
        in_range.groupby("ex_date", as_index=True)["cash_per_share"].sum()
        if not in_range.empty
        else pd.Series(dtype=float)
    )
    cash = active["date"].map(dividends).fillna(0.0).astype(float)
    actual = active["close"].astype(float)
    growth = (actual + cash) / actual.shift(1)
    growth.iloc[0] = 1.0
    if not np.isfinite(growth).all() or (growth <= 0).any():
        raise ValueError(f"Invalid total-return growth factors for {symbol}")

    active["close"] = float(actual.iloc[0]) * growth.cumprod()
    out.loc[active["index"], "close"] = active["close"].to_numpy()
    return out
