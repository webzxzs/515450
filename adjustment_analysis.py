#!/usr/bin/env python3
"""Compare unadjusted and Longbridge forward-adjusted ETF histories.

Why this exists
---------------
Longbridge documents ``--adjust forward`` as forward-adjusting historical K-line
prices for splits/dividends.  That makes forward-adjusted data the more useful
basis for long-horizon return research, while unadjusted (``actual``) prices are
still useful for checking raw market prices, lot sizing, and fee sensitivity.

This module keeps the two roles explicit instead of silently mixing them:

1. Load the same portfolio on ``actual`` and ``forward`` price bases.
2. Align both histories to the exact same common trading dates.
3. Measure the per-ETF return uplift attributable to adjustment effects.
4. Run the same DCA + periodic-rebalance strategy on both price bases as a
   sensitivity/reconciliation check.

Important limitation
--------------------
The forward-adjusted backtest is a total-return *proxy*.  Its historical prices
are synthetic adjusted prices, so the resulting historical share counts, lot
rounding and fees should not be interpreted as literal broker executions.  The
project does not manufacture dividend cash events when Longbridge does not
provide reliable dividend records for the ETF.
"""

from __future__ import annotations

import argparse
from pathlib import Path

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


OUTPUT_DIR = Path(__file__).resolve().parent
TRADING_DAYS = 242


