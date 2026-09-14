#!/usr/bin/env python3
"""Risk decomposition for the ETF portfolio.

Focuses on whether nominal capital diversification is also risk diversification.
Outputs static and rolling diagnostics from aligned daily ETF returns:

- annualized asset volatility
- correlation matrix
- portfolio volatility
- component risk contribution and risk-share percentages
- diversification ratio
- PCA first-component explained share and loadings
- rolling portfolio volatility, average correlation, PC1 share, and risk concentration
- calendar-year risk snapshots
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
from backtest import load_price_table, parse_portfolio


OUTPUT_DIR = Path(__file__).resolve().parent
TRADING_DAYS = 242


def return_table(prices: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Convert aligned close prices to aligned simple daily returns."""
    missing = [s for s in symbols if s not in prices.columns]
    if missing:
        raise ValueError(f"Missing price columns: {missing}")
    table = prices[["date", *symbols]].copy()
    table["date"] = pd.to_datetime(table["date"])
    values = table[symbols].apply(pd.to_numeric, errors="coerce")
    returns = values.pct_change(fill_method=None)
    returns.insert(0, "date", table["date"])
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    if len(returns) < 20:
        raise ValueError("Not enough return observations")
    return returns


def _normalized_weights(weights: dict[str, float], symbols: list[str]) -> np.ndarray:
    raw = np.array([float(weights[s]) for s in symbols], dtype=float)
    if np.any(raw < 0):
        raise ValueError("Negative weights are not supported")
    total = float(raw.sum())
    if total <= 0:
        raise ValueError("Weights must sum to a positive value")
    return raw / total


def static_risk_report(
    returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    annualization: int = TRADING_DAYS,
) -> dict:
    """Compute covariance, correlations, risk contributions, and PCA diagnostics."""
    symbols = list(weights)
    if annualization <= 0:
        raise ValueError("annualization must be > 0")
    if len(returns) < 20:
        raise ValueError("Need at least 20 observations")

    x = returns[symbols].apply(pd.to_numeric, errors="coerce").dropna()
    if len(x) < 20:
        raise ValueError("Need at least 20 complete return observations")

    w = _normalized_weights(weights, symbols)
    cov_daily = x.cov().to_numpy(dtype=float)
    cov_annual = cov_daily * annualization
    corr = x.corr()

    asset_vol = np.sqrt(np.clip(np.diag(cov_annual), 0.0, None))
    portfolio_variance = float(w @ cov_annual @ w)
    portfolio_variance = max(portfolio_variance, 0.0)
    portfolio_vol = float(np.sqrt(portfolio_variance))

    marginal_var = cov_annual @ w
    if portfolio_variance > 1e-18:
        risk_share = w * marginal_var / portfolio_variance
        component_vol = w * marginal_var / portfolio_vol if portfolio_vol > 0 else np.zeros_like(w)
    else:
        risk_share = np.full_like(w, np.nan)
        component_vol = np.full_like(w, np.nan)

    weighted_asset_vol = float(w @ asset_vol)
    diversification_ratio = (
        weighted_asset_vol / portfolio_vol if portfolio_vol > 1e-18 else float("nan")
    )

    corr_matrix = corr.to_numpy(dtype=float)
    eigvals, eigvecs = np.linalg.eigh(corr_matrix)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    eigvals = np.clip(eigvals, 0.0, None)
    eigsum = float(eigvals.sum())
    pc1_share = float(eigvals[0] / eigsum) if eigsum > 0 else float("nan")
    pc1 = eigvecs[:, 0].copy()
    if float(pc1.sum()) < 0:
        pc1 *= -1.0

    n = len(symbols)
    if n > 1:
        upper = corr_matrix[np.triu_indices(n, k=1)]
        average_pairwise_correlation = float(np.nanmean(upper))
        max_pairwise_correlation = float(np.nanmax(upper))
    else:
        average_pairwise_correlation = float("nan")
        max_pairwise_correlation = float("nan")

    absolute_rc = np.abs(risk_share)
    rc_total = float(np.nansum(absolute_rc))
    if rc_total > 0:
        normalized_abs_rc = absolute_rc / rc_total
        effective_risk_bets = float(1.0 / np.sum(normalized_abs_rc**2))
        max_abs_risk_share = float(np.max(normalized_abs_rc))
    else:
        effective_risk_bets = float("nan")
        max_abs_risk_share = float("nan")

    asset_rows = []
    for i, symbol in enumerate(symbols):
        asset_rows.append(
            {
                "symbol": symbol,
                "capital_weight": float(w[i]),
                "annualized_vol": float(asset_vol[i]),
                "component_vol": float(component_vol[i]),
                "risk_share": float(risk_share[i]),
                "pc1_loading": float(pc1[i]),
            }
        )

    summary = {
        "observations": int(len(x)),
        "portfolio_vol": portfolio_vol,
        "weighted_asset_vol": weighted_asset_vol,
        "diversification_ratio": diversification_ratio,
        "average_pairwise_correlation": average_pairwise_correlation,
        "max_pairwise_correlation": max_pairwise_correlation,
        "pc1_explained_share": pc1_share,
        "effective_risk_bets": effective_risk_bets,
        "max_abs_risk_share": max_abs_risk_share,
    }

    return {
        "summary": summary,
        "assets": pd.DataFrame(asset_rows),
        "correlation": corr,
        "covariance_annual": pd.DataFrame(cov_annual, index=symbols, columns=symbols),
        "eigenvalues": pd.DataFrame(
            {
                "component": np.arange(1, len(eigvals) + 1),
                "eigenvalue": eigvals,
                "explained_share": eigvals / eigsum if eigsum > 0 else np.nan,
            }
        ),
    }


