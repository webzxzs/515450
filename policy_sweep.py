#!/usr/bin/env python3
"""Jointly explore ETF target weights and execution policies.

25/25/25/25 is never used as a search center. With the default 5% grid the
script evaluates all 375 bounded weight combinations under every policy.

To keep runtime practical without letting one rebalance style pre-filter the
weights for every other style, the search is two-stage:

1. Full-history screen: complete weight grid x every contribution/rebalance
   policy. Each policy keeps its own top candidates.
2. Robust validation: only those per-policy candidates are rerun over
   chronological folds and ranked by the same multi-objective robustness logic
   used by ``weight_sweep.py`` plus small fee/drift tie-breakers.
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
from weight_sweep import chronological_folds, default_symbols, generate_weight_grid, rank_results


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


def _strategy_config(
    weights: dict[str, float],
    policy: dict[str, float | int | str],
    *,
    monthly: float,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> AdaptiveStrategyConfig:
    return AdaptiveStrategyConfig(
        weights=weights,
        monthly_contribution=monthly,
        commission_rate=commission,
        min_commission=min_commission,
        lot_sizes=lot_sizes,
        contribution_mode=str(policy["contribution_mode"]),
        rebalance_rule=str(policy["rebalance_rule"]),
        rebalance_months=int(policy["rebalance_months"]),
        rebalance_threshold=float(policy["rebalance_threshold"]),
    )


def evaluate_full(
    prices: pd.DataFrame,
    weights: dict[str, float],
    policy: dict[str, float | int | str],
    *,
    monthly: float,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> dict:
    scfg = _strategy_config(
        weights,
        policy,
        monthly=monthly,
        commission=commission,
        min_commission=min_commission,
        lot_sizes=lot_sizes,
    )
    full = run_adaptive_strategy(prices, scfg).summary

    row: dict[str, float | int | str | bool] = {
        "policy": str(policy["policy"]),
        "contribution_mode": str(policy["contribution_mode"]),
        "rebalance_rule": str(policy["rebalance_rule"]),
        "rebalance_months": int(policy["rebalance_months"]),
        "rebalance_threshold": float(policy["rebalance_threshold"]),
    }
    for symbol, weight in weights.items():
        row[f"weight_{symbol}"] = float(weight)

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
            "hhi": float(sum(float(weight) ** 2 for weight in weights.values())),
        }
    )
    return row


def screen_rank(results: pd.DataFrame) -> pd.DataFrame:
    """Full-history screen used only to choose fold-validation candidates."""
    ranked = results.copy()
    ranked["screen_rank_xirr"] = _percentile_rank(ranked["full_xirr"], higher_is_better=True)
    ranked["screen_rank_sharpe"] = _percentile_rank(
        ranked["full_sharpe"], higher_is_better=True
    )
    ranked["screen_rank_drawdown"] = _percentile_rank(
        ranked["full_max_drawdown"], higher_is_better=True
    )
    ranked["screen_rank_diversification"] = _percentile_rank(
        ranked["hhi"], higher_is_better=False
    )
    ranked["screen_rank_fees"] = _percentile_rank(
        ranked["full_total_fees"], higher_is_better=False
    )
    ranked["screen_rank_drift"] = _percentile_rank(
        ranked["mean_monthly_drift"], higher_is_better=False
    )
    ranked["screen_score"] = (
        0.35 * ranked["screen_rank_xirr"]
        + 0.25 * ranked["screen_rank_sharpe"]
        + 0.20 * ranked["screen_rank_drawdown"]
        + 0.10 * ranked["screen_rank_diversification"]
        + 0.05 * ranked["screen_rank_fees"]
        + 0.05 * ranked["screen_rank_drift"]
    )
    return ranked.sort_values(
        ["screen_score", "full_xirr", "full_sharpe"], ascending=False
    ).reset_index(drop=True)


def select_fold_candidates(screen: pd.DataFrame, top_per_policy: int) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for _, part in screen.groupby("policy", sort=False):
        parts.append(screen_rank(part).head(top_per_policy))
    return pd.concat(parts, ignore_index=True)


def _row_weights(row: pd.Series, symbols: list[str]) -> dict[str, float]:
    return {symbol: float(row[f"weight_{symbol}"]) for symbol in symbols}


def _row_policy(row: pd.Series) -> dict[str, float | int | str]:
    return {
        "policy": str(row["policy"]),
        "contribution_mode": str(row["contribution_mode"]),
        "rebalance_rule": str(row["rebalance_rule"]),
        "rebalance_months": int(row["rebalance_months"]),
        "rebalance_threshold": float(row["rebalance_threshold"]),
    }


def add_fold_validation(
    selected: pd.DataFrame,
    folds: list[pd.DataFrame],
    *,
    symbols: list[str],
    monthly: float,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> pd.DataFrame:
    rows: list[dict] = []
    for _, source in selected.iterrows():
        weights = _row_weights(source, symbols)
        policy = _row_policy(source)
        scfg = _strategy_config(
            weights,
            policy,
            monthly=monthly,
            commission=commission,
            min_commission=min_commission,
            lot_sizes=lot_sizes,
        )

        fold_xirrs: list[float] = []
        fold_dds: list[float] = []
        for fold in folds:
            summary = run_adaptive_strategy(fold, scfg).summary
            fold_xirrs.append(_safe_float(summary["xirr"]))
            fold_dds.append(_safe_float(summary["max_drawdown"]))

        finite_xirr = np.asarray([v for v in fold_xirrs if np.isfinite(v)], dtype=float)
        finite_dd = np.asarray([v for v in fold_dds if np.isfinite(v)], dtype=float)
        row = source.to_dict()
        row.update(
            {
                "worst_fold_xirr": float(np.min(finite_xirr)) if len(finite_xirr) else float("nan"),
                "mean_fold_xirr": float(np.mean(finite_xirr)) if len(finite_xirr) else float("nan"),
                "fold_xirr_std": float(np.std(finite_xirr, ddof=0)) if len(finite_xirr) else float("nan"),
                "worst_fold_drawdown": float(np.min(finite_dd)) if len(finite_dd) else float("nan"),
            }
        )
        for idx, value in enumerate(fold_xirrs, start=1):
            row[f"fold_{idx}_xirr"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def policy_rank(results: pd.DataFrame) -> pd.DataFrame:
    ranked = rank_results(results)
    ranked["rank_fees"] = _percentile_rank(
        ranked["full_total_fees"], higher_is_better=False
    )
    ranked["rank_drift"] = _percentile_rank(
        ranked["mean_monthly_drift"], higher_is_better=False
    )
    ranked["policy_score"] = (
        0.90 * ranked["robust_score"]
        + 0.05 * ranked["rank_fees"]
        + 0.05 * ranked["rank_drift"]
    )
    return ranked.sort_values(
        ["policy_score", "worst_fold_xirr", "full_xirr"], ascending=False
    ).reset_index(drop=True)


def summarize_policies(ranked: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for policy, part in ranked.groupby("policy", sort=False):
        rows.append(
            {
                "policy": policy,
                "validated_candidates": int(len(part)),
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
    parser.add_argument(
        "--screen-top-per-policy",
        type=int,
        default=15,
        help="完整网格筛选后，每种执行规则进入分段验证的候选数",
    )
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
    if args.screen_top_per_policy <= 0 or args.top <= 0:
        raise ValueError("--screen-top-per-policy and --top must be > 0")

    symbols = default_symbols()
    periodic_months = _parse_int_list(args.periodic_months)
    thresholds = _parse_float_list(args.thresholds)
    policies = build_policy_variants(periodic_months, thresholds)
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

    total_screen = len(weights_grid) * len(policies)
    print(
        f"阶段 1 完整联合筛选: {len(weights_grid)} 权重 × {len(policies)} 规则 "
        f"= {total_screen} 组 | adjust={args.adjust}"
    )
    screen_rows: list[dict] = []
    done = 0
    equal_weight = 1.0 / len(symbols)
    for policy in policies:
        for weights in weights_grid:
            row = evaluate_full(
                prices,
                weights,
                policy,
                monthly=args.monthly,
                commission=args.commission,
                min_commission=args.min_commission,
                lot_sizes=lot_sizes,
            )
            row["is_equal_weight_benchmark"] = all(
                abs(weights[symbol] - equal_weight) < 1e-9 for symbol in symbols
            )
            screen_rows.append(row)
            done += 1
            if done % 250 == 0 or done == total_screen:
                print(f"  screen: {done}/{total_screen}")

    screen = pd.DataFrame(screen_rows)
    selected = select_fold_candidates(screen, args.screen_top_per_policy)
    print(
        f"阶段 2 分段稳健性验证: {len(selected)} 组 "
        f"({args.screen_top_per_policy} / policy × {len(policies)} policies)"
    )
    validated = add_fold_validation(
        selected,
        folds,
        symbols=symbols,
        monthly=args.monthly,
        commission=args.commission,
        min_commission=args.min_commission,
        lot_sizes=lot_sizes,
    )
    ranked = policy_rank(validated)
    policy_summary = summarize_policies(ranked)
    region = top_region_summary(ranked, symbols, args.top)

    screen.to_csv(
        OUTPUT_DIR / "adaptive_joint_screen.csv", index=False, encoding="utf-8-sig"
    )
    ranked.to_csv(
        OUTPUT_DIR / "adaptive_policy_results.csv", index=False, encoding="utf-8-sig"
    )
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

    print("\n=== 执行规则稳健性（各规则自己的筛选候选） ===")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(policy_summary.to_string(index=False))

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
    print("\n25/25/25/25 只是完整网格中的普通 benchmark 行，不参与设定搜索中心。")


if __name__ == "__main__":
    main()
