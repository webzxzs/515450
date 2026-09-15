#!/usr/bin/env python3
"""Explore robust target weights for the ETF DCA + rebalance strategy.

This is intentionally not a single-metric optimizer.  It enumerates a bounded
weight grid, runs the existing portfolio backtest for the full common history
and several chronological sub-periods, then ranks candidates by a blend of:

- full-period XIRR
- full-period Sharpe
- full-period max drawdown
- worst sub-period XIRR
- average sub-period XIRR
- sub-period XIRR stability
- diversification (lower HHI concentration)

The goal is to surface stable, investable candidate allocations rather than the
one historical combination that happened to maximize return.
"""

from __future__ import annotations

import argparse
import itertools
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import config as cfg
from backtest import (
    StrategyConfig,
    load_price_table,
    parse_lot_sizes,
    parse_portfolio,
    run_strategy,
)
from longbridge_data import resolve_symbol


OUTPUT_DIR = Path(__file__).resolve().parent


def parse_symbols(spec: str) -> list[str]:
    """Parse a comma-separated symbol list and normalize Longbridge suffixes."""
    symbols: list[str] = []
    for raw in str(spec).split(","):
        raw = raw.strip()
        if not raw:
            continue
        symbol = resolve_symbol(raw)
        if symbol in symbols:
            raise ValueError(f"Duplicate symbol: {symbol}")
        symbols.append(symbol)
    if len(symbols) < 2:
        raise ValueError("Need at least two symbols")
    return symbols


def default_symbols() -> list[str]:
    return list(parse_portfolio(cfg.DEFAULT_PORTFOLIO))


def effective_weight_bounds(
    symbols: Iterable[str],
    *,
    min_weight: float,
    max_weight: float,
) -> dict[str, tuple[float, float]]:
    """Resolve per-symbol bounds using config overrides plus global fallback."""
    if not (0 <= min_weight <= max_weight <= 1):
        raise ValueError("require 0 <= min_weight <= max_weight <= 1")

    configured = getattr(cfg, "WEIGHT_BOUNDS", {})
    bounds: dict[str, tuple[float, float]] = {}
    for symbol in symbols:
        lo, hi = configured.get(symbol, (min_weight, max_weight))
        lo = float(lo)
        hi = float(hi)
        if not (0 <= lo <= hi <= 1):
            raise ValueError(f"Invalid weight bounds for {symbol}: {(lo, hi)}")
        bounds[symbol] = (lo, hi)
    return bounds


def generate_weight_grid(
    symbols: Iterable[str],
    *,
    step: float = 0.05,
    min_weight: float = 0.10,
    max_weight: float = 0.50,
    symbol_bounds: dict[str, tuple[float, float]] | None = None,
) -> list[dict[str, float]]:
    """Enumerate bounded weight combinations that sum exactly to 100%.

    ``min_weight`` / ``max_weight`` provide the fallback bounds. Per-symbol
    bounds can override them, and by default configured overrides from
    ``config.WEIGHT_BOUNDS`` are applied. This lets the research ask whether a
    sleeve such as gold should be 0% without forcing the same floor on every
    other asset.
    """
    symbols = list(symbols)
    if len(symbols) < 2:
        raise ValueError("Need at least two symbols")
    if not (0 < step <= 1):
        raise ValueError("step must be in (0, 1]")
    units_total = round(1.0 / step)
    if not math.isclose(units_total * step, 1.0, abs_tol=1e-9):
        raise ValueError("step must divide 1.0 exactly, e.g. 0.10, 0.05, 0.025")

    bounds = (
        effective_weight_bounds(symbols, min_weight=min_weight, max_weight=max_weight)
        if symbol_bounds is None
        else {symbol: tuple(symbol_bounds.get(symbol, (min_weight, max_weight))) for symbol in symbols}
    )

    unit_bounds: dict[str, tuple[int, int]] = {}
    for symbol in symbols:
        lo, hi = (float(v) for v in bounds[symbol])
        if not (0 <= lo <= hi <= 1):
            raise ValueError(f"Invalid weight bounds for {symbol}: {(lo, hi)}")
        min_units = int(math.ceil(lo / step - 1e-9))
        max_units = int(math.floor(hi / step + 1e-9))
        if min_units > max_units:
            raise ValueError(f"No grid point fits bounds for {symbol}: {(lo, hi)}")
        unit_bounds[symbol] = (min_units, max_units)

    if sum(lo for lo, _ in unit_bounds.values()) > units_total:
        raise ValueError("minimum weights are too high for the selected symbols")
    if sum(hi for _, hi in unit_bounds.values()) < units_total:
        raise ValueError("maximum weights are too low for the selected symbols")

    head_symbols = symbols[:-1]
    head_choices = [
        range(unit_bounds[symbol][0], unit_bounds[symbol][1] + 1)
        for symbol in head_symbols
    ]
    last_symbol = symbols[-1]
    last_min, last_max = unit_bounds[last_symbol]

    out: list[dict[str, float]] = []
    for head in itertools.product(*head_choices):
        last = units_total - sum(head)
        if last < last_min or last > last_max:
            continue
        units = (*head, last)
        weights = {symbol: unit * step for symbol, unit in zip(symbols, units)}
        out.append(weights)
    return out