def rolling_risk_report(
    returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    window: int = 242,
    stride: int = 21,
    annualization: int = TRADING_DAYS,
) -> pd.DataFrame:
    """Compute rolling risk diagnostics, sampled every ``stride`` trading days."""
    if window < 20:
        raise ValueError("window must be >= 20")
    if stride <= 0:
        raise ValueError("stride must be > 0")
    if len(returns) < window:
        raise ValueError("Not enough observations for rolling window")

    symbols = list(weights)
    rows: list[dict] = []
    endpoints = list(range(window, len(returns) + 1, stride))
    if endpoints[-1] != len(returns):
        endpoints.append(len(returns))

    for end in endpoints:
        sample = returns.iloc[end - window : end].copy()
        report = static_risk_report(sample, weights, annualization=annualization)
        summary = report["summary"]
        assets = report["assets"].set_index("symbol")
        row: dict[str, float | str] = {
            "date": pd.Timestamp(sample.iloc[-1]["date"]),
            "portfolio_vol": float(summary["portfolio_vol"]),
            "diversification_ratio": float(summary["diversification_ratio"]),
            "average_pairwise_correlation": float(summary["average_pairwise_correlation"]),
            "pc1_explained_share": float(summary["pc1_explained_share"]),
            "effective_risk_bets": float(summary["effective_risk_bets"]),
            "max_abs_risk_share": float(summary["max_abs_risk_share"]),
        }
        for symbol in symbols:
            row[f"risk_share_{symbol}"] = float(assets.loc[symbol, "risk_share"])
        rows.append(row)
    return pd.DataFrame(rows)