def align_price_bases(
    actual: pd.DataFrame,
    forward: pd.DataFrame,
    symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return actual/forward tables restricted to exactly matching dates.

    Both inputs must contain ``date`` plus every symbol.  The returned frames
    use the same ordered date index and the original symbol column names so they
    can be passed directly to ``run_strategy``.
    """
    for name, frame in (("actual", actual), ("forward", forward)):
        missing = [c for c in ["date", *symbols] if c not in frame.columns]
        if missing:
            raise ValueError(f"{name} price table missing columns: {missing}")

    a = actual[["date", *symbols]].copy()
    f = forward[["date", *symbols]].copy()
    a["date"] = pd.to_datetime(a["date"])
    f["date"] = pd.to_datetime(f["date"])

    merged = pd.merge(
        a,
        f,
        on="date",
        how="inner",
        suffixes=("__actual", "__forward"),
        validate="one_to_one",
    ).sort_values("date")
    if len(merged) < 2:
        raise ValueError("Need at least two common actual/forward observations")

    actual_out = pd.DataFrame({"date": merged["date"]})
    forward_out = pd.DataFrame({"date": merged["date"]})
    for symbol in symbols:
        actual_out[symbol] = pd.to_numeric(
            merged[f"{symbol}__actual"], errors="coerce"
        )
        forward_out[symbol] = pd.to_numeric(
            merged[f"{symbol}__forward"], errors="coerce"
        )

    valid = actual_out[symbols].notna().all(axis=1) & forward_out[symbols].notna().all(axis=1)
    actual_out = actual_out.loc[valid].reset_index(drop=True)
    forward_out = forward_out.loc[valid].reset_index(drop=True)
    if len(actual_out) < 2:
        raise ValueError("Not enough valid aligned actual/forward prices")
    return actual_out, forward_out


def _annualized_return(first: float, last: float, days: int) -> float:
    if first <= 0 or last <= 0 or days <= 0:
        return float("nan")
    return float((last / first) ** (365.25 / days) - 1.0)


def asset_adjustment_report(
    actual: pd.DataFrame,
    forward: pd.DataFrame,
    symbols: list[str],
    *,
    wedge_threshold: float = 1e-6,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Measure price-return vs forward-adjusted return differences per ETF.

    ``adjustment_days`` counts days where the forward-adjusted return differs
    from the raw-price return by more than ``wedge_threshold``.  The daily wedge
    is useful for locating ex-dividend/split adjustment effects without
    pretending that every wedge can be reconstructed as a cash dividend.
    """
    if wedge_threshold < 0:
        raise ValueError("wedge_threshold must be >= 0")

    actual, forward = align_price_bases(actual, forward, symbols)
    days = max((actual["date"].iloc[-1] - actual["date"].iloc[0]).days, 1)
    rows: list[dict] = []
    wedge_frame = pd.DataFrame({"date": actual["date"]})

    for symbol in symbols:
        a = actual[symbol].astype(float)
        f = forward[symbol].astype(float)
        a_ret = a.pct_change(fill_method=None)
        f_ret = f.pct_change(fill_method=None)
        wedge = f_ret - a_ret

        actual_total = float(a.iloc[-1] / a.iloc[0] - 1.0)
        forward_total = float(f.iloc[-1] / f.iloc[0] - 1.0)
        actual_ann = _annualized_return(float(a.iloc[0]), float(a.iloc[-1]), days)
        forward_ann = _annualized_return(float(f.iloc[0]), float(f.iloc[-1]), days)
        valid_wedge = wedge.replace([np.inf, -np.inf], np.nan).dropna()
        adjustment_mask = valid_wedge.abs() > wedge_threshold

        rows.append(
            {
                "symbol": symbol,
                "start": str(pd.Timestamp(actual["date"].iloc[0]).date()),
                "end": str(pd.Timestamp(actual["date"].iloc[-1]).date()),
                "observations": int(len(actual)),
                "actual_total_return": actual_total,
                "forward_total_return": forward_total,
                "total_return_uplift": forward_total - actual_total,
                "actual_annualized_return": actual_ann,
                "forward_annualized_return": forward_ann,
                "annualized_return_uplift": forward_ann - actual_ann,
                "adjustment_days": int(adjustment_mask.sum()),
                "max_abs_daily_adjustment_wedge": (
                    float(valid_wedge.abs().max()) if len(valid_wedge) else float("nan")
                ),
                "mean_abs_daily_adjustment_wedge": (
                    float(valid_wedge.abs().mean()) if len(valid_wedge) else float("nan")
                ),
                "start_forward_to_actual_ratio": float(f.iloc[0] / a.iloc[0]),
                "end_forward_to_actual_ratio": float(f.iloc[-1] / a.iloc[-1]),
            }
        )
        wedge_frame[f"actual_return_{symbol}"] = a_ret
        wedge_frame[f"forward_return_{symbol}"] = f_ret
        wedge_frame[f"adjustment_wedge_{symbol}"] = wedge
        wedge_frame[f"forward_to_actual_ratio_{symbol}"] = f / a

    return pd.DataFrame(rows), wedge_frame


def strategy_basis_report(
    actual: pd.DataFrame,
    forward: pd.DataFrame,
    weights: dict[str, float],
    *,
    monthly: float,
    rebalance_months: int,
    commission: float,
    min_commission: float,
    lot_sizes: dict[str, int],
) -> pd.DataFrame:
    """Run identical strategy settings on actual and forward-adjusted prices."""
    symbols = list(weights)
    actual, forward = align_price_bases(actual, forward, symbols)
    scfg = StrategyConfig(
        weights=weights,
        monthly_contribution=monthly,
        rebalance_months=rebalance_months,
        commission_rate=commission,
        min_commission=min_commission,
        lot_sizes=lot_sizes,
    )
    actual_result = run_strategy(actual, scfg)
    forward_result = run_strategy(forward, scfg)

    metrics = [
        "total_contribution",
        "final_value",
        "pnl",
        "xirr",
        "annualized_twr",
        "sharpe",
        "max_drawdown",
        "total_fees",
        "trade_count",
        "rebalance_events",
        "rebalance_trade_count",
        "ending_cash",
    ]
    rows = []
    for metric in metrics:
        a = float(actual_result.summary[metric])
        f = float(forward_result.summary[metric])
        rows.append(
            {
                "metric": metric,
                "actual": a,
                "forward_adjusted_proxy": f,
                "forward_minus_actual": f - a,
            }
        )
    return pd.DataFrame(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="对比 Longbridge actual 与 forward 前复权口径"
    )
    parser.add_argument("--portfolio", default=cfg.DEFAULT_PORTFOLIO)
    parser.add_argument("--monthly", type=float, default=cfg.MONTHLY_CONTRIBUTION)
    parser.add_argument("--rebalance-months", type=int, default=cfg.REBALANCE_MONTHS)
    parser.add_argument("--start", default=cfg.START_DATE)
    parser.add_argument("--end", default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--commission", type=float, default=cfg.COMMISSION)
    parser.add_argument("--min-commission", type=float, default=cfg.MIN_COMMISSION)
    parser.add_argument("--lot-sizes", default="")
    parser.add_argument(
        "--wedge-threshold",
        type=float,
        default=1e-6,
        help="actual/forward 单日收益差超过该阈值时记为 adjustment day",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.monthly <= 0:
        raise ValueError("--monthly must be > 0")
    if args.rebalance_months < 0:
        raise ValueError("--rebalance-months must be >= 0")

    weights = parse_portfolio(args.portfolio)
    symbols = list(weights)
    lot_sizes = parse_lot_sizes(args.lot_sizes, symbols)

    print("加载 actual 原始价格...")
    actual = load_price_table(
        symbols,
        start=args.start,
        end=args.end,
        adjust="actual",
        refresh=args.refresh,
    )
    print("加载 forward 前复权价格（Longbridge：splits/dividends adjusted）...")
    forward = load_price_table(
        symbols,
        start=args.start,
        end=args.end,
        adjust="forward",
        refresh=args.refresh,
    )
    actual, forward = align_price_bases(actual, forward, symbols)

    assets, wedges = asset_adjustment_report(
        actual,
        forward,
        symbols,
        wedge_threshold=args.wedge_threshold,
    )
    portfolio = strategy_basis_report(
        actual,
        forward,
        weights,
        monthly=args.monthly,
        rebalance_months=args.rebalance_months,
        commission=args.commission,
        min_commission=args.min_commission,
        lot_sizes=lot_sizes,
    )

    assets.to_csv(OUTPUT_DIR / "adjustment_assets.csv", index=False, encoding="utf-8-sig")
    wedges.to_csv(OUTPUT_DIR / "adjustment_daily_wedges.csv", index=False, encoding="utf-8-sig")
    portfolio.to_csv(
        OUTPUT_DIR / "adjustment_portfolio_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("\n=== ETF 复权影响 ===")
    show = assets[
        [
            "symbol",
            "actual_total_return",
            "forward_total_return",
            "annualized_return_uplift",
            "adjustment_days",
            "max_abs_daily_adjustment_wedge",
        ]
    ].copy()
    with pd.option_context("display.width", 180, "display.max_columns", None):
        print(show.to_string(index=False))

    print("\n=== 组合 actual vs forward-adjusted proxy ===")
    with pd.option_context("display.width", 180, "display.max_columns", None):
        print(portfolio.to_string(index=False))

    print(
        "\n解释：forward-adjusted 是长期总收益研究口径；actual 是原始市场价格口径。"
        "前复权回测中的历史成交价/份额是代理值，不应当作真实券商成交记录。"
    )
    print(
        "输出: adjustment_assets.csv / adjustment_daily_wedges.csv / "
        "adjustment_portfolio_comparison.csv"
    )


if __name__ == "__main__":
    main()
