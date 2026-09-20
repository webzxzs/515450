#!/usr/bin/env python3
"""Historical risk-free-rate helpers for Sharpe-ratio calculations.

The research benchmark is the ChinaBond 1-year government-bond yield curve.
ETF trading dates are matched to the latest yield published on or before that
date (backward-only merge, never look-ahead). The annual yield is converted to
an equivalent daily return using the research convention of 242 trading days.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_RISK_FREE_FILE = Path(__file__).resolve().with_name("risk_free.csv")
TRADING_DAYS_PER_YEAR = 242


@lru_cache(maxsize=8)
def _load_curve_cached(path_text: str) -> pd.DataFrame:
    path = Path(path_text)
    if not path.exists():
        raise FileNotFoundError(
            f"Risk-free snapshot not found: {path}. Run update_risk_free.py first."
        )

    df = pd.read_csv(path)
    required = {"date", "annual_yield_pct"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Risk-free snapshot missing columns: {sorted(missing)}")

    out = df[["date", "annual_yield_pct"]].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").astype("datetime64[ns]")
    out["annual_yield_pct"] = pd.to_numeric(out["annual_yield_pct"], errors="coerce")
    out = out.dropna().sort_values("date").drop_duplicates("date", keep="last")
    if out.empty:
        raise ValueError("Risk-free snapshot contains no usable observations")
    if (out["annual_yield_pct"] <= -100).any():
        raise ValueError("Risk-free annual yield must be greater than -100%")
    return out.reset_index(drop=True)


def load_risk_free_curve(path: str | Path = DEFAULT_RISK_FREE_FILE) -> pd.DataFrame:
    """Load the repo-maintained historical 1Y China government-bond yield snapshot."""
    return _load_curve_cached(str(Path(path).resolve())).copy()


@lru_cache(maxsize=128)
def _aligned_values_cached(
    date_ns: tuple[int, ...],
    path_text: str,
    trading_days: int,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    curve = _load_curve_cached(path_text)
    dates = pd.to_datetime(pd.Series(date_ns, dtype="int64")).astype("datetime64[ns]")
    left = pd.DataFrame({"date": dates, "_order": np.arange(len(dates), dtype=int)})
    merged = pd.merge_asof(
        left.sort_values("date"),
        curve.sort_values("date"),
        on="date",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("_order")

    if merged["annual_yield_pct"].isna().any():
        first_missing = merged.loc[merged["annual_yield_pct"].isna(), "date"].iloc[0]
        first_curve = curve["date"].iloc[0]
        raise ValueError(
            "Risk-free history does not reach the requested date "
            f"{first_missing.date()}; first available observation is {first_curve.date()}"
        )

    annual_decimal = merged["annual_yield_pct"].to_numpy(dtype=float) / 100.0
    daily = np.power(1.0 + annual_decimal, 1.0 / float(trading_days)) - 1.0
    return tuple(daily.tolist()), tuple(annual_decimal.tolist())


def align_risk_free_returns(
    dates: pd.Series | pd.Index | list,
    *,
    path: str | Path = DEFAULT_RISK_FREE_FILE,
    trading_days: int = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Return backward-aligned annual yields and equivalent daily risk-free returns."""
    parsed = pd.to_datetime(pd.Series(dates), errors="coerce").astype("datetime64[ns]")
    if parsed.isna().any():
        raise ValueError("Risk-free alignment received invalid dates")
    if trading_days <= 0:
        raise ValueError("trading_days must be positive")

    date_ns = tuple(parsed.astype("int64").tolist())
    resolved = str(Path(path).resolve())
    daily, annual = _aligned_values_cached(date_ns, resolved, int(trading_days))
    return pd.DataFrame(
        {
            "date": parsed.to_numpy(),
            "risk_free_annual": np.asarray(annual, dtype=float),
            "risk_free_daily": np.asarray(daily, dtype=float),
        }
    )


def annualized_excess_sharpe_from_daily(
    returns: pd.Series | list,
    risk_free_daily: pd.Series | list,
    *,
    trading_days: int = TRADING_DAYS_PER_YEAR,
    min_observations: int = 30,
) -> float:
    """Calculate annualized Sharpe from already aligned daily risk-free returns."""
    frame = pd.DataFrame(
        {
            "return": pd.to_numeric(pd.Series(returns), errors="coerce"),
            "risk_free_daily": pd.to_numeric(pd.Series(risk_free_daily), errors="coerce"),
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) <= min_observations:
        return float("nan")
    excess = frame["return"].to_numpy(dtype=float) - frame["risk_free_daily"].to_numpy(dtype=float)
    std = float(np.std(excess, ddof=1))
    if std <= 1e-12:
        return float("nan")
    return float(np.mean(excess) / std * np.sqrt(float(trading_days)))


def annualized_excess_sharpe(
    returns: pd.Series | list,
    dates: pd.Series | pd.Index | list,
    *,
    path: str | Path = DEFAULT_RISK_FREE_FILE,
    trading_days: int = TRADING_DAYS_PER_YEAR,
    min_observations: int = 30,
) -> float:
    """Calculate annualized Sharpe from daily excess returns over historical 1Y CGB yields."""
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(pd.Series(dates), errors="coerce"),
            "return": pd.to_numeric(pd.Series(returns), errors="coerce"),
        }
    ).replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna().reset_index(drop=True)
    if len(frame) <= min_observations:
        return float("nan")

    rf = align_risk_free_returns(
        frame["date"],
        path=path,
        trading_days=trading_days,
    )
    return annualized_excess_sharpe_from_daily(
        frame["return"],
        rf["risk_free_daily"],
        trading_days=trading_days,
        min_observations=min_observations,
    )


def mean_annual_risk_free_rate(
    dates: pd.Series | pd.Index | list,
    *,
    path: str | Path = DEFAULT_RISK_FREE_FILE,
    trading_days: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Mean backward-aligned annual risk-free yield, expressed as a decimal."""
    rf = align_risk_free_returns(dates, path=path, trading_days=trading_days)
    return float(rf["risk_free_annual"].mean())
