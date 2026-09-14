#!/usr/bin/env python3
"""Walk-forward validation for ETF target-weight selection.

Each test window is strictly out-of-sample: candidate weights are ranked using
only the immediately preceding training window. The selected allocation is then
run on the following test window without using any test-period observations in
selection.

This script is a research validator, not a single continuous account simulator.
Each OOS window starts a fresh DCA backtest so that parameter-selection quality
can be compared cleanly across windows. The per-window TWR returns are also
stitched into an aggregate OOS NAV for risk metrics; XIRR is reported per window
rather than falsely compounded across reset accounts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
from backtest import StrategyConfig, load_price_table, parse_lot_sizes, run_strategy
from weight_sweep import (
    consensus_candidate,
    default_symbols,
    evaluate_weights,
    generate_weight_grid,
    rank_results,
)


OUTPUT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train: pd.DataFrame
    test: pd.DataFrame


def build_walk_forward_windows(
    prices: pd.DataFrame,
    *,
    train_years: int = 3,
    test_months: int = 12,
    min_train_days: int = 400,
    min_test_days: int = 40,
) -> list[WalkForwardWindow]:
    """Create chronological train->test windows with no overlap/leakage."""
    if train_years <= 0:
        raise ValueError("train_years must be > 0")
    if test_months <= 0:
        raise ValueError("test_months must be > 0")
    if prices.empty:
        raise ValueError("prices is empty")

    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").reset_index(drop=True)

    first_date = pd.Timestamp(data["date"].iloc[0])
    last_date = pd.Timestamp(data["date"].iloc[-1])
    target_test_start = first_date + pd.DateOffset(years=train_years)

    windows: list[WalkForwardWindow] = []
    while target_test_start <= last_date:
        test_candidates = data.index[data["date"] >= target_test_start]
        if len(test_candidates) == 0:
            break
        test_start = pd.Timestamp(data.loc[test_candidates[0], "date"])
        target_test_end_exclusive = test_start + pd.DateOffset(months=test_months)
        train_start_target = test_start - pd.DateOffset(years=train_years)

        train = data[(data["date"] >= train_start_target) & (data["date"] < test_start)].copy()
        test = data[(data["date"] >= test_start) & (data["date"] < target_test_end_exclusive)].copy()

        if len(train) >= min_train_days and len(test) >= min_test_days:
            train = train.reset_index(drop=True)
            test = test.reset_index(drop=True)
            windows.append(
                WalkForwardWindow(
                    train_start=pd.Timestamp(train["date"].iloc[0]),
                    train_end=pd.Timestamp(train["date"].iloc[-1]),
                    test_start=pd.Timestamp(test["date"].iloc[0]),
                    test_end=pd.Timestamp(test["date"].iloc[-1]),
                    train=train,
                    test=test,
                )
            )

        target_test_start = test_start + pd.DateOffset(months=test_months)

    if not windows:
        raise ValueError(
            "No valid walk-forward windows. Need more common history or shorter training/test periods."
        )
    return windows


def _strategy_config(
    weights: dict[str, float],
    *,
    monthly: float,
    rebalance_months: int,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> StrategyConfig:
    return StrategyConfig(
        weights=weights,
        monthly_contribution=monthly,
        rebalance_months=rebalance_months,
        commission_rate=commission,
        min_commission=min_commission,
        lot_sizes=lot_sizes,
    )


def select_weights_on_training(
    train: pd.DataFrame,
    candidates: list[dict[str, float]],
    *,
    monthly: float,
    rebalance_months: int,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
    folds: int,
    top_n: int,
) -> tuple[dict[str, float], pd.Series, pd.DataFrame]:
    """Rank candidates using training data only and return robust consensus pick."""
    if folds < 2:
        raise ValueError("folds must be >= 2")
    if len(train) < folds * 40:
        raise ValueError("training window too short for requested folds")

    edges = np.linspace(0, len(train), folds + 1, dtype=int)
    train_folds = [
        train.iloc[edges[i] : edges[i + 1]].copy().reset_index(drop=True)
        for i in range(folds)
    ]

    rows = [
        evaluate_weights(
            train,
            train_folds,
            weights,
            monthly=monthly,
            rebalance_months=rebalance_months,
            commission=commission,
            min_commission=min_commission,
            lot_sizes=lot_sizes,
        )
        for weights in candidates
    ]
    ranked = rank_results(pd.DataFrame(rows))
    symbols = list(candidates[0])
    recommendation, _ = consensus_candidate(ranked, symbols, top_n=top_n)
    chosen = {symbol: float(recommendation[f"weight_{symbol}"]) for symbol in symbols}
    return chosen, recommendation, ranked


def _summary_row(prefix: str, summary: dict) -> dict[str, float]:
    keys = [
        "xirr",
        "annualized_twr",
        "sharpe",
        "max_drawdown",
        "final_value",
        "total_fees",
        "trade_count",
    ]
    return {f"{prefix}_{key}": float(summary[key]) for key in keys}


def _aggregate_oos_nav(daily_parts: list[pd.DataFrame]) -> pd.DataFrame:
    """Stitch OOS TWR returns from independent validation windows."""
    rows: list[pd.DataFrame] = []
    nav = 1.0
    for window_no, daily in enumerate(daily_parts, start=1):
        part = daily[["date", "twr_return"]].copy()
        part["window"] = window_no
        part["oos_nav"] = np.nan
        for idx, value in part["twr_return"].items():
            ret = float(value) if np.isfinite(value) else 0.0
            nav *= 1.0 + ret
            part.loc[idx, "oos_nav"] = nav
        rows.append(part)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def summarize_walk_forward(results: pd.DataFrame, oos_nav: pd.DataFrame) -> dict:
    if results.empty:
        raise ValueError("results is empty")

    selected_xirr = pd.to_numeric(results["selected_test_xirr"], errors="coerce")
    equal_xirr = pd.to_numeric(results["equal_test_xirr"], errors="coerce")
    default_xirr = pd.to_numeric(results["default_test_xirr"], errors="coerce")

    summary: dict[str, float | int | str] = {
        "windows": int(len(results)),
        "first_test_start": str(pd.Timestamp(results.iloc[0]["test_start"]).date()),
        "last_test_end": str(pd.Timestamp(results.iloc[-1]["test_end"]).date()),
        "mean_oos_xirr": float(selected_xirr.mean()),
        "median_oos_xirr": float(selected_xirr.median()),
        "worst_oos_xirr": float(selected_xirr.min()),
        "mean_excess_xirr_vs_equal": float((selected_xirr - equal_xirr).mean()),
        "mean_excess_xirr_vs_default": float((selected_xirr - default_xirr).mean()),
        "hit_rate_vs_equal": float((selected_xirr > equal_xirr).mean()),
        "hit_rate_vs_default": float((selected_xirr > default_xirr).mean()),
    }

    if not oos_nav.empty:
        returns = pd.to_numeric(oos_nav["twr_return"], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        nav = pd.to_numeric(oos_nav["oos_nav"], errors="coerce").dropna()
        if len(returns) > 1:
            std = float(returns.std(ddof=1))
            summary["stitched_oos_sharpe"] = (
                float(returns.mean() / std * np.sqrt(242)) if std > 1e-12 else float("nan")
            )
        else:
            summary["stitched_oos_sharpe"] = float("nan")
        if not nav.empty:
            dd = nav / nav.cummax() - 1.0
            summary["stitched_oos_max_drawdown"] = float(dd.min())
            days = max(
                (pd.Timestamp(oos_nav.iloc[-1]["date"]) - pd.Timestamp(oos_nav.iloc[0]["date"])).days,
                1,
            )
            summary["stitched_oos_annualized_twr"] = float(nav.iloc[-1] ** (365.25 / days) - 1.0)

    weight_cols = [c for c in results.columns if c.startswith("selected_weight_")]
    for col in weight_cols:
        values = pd.to_numeric(results[col], errors="coerce")
        suffix = col.removeprefix("selected_weight_")
        summary[f"mean_selected_weight_{suffix}"] = float(values.mean())
        summary[f"std_selected_weight_{suffix}"] = float(values.std(ddof=0))
        summary[f"min_selected_weight_{suffix}"] = float(values.min())
        summary[f"max_selected_weight_{suffix}"] = float(values.max())
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETF 权重 Walk-Forward 样本外验证")
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--min-weight", type=float, default=0.10)
    parser.add_argument("--max-weight", type=float, default=0.50)
    parser.add_argument("--train-years", type=int, default=3)
    parser.add_argument("--test-months", type=int, default=12)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--top", type=int, default=20)
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
    symbols = default_symbols()
    candidates = generate_weight_grid(
        symbols,
        step=args.step,
        min_weight=args.min_weight,
        max_weight=args.max_weight,
    )
    lot_sizes = parse_lot_sizes(args.lot_sizes, symbols)
    prices = load_price_table(
        symbols,
        start=args.start,
        end=args.end,
        adjust=args.adjust,
        refresh=args.refresh,
    )
    windows = build_walk_forward_windows(
        prices,
        train_years=args.train_years,
        test_months=args.test_months,
    )

    default_weights = {
        symbol: weight
        for symbol, weight in zip(symbols, [1.0 / len(symbols)] * len(symbols))
    }
    # Current config is equal weight today, but keep these concepts separate so
    # future config changes still compare both a neutral equal-weight benchmark
    # and the then-current default allocation.
    from backtest import parse_portfolio

    configured_weights = parse_portfolio(cfg.DEFAULT_PORTFOLIO)

    print(
        f"Walk-Forward: {len(candidates)} candidates | train={args.train_years}y | "
        f"test={args.test_months}m | windows={len(windows)}"
    )

    rows: list[dict] = []
    selected_daily_parts: list[pd.DataFrame] = []

    for window_no, window in enumerate(windows, start=1):
        print(
            f"\n[{window_no}/{len(windows)}] train "
            f"{window.train_start.date()}~{window.train_end.date()} -> test "
            f"{window.test_start.date()}~{window.test_end.date()}"
        )
        selected, train_pick, _ = select_weights_on_training(
            window.train,
            candidates,
            monthly=args.monthly,
            rebalance_months=args.rebalance_months,
            commission=args.commission,
            min_commission=args.min_commission,
            lot_sizes=lot_sizes,
            folds=args.folds,
            top_n=args.top,
        )

        selected_result = run_strategy(
            window.test,
            _strategy_config(
                selected,
                monthly=args.monthly,
                rebalance_months=args.rebalance_months,
                commission=args.commission,
                min_commission=args.min_commission,
                lot_sizes=lot_sizes,
            ),
        )
        equal_result = run_strategy(
            window.test,
            _strategy_config(
                default_weights,
                monthly=args.monthly,
                rebalance_months=args.rebalance_months,
                commission=args.commission,
                min_commission=args.min_commission,
                lot_sizes=lot_sizes,
            ),
        )
        configured_result = run_strategy(
            window.test,
            _strategy_config(
                configured_weights,
                monthly=args.monthly,
                rebalance_months=args.rebalance_months,
                commission=args.commission,
                min_commission=args.min_commission,
                lot_sizes=lot_sizes,
            ),
        )
        selected_daily_parts.append(selected_result.daily)

        row: dict[str, float | int | str] = {
            "window": window_no,
            "train_start": window.train_start,
            "train_end": window.train_end,
            "test_start": window.test_start,
            "test_end": window.test_end,
            "train_robust_score": float(train_pick["robust_score"]),
            "train_full_xirr": float(train_pick["full_xirr"]),
            "train_worst_fold_xirr": float(train_pick["worst_fold_xirr"]),
        }
        for symbol, weight in selected.items():
            row[f"selected_weight_{symbol}"] = weight
        row.update(_summary_row("selected_test", selected_result.summary))
        row.update(_summary_row("equal_test", equal_result.summary))
        row.update(_summary_row("default_test", configured_result.summary))
        rows.append(row)

        weights_text = ", ".join(f"{s}={w:.0%}" for s, w in selected.items())
        print(
            f"  selected: {weights_text} | "
            f"OOS XIRR={selected_result.summary['xirr']:.2%} | "
            f"equal={equal_result.summary['xirr']:.2%}"
        )

    results = pd.DataFrame(rows)
    oos_nav = _aggregate_oos_nav(selected_daily_parts)
    summary = summarize_walk_forward(results, oos_nav)

    results.to_csv(OUTPUT_DIR / "walk_forward_windows.csv", index=False, encoding="utf-8-sig")
    oos_nav.to_csv(OUTPUT_DIR / "walk_forward_oos_nav.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([summary]).to_csv(
        OUTPUT_DIR / "walk_forward_summary.csv", index=False, encoding="utf-8-sig"
    )

    print("\n=== Walk-Forward OOS summary ===")
    print(f"windows: {summary['windows']}")
    print(f"mean OOS XIRR: {summary['mean_oos_xirr']:.2%}")
    print(f"worst OOS XIRR: {summary['worst_oos_xirr']:.2%}")
    print(f"hit rate vs equal weight: {summary['hit_rate_vs_equal']:.1%}")
    print(f"mean excess XIRR vs equal: {summary['mean_excess_xirr_vs_equal']:.2%}")
    if "stitched_oos_annualized_twr" in summary:
        print(f"stitched OOS annualized TWR: {summary['stitched_oos_annualized_twr']:.2%}")
        print(f"stitched OOS Sharpe: {summary['stitched_oos_sharpe']:.3f}")
        print(f"stitched OOS maxDD: {summary['stitched_oos_max_drawdown']:.2%}")

    print(
        "\n输出: walk_forward_windows.csv / walk_forward_oos_nav.csv / "
        "walk_forward_summary.csv"
    )


if __name__ == "__main__":
    main()