def chronological_folds(prices: pd.DataFrame, count: int = 3) -> list[pd.DataFrame]:
    """Split common history into contiguous, non-overlapping folds."""
    if count < 2:
        raise ValueError("fold count must be >= 2")
    if len(prices) < count * 40:
        raise ValueError("Not enough price history for requested fold count")

    edges = np.linspace(0, len(prices), count + 1, dtype=int)
    folds: list[pd.DataFrame] = []
    for i in range(count):
        part = prices.iloc[edges[i] : edges[i + 1]].copy().reset_index(drop=True)
        if len(part) < 40:
            raise ValueError("A chronological fold is too short")
        folds.append(part)
    return folds


def _safe_float(value) -> float:
    value = float(value)
    return value if np.isfinite(value) else float("nan")


def evaluate_weights(
    prices: pd.DataFrame,
    folds: list[pd.DataFrame],
    weights: dict[str, float],
    *,
    monthly: float,
    rebalance_months: int,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> dict:
    """Run one candidate allocation across full history and all folds."""
    scfg = StrategyConfig(
        weights=weights,
        monthly_contribution=monthly,
        rebalance_months=rebalance_months,
        commission_rate=commission,
        min_commission=min_commission,
        lot_sizes=lot_sizes,
    )
    full = run_strategy(prices, scfg).summary

    fold_xirrs: list[float] = []
    fold_dds: list[float] = []
    for fold in folds:
        summary = run_strategy(fold, scfg).summary
        fold_xirrs.append(_safe_float(summary["xirr"]))
        fold_dds.append(_safe_float(summary["max_drawdown"]))

    finite_xirr = np.asarray([v for v in fold_xirrs if np.isfinite(v)], dtype=float)
    finite_dd = np.asarray([v for v in fold_dds if np.isfinite(v)], dtype=float)

    row: dict[str, float | int | str] = {}
    for symbol, weight in weights.items():
        row[f"weight_{symbol}"] = weight

    row.update(
        {
            "full_xirr": _safe_float(full["xirr"]),
            "full_twr": _safe_float(full["annualized_twr"]),
            "full_sharpe": _safe_float(full["sharpe"]),
            "full_max_drawdown": _safe_float(full["max_drawdown"]),
            "full_final_value": _safe_float(full["final_value"]),
            "full_total_fees": _safe_float(full["total_fees"]),
            "full_trade_count": int(full["trade_count"]),
            "worst_fold_xirr": float(np.min(finite_xirr)) if len(finite_xirr) else float("nan"),
            "mean_fold_xirr": float(np.mean(finite_xirr)) if len(finite_xirr) else float("nan"),
            "fold_xirr_std": float(np.std(finite_xirr, ddof=0)) if len(finite_xirr) else float("nan"),
            "worst_fold_drawdown": float(np.min(finite_dd)) if len(finite_dd) else float("nan"),
            "hhi": float(sum(weight * weight for weight in weights.values())),
        }
    )
    for idx, value in enumerate(fold_xirrs, start=1):
        row[f"fold_{idx}_xirr"] = value
    return row


def _percentile_rank(series: pd.Series, *, higher_is_better: bool) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    finite = values.dropna()
    if finite.empty:
        return pd.Series(0.0, index=series.index)
    span = max(float(finite.max() - finite.min()), 1e-9)
    if higher_is_better:
        filled = values.fillna(float(finite.min()) - span)
        return filled.rank(method="average", pct=True, ascending=True)
    filled = values.fillna(float(finite.max()) + span)
    return (-filled).rank(method="average", pct=True, ascending=True)


def rank_results(results: pd.DataFrame) -> pd.DataFrame:
    """Add transparent multi-objective rank components and robust score."""
    ranked = results.copy()
    ranked["rank_full_xirr"] = _percentile_rank(ranked["full_xirr"], higher_is_better=True)
    ranked["rank_full_sharpe"] = _percentile_rank(ranked["full_sharpe"], higher_is_better=True)
    ranked["rank_worst_fold_xirr"] = _percentile_rank(
        ranked["worst_fold_xirr"], higher_is_better=True
    )
    ranked["rank_mean_fold_xirr"] = _percentile_rank(
        ranked["mean_fold_xirr"], higher_is_better=True
    )
    ranked["rank_drawdown"] = _percentile_rank(
        ranked["full_max_drawdown"], higher_is_better=True
    )
    ranked["rank_stability"] = _percentile_rank(
        ranked["fold_xirr_std"], higher_is_better=False
    )
    ranked["rank_diversification"] = _percentile_rank(
        ranked["hhi"], higher_is_better=False
    )

    ranked["robust_score"] = (
        0.25 * ranked["rank_full_xirr"]
        + 0.15 * ranked["rank_full_sharpe"]
        + 0.25 * ranked["rank_worst_fold_xirr"]
        + 0.10 * ranked["rank_mean_fold_xirr"]
        + 0.15 * ranked["rank_drawdown"]
        + 0.05 * ranked["rank_stability"]
        + 0.05 * ranked["rank_diversification"]
    )
    return ranked.sort_values(
        ["robust_score", "worst_fold_xirr", "full_xirr"], ascending=False
    ).reset_index(drop=True)


def consensus_candidate(ranked: pd.DataFrame, symbols: list[str], top_n: int = 20) -> tuple[pd.Series, dict[str, float]]:
    """Find the actual grid candidate closest to the center of the top region."""
    top = ranked.head(max(1, min(top_n, len(ranked))))
    center = {symbol: float(top[f"weight_{symbol}"].mean()) for symbol in symbols}

    distance = pd.Series(0.0, index=top.index)
    for symbol in symbols:
        distance += (top[f"weight_{symbol}"] - center[symbol]) ** 2
    chosen = top.loc[distance.idxmin()]
    return chosen, center


def _fmt_pct(value: float) -> str:
    return "n/a" if not np.isfinite(value) else f"{value:.2%}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="探索多ETF定投 + 再平衡的稳健目标权重")
    parser.add_argument(
        "--symbols",
        default=",".join(default_symbols()),
        help="逗号分隔 ETF 列表；默认读取 config.DEFAULT_PORTFOLIO 的当前 ETF universe",
    )
    parser.add_argument("--step", type=float, default=0.05, help="权重步长，默认 5%%")
    parser.add_argument("--min-weight", type=float, default=0.10, help="未单独配置标的的最低权重")
    parser.add_argument("--max-weight", type=float, default=0.50, help="未单独配置标的的最高权重")
    parser.add_argument("--folds", type=int, default=3, help="时间稳定性分段数")
    parser.add_argument("--top", type=int, default=20, help="输出前 N 个候选")
    parser.add_argument("--monthly", type=float, default=cfg.MONTHLY_CONTRIBUTION)
    parser.add_argument("--rebalance-months", type=int, default=cfg.REBALANCE_MONTHS)
    parser.add_argument("--start", default=cfg.START_DATE)
    parser.add_argument("--end", default=None)
    parser.add_argument("--adjust", choices=["actual", "forward"], default=cfg.PRICE_ADJUST)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--commission", type=float, default=cfg.COMMISSION)
    parser.add_argument("--min-commission", type=float, default=cfg.MIN_COMMISSION)
    parser.add_argument("--lot-sizes", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = parse_symbols(args.symbols)
    if args.monthly <= 0:
        raise ValueError("--monthly must be > 0")
    if args.rebalance_months < 0:
        raise ValueError("--rebalance-months must be >= 0")
    if args.top <= 0:
        raise ValueError("--top must be > 0")

    bounds = effective_weight_bounds(
        symbols,
        min_weight=args.min_weight,
        max_weight=args.max_weight,
    )
    candidates = generate_weight_grid(
        symbols,
        step=args.step,
        min_weight=args.min_weight,
        max_weight=args.max_weight,
        symbol_bounds=bounds,
    )
    lot_sizes = parse_lot_sizes(args.lot_sizes, symbols)
    prices = load_price_table(
        symbols,
        start=args.start,
        end=args.end,
        adjust=args.adjust,
        refresh=args.refresh,
    )
    folds = chronological_folds(prices, args.folds)

    print(f"搜索 {len(candidates)} 组权重 | step={args.step:.1%} | folds={args.folds}")
    print("权重边界:")
    for symbol in symbols:
        lo, hi = bounds[symbol]
        print(f"  {symbol}: {lo:.0%}~{hi:.0%}")
    print(
        f"共同数据区间: {prices['date'].iloc[0].date()} ~ "
        f"{prices['date'].iloc[-1].date()} ({len(prices)} 天)"
    )

    rows = []
    for idx, weights in enumerate(candidates, start=1):
        rows.append(
            evaluate_weights(
                prices,
                folds,
                weights,
                monthly=args.monthly,
                rebalance_months=args.rebalance_months,
                commission=args.commission,
                min_commission=args.min_commission,
                lot_sizes=lot_sizes,
            )
        )
        if idx % 50 == 0 or idx == len(candidates):
            print(f"  已完成 {idx}/{len(candidates)}")

    ranked = rank_results(pd.DataFrame(rows))
    top = ranked.head(min(args.top, len(ranked))).copy()
    recommendation, center = consensus_candidate(ranked, symbols, top_n=args.top)

    ranked.to_csv(OUTPUT_DIR / "weight_sweep_results.csv", index=False, encoding="utf-8-sig")
    top.to_csv(OUTPUT_DIR / "weight_sweep_top.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([recommendation]).to_csv(
        OUTPUT_DIR / "weight_sweep_recommendation.csv", index=False, encoding="utf-8-sig"
    )

    display_cols = [f"weight_{s}" for s in symbols] + [
        "robust_score",
        "full_xirr",
        "worst_fold_xirr",
        "full_sharpe",
        "full_max_drawdown",
        "fold_xirr_std",
    ]
    print("\n=== 稳健排名 Top 10 ===")
    with pd.option_context("display.max_columns", None, "display.width", 180):
        print(top[display_cols].head(10).to_string(index=False))

    print("\n=== Top 区域中心 ===")
    for symbol in symbols:
        print(f"{symbol}: {center[symbol]:.1%}")

    print("\n=== 推荐网格候选（最接近 Top 区域中心） ===")
    for symbol in symbols:
        print(f"{symbol}: {float(recommendation[f'weight_{symbol}']):.1%}")
    print(
        "指标: "
        f"score={float(recommendation['robust_score']):.3f}, "
        f"XIRR={_fmt_pct(float(recommendation['full_xirr']))}, "
        f"worst-fold XIRR={_fmt_pct(float(recommendation['worst_fold_xirr']))}, "
        f"maxDD={_fmt_pct(float(recommendation['full_max_drawdown']))}"
    )
    print(
        "\n输出: weight_sweep_results.csv / weight_sweep_top.csv / "
        "weight_sweep_recommendation.csv"
    )


if __name__ == "__main__":
    main()
