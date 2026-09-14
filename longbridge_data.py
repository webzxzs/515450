#!/usr/bin/env python3
"""Longbridge market-data adapter for the 515450 backtest project.

Design goals:
- Keep the legacy AkShare/HFQ files untouched.
- Pull official Longbridge historical K-lines through the authenticated CLI.
- Cache normalized OHLCV data outside the repository.
- Fetch in calendar-year chunks so long histories do not depend on a single
  <=1000-candle response.
- Make price adjustment explicit: ``actual`` or ``forward``.

The Longbridge CLI is preferred because it reuses the OAuth token created by
``longbridge auth login`` and does not require secrets in this repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


SYMBOL_MAP = {
    "515450": "515450.SH",
    "513130": "513130.SH",
}

MARKET_TZ = {
    "SH": "Asia/Shanghai",
    "SZ": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}

REQUIRED_COLUMNS = ["date", "open", "high", "low", "close"]


class LongbridgeDataError(RuntimeError):
    """Raised when Longbridge market data cannot be loaded safely."""


@dataclass(frozen=True)
class CacheInfo:
    path: Path
    symbol: str
    adjust: str


def resolve_symbol(symbol: str) -> str:
    """Convert project codes to Longbridge ``ticker.region`` symbols."""
    raw = str(symbol).strip().upper()
    if raw in SYMBOL_MAP:
        return SYMBOL_MAP[raw]
    if "." in raw:
        return raw
    if raw.startswith(("5", "6", "9")):
        return f"{raw}.SH"
    return f"{raw}.SZ"


def _cache_root() -> Path:
    override = os.getenv("BACKTEST_LONGBRIDGE_CACHE")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "515450-backtest" / "longbridge"
    return Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "515450-backtest" / "longbridge"


def cache_info(symbol: str, adjust: str) -> CacheInfo:
    lb_symbol = resolve_symbol(symbol)
    safe = lb_symbol.replace(".", "_")
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    return CacheInfo(root / f"{safe}_{adjust}.csv", lb_symbol, adjust)


def _market_timezone(symbol: str) -> str:
    region = symbol.rsplit(".", 1)[-1].upper()
    return MARKET_TZ.get(region, "UTC")


def _normalize_date(value, symbol: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(_market_timezone(symbol)).tz_localize(None)
    return pd.Timestamp(ts.date())


def _extract_rows(payload) -> list[dict]:
    """Accept the CLI's current JSON array and a few defensive wrapper shapes."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise LongbridgeDataError(f"Unexpected Longbridge JSON type: {type(payload).__name__}")

    for key in ("candlesticks", "items", "result", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("candlesticks", "items", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise LongbridgeDataError("Longbridge JSON did not contain a candlestick array")


def _rows_to_frame(rows: Iterable[dict], symbol: str) -> pd.DataFrame:
    normalized = []
    for row in rows:
        ts = row.get("time", row.get("timestamp", row.get("date")))
        if ts is None:
            continue
        normalized.append(
            {
                "date": _normalize_date(ts, symbol),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("turnover", row.get("amount")),
            }
        )

    df = pd.DataFrame(normalized)
    if df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS + ["volume", "amount"])

    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df.dropna(subset=REQUIRED_COLUMNS)
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return df


def _year_windows(start: date, end: date):
    cursor = start
    while cursor <= end:
        window_end = min(date(cursor.year, 12, 31), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _run_cli_window(symbol: str, start: date, end: date, adjust: str) -> pd.DataFrame:
    exe = shutil.which("longbridge")
    if not exe:
        raise LongbridgeDataError(
            "Longbridge CLI not found. Install it, run `longbridge auth login`, then retry."
        )

    cmd = [
        exe,
        "kline",
        "history",
        symbol,
        "--period",
        "day",
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--format",
        "json",
    ]
    if adjust == "forward":
        cmd.extend(["--adjust", "forward"])

    proc = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown error").strip()
        raise LongbridgeDataError(f"Longbridge CLI failed for {symbol}: {detail}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LongbridgeDataError(
            f"Longbridge returned non-JSON output for {symbol}: {proc.stdout[:300]!r}"
        ) from exc

    return _rows_to_frame(_extract_rows(payload), symbol)


def fetch_daily(
    symbol: str,
    start: date | str,
    end: date | str | None = None,
    *,
    adjust: str = "actual",
) -> pd.DataFrame:
    """Fetch daily Longbridge candles for a date range.

    ``adjust`` is deliberately limited to values Longbridge actually supports:
    ``actual`` (unadjusted/tradeable historical prices) or ``forward``.
    """
    if adjust not in {"actual", "forward"}:
        raise ValueError("adjust must be 'actual' or 'forward'")

    lb_symbol = resolve_symbol(symbol)
    start_d = pd.Timestamp(start).date()
    end_d = pd.Timestamp(end or date.today()).date()
    if start_d > end_d:
        raise ValueError(f"start {start_d} is after end {end_d}")

    frames = []
    for a, b in _year_windows(start_d, end_d):
        part = _run_cli_window(lb_symbol, a, b, adjust)
        if not part.empty:
            frames.append(part)

    if not frames:
        raise LongbridgeDataError(f"Longbridge returned no daily data for {lb_symbol}")

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    return out


def _read_cache(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise LongbridgeDataError(f"Bad Longbridge cache {path}: missing {missing}")
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close", "volume", "amount"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def load_daily_data(
    symbol: str,
    *,
    start: date | str = "2000-01-01",
    end: date | str | None = None,
    adjust: str = "actual",
    refresh: bool = False,
) -> pd.DataFrame:
    """Load cached Longbridge data and incrementally refresh missing ranges."""
    info = cache_info(symbol, adjust)
    requested_start = pd.Timestamp(start).date()
    requested_end = pd.Timestamp(end or date.today()).date()

    cached = None
    if info.path.exists() and not refresh:
        cached = _read_cache(info.path)

    fetch_ranges: list[tuple[date, date]] = []
    if cached is None or cached.empty:
        fetch_ranges.append((requested_start, requested_end))
    else:
        cache_start = cached["date"].iloc[0].date()
        cache_end = cached["date"].iloc[-1].date()
        if requested_start < cache_start:
            fetch_ranges.append((requested_start, cache_start - timedelta(days=1)))
        # Seven calendar days tolerates weekends and normal exchange holidays.
        if requested_end > cache_end and (requested_end - cache_end).days > 0:
            fetch_ranges.append((cache_end + timedelta(days=1), requested_end))

    frames = [cached] if cached is not None and not cached.empty else []
    for a, b in fetch_ranges:
        if a <= b:
            frames.append(fetch_daily(info.symbol, a, b, adjust=adjust))

    if not frames:
        raise LongbridgeDataError(f"No data available for {info.symbol}")

    merged = pd.concat(frames, ignore_index=True)
    merged = (
        merged.drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    merged.to_csv(info.path, index=False)

    mask = (merged["date"].dt.date >= requested_start) & (merged["date"].dt.date <= requested_end)
    result = merged.loc[mask].reset_index(drop=True)
    if result.empty:
        raise LongbridgeDataError(
            f"No cached/fetched rows for {info.symbol} in {requested_start}..{requested_end}"
        )

    print(
        f"Longbridge {info.symbol} [{adjust}] "
        f"{result['date'].iloc[0].date()} ~ {result['date'].iloc[-1].date()}, "
        f"{len(result)} bars (cache: {info.path})"
    )
    return result
