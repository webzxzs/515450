#!/usr/bin/env python3
"""Explore target weights together with contribution/rebalancing policies.

The 25/25/25/25 portfolio is treated only as a benchmark.  Weight discovery
still spans the full bounded grid.  To keep the joint search interpretable, the
script uses two stages:

1. Sweep the complete weight grid twice using a common 3-month rebalance rule:
   once with target-split DCA and once with underweight-directed DCA.  Keep the
   robust top region from both searches.
2. Evaluate the union of those weight candidates across periodic rebalance
   cadences and drift-threshold policies, using chronological folds again.

This is intentionally a robustness search, not a precision optimizer.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
from adaptive_strategy import AdaptiveStrategyConfig, run_adaptive_strategy
from backtest import load_price_table, parse_lot_sizes
from weight_sweep import (
    chronological_folds,
    default_symbols,
    generate_weight_grid,
    rank_results,
)


OUTPUT_DIR = Path(__file__).resolve().parent


def _safe_float(value) -> float:
    value = float(value)
    return value if np.isfinite(value) else float("nan")


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


def evaluate_adaptive(
    prices: pd.DataFrame,
    folds: list[pd.DataFrame],
    weights: dict[str, float],
    *,
    monthly: float,
    contribution_mode: str,
    rebalance_rule: str,
    rebalance_months: int,
    rebalance_threshold: float,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> dict:
    scfg = AdaptiveStrategyConfig(
        weights=weights,
        monthly_contribution=monthly,
        commission_rate=commission,
        min_commission=min_commission,
        lot_sizes=lot_sizes,
        contribution_mode=contribution_mode,
        rebalance_rule=rebalance_rule,
        rebalance_months=rebalance_months,
        rebalance_threshold=rebalance_threshold,
    )
    full = run_adaptive_strategy(prices, scfg).summary

    fold_xirrs: list[float] = []
    fold_dds: list[float] = []
    for fold in folds:
        summary = run_adaptive_strategy(fold, scfg).summary
        fold_xirrs.append(_safe_float(summary["xirr"]))
        fold_dds.append(_safe_float(summary["max_drawdown"]))

    finite_xirr = np.asarray([v for v in fold_xirrs if np.isfinite(v)], dtype=float)
    finite_dd = np.asarray([v for v in fold_dds if np.isfinite(v)], dtype=float)

    row: dict[str, float | int | str | bool] = {
        "contribution_mode": contribution_mode,
        "rebalance_rule": rebalance_rule,
        "rebalance_months": rebalance_months,
        "rebalance_threshold": rebalance_threshold,
    }
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
            "full_rebalance_events": int(full["rebalance_events"]),
            "full_total_traded_gross": _safe_float(full["total_traded_gross"]),
            "mean_monthly_drift": _safe_float(full["mean_monthly_max_weight_drift"]),
            "max_monthly_drift": _safe_float(full["max_monthly_max_weight_drift"]),
            "ending_drift": _safe_float(full["ending_max_weight_drift"]),
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


def policy_rank(results: pd.DataFrame) -> pd.DataFrame:
    """Rank joint policy candidates without letting turnover dominate returns."""
    ranked = rank_results(results)
    ranked["rank_fees"] = _percentile_rank(ranked["full_total_fees"], higher_is_better=False)
    ranked["rank_drift"] = _percentile_rank(ranked["mean_monthly_drift"], higher_is_better=False)
    ranked["policy_score"] = (
        0.90 * ranked["robust_score"]
        + 0.05 * ranked["rank_fees"]
        + 0.05 * ranked["rank_drift"]
    )
    return ranked.sort_values(
        ["policy_score", "worst_fold_xirr", "full_xirr"],
        ascending=False,
    ).reset_index(drop=True)


def _weight_key(weights: dict[str, float], symbols: list[str]) -> tuple[float, ...]:
    return tuple(round(float(weights[s]), 10) for s in symbols)


def _row_weights(row: pd.Series, symbols: list[str]) -> dict[str, float]:
    return {symbol: float(row[f"weight_{symbol}"]) for symbol in symbols}


def select_seed_weights(
    prices: pd.DataFrame,
    folds: list[pd.DataFrame],
    candidates: list[dict[str, float]],
    *,
    symbols: list[str],
    seed_top: int,
    monthly: float,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> tuple[list[dict[str, float]], pd.DataFrame]:
    """Search the full grid under both contribution styles and union the top regions."""
    stage_rows: list[dict] = []
    for mode in ("target", "underweight"):
        for idx, weights in enumerate(candidates, start=1):
            row = evaluate_adaptive(
                prices,
                folds,
                weights,
                monthly=monthly,
                contribution_mode=mode,
                rebalance_rule="periodic",
                rebalance_months=3,
                rebalance_threshold=0.05,
                commission=commission,
                min_commission=min_commission,
                lot_sizes=lot_sizes,
            )
            row["seed_mode"] = mode
            stage_rows.append(row)
            if idx % 100 == 0 or idx == len(candidates):
                print(f"  seed {mode}: {idx}/{len(candidates)}")

    stage = pd.DataFrame(stage_rows)
    selected: dict[tuple[float, ...], dict[str, float]] = {}
    ranked_parts: list[pd.DataFrame] = []
    for mode in ("target", "underweight"):
        part = rank_results(stage[stage["seed_mode"] == mode].copy())
        ranked_parts.append(part)
        for _, row in part.head(seed_top).iterrows():
            weights = _row_weights(row, symbols)
            selected[_weight_key(weights, symbols)] = weights

    # Equal weight is retained only as a reference candidate when it lies on the
    # search grid; it is never used to constrain or center the discovered weights.
    equal = {symbol: 1.0 / len(symbols) for symbol in symbols}
    candidate_keys = {_weight_key(weights, symbols) for weights in candidates}
    if _weight_key(equal, symbols) in candidate_keys:
        selected[_weight_key(equal, symbols)] = equal

    return list(selected.values()), pd.concat(ranked_parts, ignore_index=True)


def build_policy_variants(
    periodic_months: list[int],
    thresholds: list[float],
) -> list[dict[str, float | int | str]]:
    variants: list[dict[str, float | int | str]] = []
    for mode in ("target", "underweight"):
        variants.append(
            {
                "policy": f"{mode}_none",
                "contribution_mode": mode,
                "rebalance_rule": "none",
                "rebalance_months": 0,
                "rebalance_threshold": 0.0,
            }
        )
        for months in periodic_months:
            variants.append(
                {
                    "policy": f"{mode}_periodic_{months}m",
                    "contribution_mode": mode,
                    "rebalance_rule": "periodic",
                    "rebalance_months": months,
                    "rebalance_threshold": 0.0,
                }
            )
        for threshold in thresholds:
            pct = int(round(threshold * 100))
            variants.append(
                {
                    "policy": f"{mode}_threshold_{pct}pct",
                    "contribution_mode": mode,
                    "rebalance_rule": "threshold",
                    "rebalance_months": 0,
                    "rebalance_threshold": threshold,
                }
            )
    return variants


def summarize_policies(ranked: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for policy, part in ranked.groupby("policy", sort=False):
        rows.append(
            {
                "policy": policy,
                "candidate_weights": int(len(part)),
                "mean_policy_score": float(part["policy_score"].mean()),
                "median_policy_score": float(part["policy_score"].median()),
                "best_policy_score": float(part["policy_score"].max()),
                "median_full_xirr": float(part["full_xirr"].median()),
                "median_worst_fold_xirr": float(part["worst_fold_xirr"].median()),
                "median_sharpe": float(part["full_sharpe"].median()),
                "median_max_drawdown": float(part["full_max_drawdown"].median()),
                "median_fees": float(part["full_total_fees"].median()),
                "median_rebalance_events": float(part["full_rebalance_events"].median()),
                "median_monthly_drift": float(part["mean_monthly_drift"].median()),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["median_policy_score", "median_worst_fold_xirr"], ascending=False
    ).reset_index(drop=True)


def top_region_summary(ranked: pd.DataFrame, symbols: list[str], top_n: int) -> pd.DataFrame:
    top = ranked.head(max(1, min(top_n, len(ranked))))
    row: dict[str, float | int | str] = {"top_n": int(len(top))}
    for symbol in symbols:
        col = f"weight_{symbol}"
        row[f"mean_{col}"] = float(top[col].mean())
        row[f"std_{col}"] = float(top[col].std(ddof=0))
        row[f"min_{col}"] = float(top[col].min())
        row[f"max_{col}"] = float(top[col].max())

    policy_counts = Counter(top["policy"].astype(str))
    mode_counts = Counter(top["contribution_mode"].astype(str))
    row["most_common_policy"] = policy_counts.most_common(1)[0][0]
    row["most_common_policy_share"] = policy_counts.most_common(1)[0][1] / len(top)
    row["underweight_share"] = mode_counts.get("underweight", 0) / len(top)
    return pd.DataFrame([row])


def _parse_int_list(spec: str) -> list[int]:
    values = sorted({int(x.strip()) for x in spec.split(",") if x.strip()})
    if not values or any(v <= 0 for v in values):
        raise ValueError("periodic months must be positive integers")
    return values


def _parse_float_list(spec: str) -> list[float]:
    values = sorted({float(x.strip()) for x in spec.split(",") if x.strip()})
    if not values or any(v <= 0 or v >= 1 for v in values):
        raise ValueError("thresholds must be decimal fractions in (0, 1)")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="联合探索 ETF 权重、定投资金方向与再平衡规则")
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--min-weight", type=float, default=0.10)
    parser.add_argument("--max-weight", type=float, default=0.50)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--seed-top", type=int, default=15, help="两种定投方式各保留多少个权重候选")
    parser.add_argument("--top", type=int, default=30, help="最终 Top 区域大小")
    parser.add_argument("--periodic-months", default="1,3,6,12")
    parser.add_argument("--thresholds", default="0.03,0.05,0.10")
    parser.add_argument("--monthly", type=float, default=cfg.MONTHLY_CONTRIBUTION)
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
    if args.seed_top <= 0 or args.top <= 0:
        raise ValueError("--seed-top and --top must be > 0")

    symbols = default_symbols()
    periodic_months = _parse_int_list(args.periodic_months)
    thresholds = _parse_float_list(args.thresholds)
    weights_grid = generate_weight_grid(
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
    folds = chronological_folds(prices, args.folds)

    print(
        f"全权重网格: {len(weights_grid)} | {args.min_weight:.0%}~{args.max_weight:.0%} | "
        f"step={args.step:.1%} | adjust={args.adjust}"
    )
    print("阶段 1：分别寻找 target DCA 与 underweight DCA 的稳健权重区域")
    seed_weights, seed_rankings = select_seed_weights(
        prices,
        folds,
        weights_grid,
        symbols=symbols,
        seed_top=args.seed_top,
        monthly=args.monthly,
        commission=args.commission,
        min_commission=args.min_commission,
        lot_sizes=lot_sizes,
    )
    print(f"阶段 1 合并后保留 {len(seed_weights)} 组独立权重候选")

    policies = build_policy_variants(periodic_months, thresholds)
    print(f"阶段 2：{len(seed_weights)} 权重 × {len(policies)} 策略规则")
    rows: list[dict] = []
    total = len(seed_weights) * len(policies)
    done = 0
    for weights in seed_weights:
        for policy in policies:
            row = evaluate_adaptive(
                prices,
                folds,
                weights,
                monthly=args.monthly,
                contribution_mode=str(policy["contribution_mode"]),
                rebalance_rule=str(policy["rebalance_rule"]),
                rebalance_months=int(policy["rebalance_months"]),
                rebalance_threshold=float(policy["rebalance_threshold"]),
                commission=args.commission,
                min_commission=args.min_commission,
                lot_sizes=lot_sizes,
            )
            row["policy"] = str(policy["policy"])
            equal_weight = 1.0 / len(symbols)
            row["is_equal_weight_benchmark"] = all(
                abs(weights[symbol] - equal_weight) < 1e-9 for symbol in symbols
            )
            rows.append(row)
            done += 1
            if done % 100 == 0 or done == total:
                print(f"  joint: {done}/{total}")

    ranked = policy_rank(pd.DataFrame(rows))
    policy_summary = summarize_policies(ranked)
    region = top_region_summary(ranked, symbols, args.top)

    seed_rankings.to_csv(
        OUTPUT_DIR / "adaptive_seed_weight_rankings.csv", index=False, encoding="utf-8-sig"
    )
    ranked.to_csv(OUTPUT_DIR / "adaptive_policy_results.csv", index=False, encoding="utf-8-sig")
    ranked.head(args.top).to_csv(
        OUTPUT_DIR / "adaptive_policy_top.csv", index=False, encoding="utf-8-sig"
    )
    policy_summary.to_csv(
        OUTPUT_DIR / "adaptive_policy_summary.csv", index=False, encoding="utf-8-sig"
    )
    region.to_csv(
        OUTPUT_DIR / "adaptive_top_region.csv", index=False, encoding="utf-8-sig"
    )

    weight_cols = [f"weight_{s}" for s in symbols]
    display_cols = [
        *weight_cols,
        "policy",
        "policy_score",
        "full_xirr",
        "worst_fold_xirr",
        "full_sharpe",
        "full_max_drawdown",
        "full_total_fees",
        "full_rebalance_events",
        "mean_monthly_drift",
    ]
    print("\n=== 联合排名 Top 15 ===")
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(ranked[display_cols].head(15).to_string(index=False))

    print("\n=== 策略规则稳健性（按候选权重中位数） ===")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(policy_summary.head(12).to_string(index=False))

    print("\n=== Top 区域权重范围 ===")
    r = region.iloc[0]
    for symbol in symbols:
        print(
            f"{symbol}: mean={r[f'mean_weight_{symbol}']:.1%} | "
            f"range={r[f'min_weight_{symbol}']:.0%}~{r[f'max_weight_{symbol}']:.0%} | "
            f"std={r[f'std_weight_{symbol}']:.1%}"
        )
    print(
        f"Top 中 underweight DCA 占比: {float(r['underweight_share']):.0%} | "
        f"最常见规则: {r['most_common_policy']} "
        f"({float(r['most_common_policy_share']):.0%})"
    )
    print("\n等权 25/25/25/25 仅作为 benchmark；联合排名不会以它为搜索中心。")


if __name__ == "__main__":
    main()