def yearly_risk_report(
    returns: pd.DataFrame,
    weights: dict[str, float],
    *,
    annualization: int = TRADING_DAYS,
    min_days: int = 80,
) -> pd.DataFrame:
    """Calendar-year snapshots to expose regime changes in correlations/risk."""
    data = returns.copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    rows: list[dict] = []
    for year, sample in data.groupby("year"):
        sample = sample.drop(columns=["year"]).reset_index(drop=True)
        if len(sample) < min_days:
            continue
        report = static_risk_report(sample, weights, annualization=annualization)
        summary = report["summary"]
        assets = report["assets"].set_index("symbol")
        row: dict[str, float | int] = {
            "year": int(year),
            "observations": int(summary["observations"]),
            "portfolio_vol": float(summary["portfolio_vol"]),
            "diversification_ratio": float(summary["diversification_ratio"]),
            "average_pairwise_correlation": float(summary["average_pairwise_correlation"]),
            "pc1_explained_share": float(summary["pc1_explained_share"]),
            "effective_risk_bets": float(summary["effective_risk_bets"]),
            "max_abs_risk_share": float(summary["max_abs_risk_share"]),
        }
        for symbol in weights:
            row[f"risk_share_{symbol}"] = float(assets.loc[symbol, "risk_share"])
        rows.append(row)
    return pd.DataFrame(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="多 ETF 组合风险贡献 / 相关性 / PCA 分析")
    parser.add_argument("--portfolio", default=cfg.DEFAULT_PORTFOLIO)
    parser.add_argument("--start", default=cfg.START_DATE)
    parser.add_argument("--end", default=None)
    parser.add_argument("--adjust", choices=["actual", "forward"], default=cfg.PRICE_ADJUST)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--rolling-window", type=int, default=242)
    parser.add_argument("--rolling-stride", type=int, default=21)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    weights = parse_portfolio(args.portfolio)
    symbols = list(weights)
    prices = load_price_table(
        symbols,
        start=args.start,
        end=args.end,
        adjust=args.adjust,
        refresh=args.refresh,
    )
    returns = return_table(prices, symbols)

    report = static_risk_report(returns, weights)
    rolling = rolling_risk_report(
        returns,
        weights,
        window=args.rolling_window,
        stride=args.rolling_stride,
    )
    yearly = yearly_risk_report(returns, weights)

    summary = report["summary"]
    pd.DataFrame([summary]).to_csv(
        OUTPUT_DIR / "risk_summary.csv", index=False, encoding="utf-8-sig"
    )
    report["assets"].to_csv(
        OUTPUT_DIR / "risk_contribution.csv", index=False, encoding="utf-8-sig"
    )
    report["correlation"].to_csv(OUTPUT_DIR / "risk_correlation.csv", encoding="utf-8-sig")
    report["covariance_annual"].to_csv(
        OUTPUT_DIR / "risk_covariance_annual.csv", encoding="utf-8-sig"
    )
    report["eigenvalues"].to_csv(
        OUTPUT_DIR / "risk_pca.csv", index=False, encoding="utf-8-sig"
    )
    rolling.to_csv(OUTPUT_DIR / "risk_rolling.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(OUTPUT_DIR / "risk_by_year.csv", index=False, encoding="utf-8-sig")

    assets = report["assets"]
    print("\n=== Portfolio risk decomposition ===")
    print(f"period: {returns['date'].iloc[0].date()} ~ {returns['date'].iloc[-1].date()}")
    print(f"portfolio vol: {summary['portfolio_vol']:.2%}")
    print(f"average pairwise corr: {summary['average_pairwise_correlation']:.3f}")
    print(f"PC1 explained share: {summary['pc1_explained_share']:.1%}")
    print(f"diversification ratio: {summary['diversification_ratio']:.3f}")
    print(f"effective risk bets: {summary['effective_risk_bets']:.2f}")
    print("\nCapital weight -> risk share:")
    for _, row in assets.iterrows():
        print(
            f"  {row['symbol']}: {row['capital_weight']:.1%} -> "
            f"{row['risk_share']:.1%} | vol={row['annualized_vol']:.1%}"
        )

    print(
        "\n输出: risk_summary.csv / risk_contribution.csv / risk_correlation.csv / "
        "risk_covariance_annual.csv / risk_pca.csv / risk_rolling.csv / risk_by_year.csv"
    )


if __name__ == "__main__":
    main()
