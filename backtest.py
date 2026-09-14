#!/usr/bin/env python3
"""Multi-ETF DCA + periodic rebalancing backtest using Longbridge data.

Strategy
--------
1. Contribute a fixed amount on the first common trading day of every month.
2. In normal months, invest that month's contribution by target weights.
3. Every N contribution months, rebalance the whole portfolio back to target
   weights (sell overweight positions first, then buy underweight positions).
4. Respect market lot sizes and commissions; unused cash remains in the account.

The engine is intentionally price-source agnostic after loading: it only needs
an aligned daily close-price table. Longbridge is the canonical source used by
``main()``.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import config as cfg
from longbridge_data import load_daily_data, resolve_symbol


OUTPUT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class StrategyConfig:
    weights: dict[str, float]
    monthly_contribution: float
    rebalance_months: int
    commission_rate: float
    min_commission: float
    lot_sizes: dict[str, int]


@dataclass
class BacktestResult:
    summary: dict
    daily: pd.DataFrame
    monthly: pd.DataFrame
    trades: pd.DataFrame


def parse_portfolio(spec: str) -> dict[str, float]:
    """Parse ``SYMBOL:WEIGHT,SYMBOL:WEIGHT`` (``=`` also accepted).

    Weights are normalized, so ``80,20`` and ``0.8,0.2`` are equivalent.
    """
    pairs: dict[str, float] = {}
    for token in str(spec).split(","):
        token = token.strip()
        if not token:
            continue
        sep = ":" if ":" in token else "=" if "=" in token else None
        if not sep:
            raise ValueError(f"Invalid portfolio item {token!r}; use SYMBOL:WEIGHT")
        raw_symbol, raw_weight = token.rsplit(sep, 1)
        symbol = resolve_symbol(raw_symbol.strip())
        weight = float(raw_weight)
        if weight <= 0:
            raise ValueError(f"Weight must be > 0 for {symbol}")
        if symbol in pairs:
            raise ValueError(f"Duplicate symbol: {symbol}")
        pairs[symbol] = weight

    if len(pairs) < 2:
        raise ValueError("Portfolio must contain at least two ETFs")
    total = sum(pairs.values())
    return {symbol: weight / total for symbol, weight in pairs.items()}


def parse_lot_sizes(spec: str, symbols: Iterable[str]) -> dict[str, int]:
    """Build per-symbol lot sizes; SH/SZ default to 100, others to 1."""
    result = {
        symbol: (100 if symbol.endswith((".SH", ".SZ")) else 1)
        for symbol in symbols
    }
    if not spec.strip():
        return result

    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        sep = ":" if ":" in token else "=" if "=" in token else None
        if not sep:
            raise ValueError(f"Invalid lot-size item {token!r}; use SYMBOL:LOT")
        raw_symbol, raw_lot = token.rsplit(sep, 1)
        symbol = resolve_symbol(raw_symbol.strip())
        lot = int(raw_lot)
        if lot <= 0:
            raise ValueError(f"Lot size must be > 0 for {symbol}")
        if symbol not in result:
            raise ValueError(f"Lot-size symbol {symbol} is not in the portfolio")
        result[symbol] = lot
    return result


def load_price_table(
    symbols: Iterable[str],
    *,
    start: str,
    end: str | None,
    adjust: str,
    refresh: bool,
) -> pd.DataFrame:
    """Load daily closes and keep only dates tradable by every portfolio ETF."""
    merged: pd.DataFrame | None = None
    for symbol in symbols:
        df = load_daily_data(symbol, start=start, end=end, adjust=adjust, refresh=refresh)
        part = df[["date", "close"]].copy().rename(columns={"close": symbol})
        merged = part if merged is None else pd.merge(merged, part, on="date", how="inner")

    if merged is None or merged.empty:
        raise ValueError("No overlapping trading dates across portfolio ETFs")

    price_cols = [c for c in merged.columns if c != "date"]
    merged[price_cols] = merged[price_cols].apply(pd.to_numeric, errors="coerce")
    merged = (
        merged.dropna(subset=price_cols)
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    if len(merged) < 2:
        raise ValueError("Not enough overlapping price history to backtest")
    return merged


def _fee(gross: float, rate: float, minimum: float) -> float:
    if gross <= 0:
        return 0.0
    return max(gross * rate, minimum)


def _round_down_shares(raw_shares: float, lot: int) -> int:
    if raw_shares <= 0:
        return 0
    return int(math.floor(raw_shares / lot) * lot)


def _max_affordable_shares(cash: float, price: float, lot: int, rate: float, minimum: float) -> int:
    if cash <= 0 or price <= 0:
        return 0
    shares = _round_down_shares(cash / price, lot)
    while shares > 0:
        gross = shares * price
        if gross + _fee(gross, rate, minimum) <= cash + 1e-9:
            return shares
        shares -= lot
    return 0


def _xirr(cashflows: list[tuple[pd.Timestamp, float]], guess: float = 0.1) -> float:
    flows = [(pd.Timestamp(d), float(v)) for d, v in cashflows if abs(v) > 1e-12]
    if len(flows) < 2 or not any(v > 0 for _, v in flows) or not any(v < 0 for _, v in flows):
        return float("nan")

    t0 = min(d for d, _ in flows)
    years = np.array([(d - t0).days / 365.25 for d, _ in flows], dtype=float)
    amounts = np.array([v for _, v in flows], dtype=float)

    def npv(rate: float) -> float:
        if rate <= -0.999999:
            return float("inf")
        return float(np.sum(amounts / np.power(1.0 + rate, years)))

    rate = guess
    for _ in range(50):
        if rate <= -0.999999:
            break
        base = np.power(1.0 + rate, years)
        f = float(np.sum(amounts / base))
        df = float(np.sum(-years * amounts / np.power(1.0 + rate, years + 1.0)))
        if not np.isfinite(f) or not np.isfinite(df) or abs(df) < 1e-12:
            break
        nxt = rate - f / df
        if abs(nxt - rate) < 1e-10:
            return float(nxt)
        rate = nxt

    lo, hi = -0.95, 10.0
    flo, fhi = npv(lo), npv(hi)
    if not np.isfinite(flo) or not np.isfinite(fhi) or np.sign(flo) == np.sign(fhi):
        return float("nan")
    for _ in range(120):
        mid = (lo + hi) / 2.0
        fm = npv(mid)
        if abs(fm) < 1e-9:
            return float(mid)
        if np.sign(fm) == np.sign(flo):
            lo, flo = mid, fm
        else:
            hi = mid
    return float((lo + hi) / 2.0)


def run_strategy(prices: pd.DataFrame, scfg: StrategyConfig) -> BacktestResult:
    symbols = list(scfg.weights)
    if len(symbols) < 2:
        raise ValueError("Strategy requires at least two ETFs")
    if abs(sum(scfg.weights.values()) - 1.0) > 1e-6:
        raise ValueError("Strategy weights must sum to 1")
    if scfg.monthly_contribution <= 0:
        raise ValueError("monthly_contribution must be > 0")
    if scfg.rebalance_months < 0:
        raise ValueError("rebalance_months must be >= 0")

    for symbol in symbols:
        if symbol not in prices.columns:
            raise ValueError(f"Missing price column: {symbol}")
        if symbol not in scfg.lot_sizes or scfg.lot_sizes[symbol] <= 0:
            raise ValueError(f"Invalid or missing lot size for {symbol}")

    shares = {symbol: 0 for symbol in symbols}
    cash = 0.0
    contributed = 0.0
    contribution_count = 0
    trades: list[dict] = []
    daily_rows: list[dict] = []
    monthly_rows: list[dict] = []
    cashflows: list[tuple[pd.Timestamp, float]] = []
    previous_month: str | None = None
    previous_value: float | None = None
    nav = 1.0

    def position_value(row: pd.Series, symbol: str) -> float:
        return shares[symbol] * float(row[symbol])

    def total_value(row: pd.Series) -> float:
        return cash + sum(position_value(row, s) for s in symbols)

    def record_trade(
        ts: pd.Timestamp,
        symbol: str,
        side: str,
        reason: str,
        price: float,
        qty: int,
        fee: float,
    ):
        trades.append(
            {
                "date": ts,
                "symbol": symbol,
                "side": side,
                "reason": reason,
                "price": price,
                "shares": qty,
                "gross": price * qty,
                "fee": fee,
                "cash_after": cash,
            }
        )

    def buy(ts: pd.Timestamp, row: pd.Series, symbol: str, desired_shares: int, reason: str) -> int:
        nonlocal cash
        price = float(row[symbol])
        lot = scfg.lot_sizes[symbol]
        desired_shares = _round_down_shares(desired_shares, lot)
        affordable = _max_affordable_shares(
            cash, price, lot, scfg.commission_rate, scfg.min_commission
        )
        qty = min(desired_shares, affordable)
        if qty <= 0:
            return 0
        gross = price * qty
        fee = _fee(gross, scfg.commission_rate, scfg.min_commission)
        cash -= gross + fee
        if cash < -1e-6:
            raise RuntimeError(f"Negative cash after buying {symbol}: {cash}")
        if abs(cash) < 1e-9:
            cash = 0.0
        shares[symbol] += qty
        record_trade(ts, symbol, "BUY", reason, price, qty, fee)
        return qty

    def sell(ts: pd.Timestamp, row: pd.Series, symbol: str, desired_shares: int, reason: str) -> int:
        nonlocal cash
        lot = scfg.lot_sizes[symbol]
        qty = min(_round_down_shares(desired_shares, lot), shares[symbol])
        if qty <= 0:
            return 0
        price = float(row[symbol])
        gross = price * qty
        fee = _fee(gross, scfg.commission_rate, scfg.min_commission)
        cash += gross - fee
        shares[symbol] -= qty
        if shares[symbol] < 0:
            raise RuntimeError(f"Negative holdings after selling {symbol}")
        record_trade(ts, symbol, "SELL", reason, price, qty, fee)
        return qty

    def invest_contribution(ts: pd.Timestamp, row: pd.Series):
        # Allocate only the new monthly contribution by target weights. Residual
        # cash from lot rounding is deliberately retained for future months.
        for symbol, weight in scfg.weights.items():
            budget = scfg.monthly_contribution * weight
            price = float(row[symbol])
            lot = scfg.lot_sizes[symbol]
            desired = _round_down_shares(budget / price, lot)
            buy(ts, row, symbol, desired, "DCA")

    def rebalance(ts: pd.Timestamp, row: pd.Series):
        equity = total_value(row)
        targets = {symbol: equity * weight for symbol, weight in scfg.weights.items()}
        desired_shares = {
            symbol: _round_down_shares(
                targets[symbol] / float(row[symbol]), scfg.lot_sizes[symbol]
            )
            for symbol in symbols
        }

        # Sell first so buys never require external leverage.
        for symbol in symbols:
            excess = shares[symbol] - desired_shares[symbol]
            if excess > 0:
                sell(ts, row, symbol, excess, "REBALANCE")
        for symbol in symbols:
            shortfall = desired_shares[symbol] - shares[symbol]
            if shortfall > 0:
                buy(ts, row, symbol, shortfall, "REBALANCE")

    for _, row in prices.iterrows():
        ts = pd.Timestamp(row["date"])
        month = ts.strftime("%Y-%m")
        contribution_today = 0.0
        rebalanced_today = False

        if month != previous_month:
            previous_month = month
            contribution_count += 1
            cash += scfg.monthly_contribution
            contributed += scfg.monthly_contribution
            contribution_today = scfg.monthly_contribution
            cashflows.append((ts, -scfg.monthly_contribution))

            if scfg.rebalance_months > 0 and contribution_count % scfg.rebalance_months == 0:
                rebalance(ts, row)
                rebalanced_today = True
            else:
                invest_contribution(ts, row)

            equity = total_value(row)
            snap = {
                "date": ts,
                "month": month,
                "portfolio_value": equity,
                "cash": cash,
                "cumulative_contribution": contributed,
                "rebalanced": rebalanced_today,
            }
            for symbol in symbols:
                value = position_value(row, symbol)
                snap[f"{symbol}_shares"] = shares[symbol]
                snap[f"{symbol}_value"] = value
                snap[f"{symbol}_weight"] = value / equity if equity > 0 else 0.0
            monthly_rows.append(snap)

        value = total_value(row)
        if previous_value is None or previous_value <= 0:
            twr_return = value / contribution_today - 1.0 if contribution_today > 0 else 0.0
        else:
            twr_return = (value - contribution_today) / previous_value - 1.0
        nav *= 1.0 + twr_return
        previous_value = value

        daily = {
            "date": ts,
            "portfolio_value": value,
            "cash": cash,
            "cumulative_contribution": contributed,
            "cash_flow": contribution_today,
            "twr_return": twr_return,
            "nav": nav,
        }
        for symbol in symbols:
            daily[f"{symbol}_shares"] = shares[symbol]
            daily[f"{symbol}_value"] = position_value(row, symbol)
        daily_rows.append(daily)

    daily_df = pd.DataFrame(daily_rows)
    monthly_df = pd.DataFrame(monthly_rows)
    trades_df = pd.DataFrame(trades)

    final_value = float(daily_df.iloc[-1]["portfolio_value"])
    cashflows.append((pd.Timestamp(daily_df.iloc[-1]["date"]), final_value))
    xirr = _xirr(cashflows)

    daily_returns = daily_df["twr_return"].replace([np.inf, -np.inf], np.nan).dropna()
    daily_returns = daily_returns.iloc[1:] if len(daily_returns) > 1 else daily_returns
    years = max(
        (daily_df.iloc[-1]["date"] - daily_df.iloc[0]["date"]).days / 365.25,
        1 / 365.25,
    )
    ann_twr = float(daily_df.iloc[-1]["nav"] ** (1.0 / years) - 1.0)
    sharpe = (
        float(daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(242))
        if len(daily_returns) > 30 and daily_returns.std(ddof=1) > 1e-12
        else float("nan")
    )
    nav_series = daily_df["nav"].astype(float)
    drawdown = nav_series / nav_series.cummax() - 1.0
    max_dd = float(drawdown.min())
    fees = float(trades_df["fee"].sum()) if not trades_df.empty else 0.0
    rebalance_trades = (
        int((trades_df["reason"] == "REBALANCE").sum()) if not trades_df.empty else 0
    )
    rebalance_events = int(monthly_df["rebalanced"].sum()) if not monthly_df.empty else 0

    summary = {
        "start": str(pd.Timestamp(daily_df.iloc[0]["date"]).date()),
        "end": str(pd.Timestamp(daily_df.iloc[-1]["date"]).date()),
        "months": contribution_count,
        "total_contribution": contributed,
        "final_value": final_value,
        "pnl": final_value - contributed,
        "xirr": xirr,
        "annualized_twr": ann_twr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "total_fees": fees,
        "trade_count": int(len(trades_df)),
        "rebalance_events": rebalance_events,
        "rebalance_trade_count": rebalance_trades,
        "ending_cash": float(cash),
    }
    for symbol, weight in scfg.weights.items():
        value = shares[symbol] * float(prices.iloc[-1][symbol])
        summary[f"target_weight_{symbol}"] = weight
        summary[f"ending_weight_{symbol}"] = value / final_value if final_value > 0 else 0.0
        summary[f"ending_shares_{symbol}"] = shares[symbol]

    return BacktestResult(
        summary=summary,
        daily=daily_df,
        monthly=monthly_df,
        trades=trades_df,
    )


def export_result(result: BacktestResult, prefix: str = "portfolio") -> None:
    summary_df = pd.DataFrame([result.summary])
    summary_path = OUTPUT_DIR / f"{prefix}_summary.csv"
    daily_path = OUTPUT_DIR / f"{prefix}_daily.csv"
    monthly_path = OUTPUT_DIR / f"{prefix}_monthly.csv"
    trades_path = OUTPUT_DIR / f"{prefix}_trades.csv"
    xlsx_path = OUTPUT_DIR / f"{prefix}_backtest.xlsx"

    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    result.daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    result.monthly.to_csv(monthly_path, index=False, encoding="utf-8-sig")
    result.trades.to_csv(trades_path, index=False, encoding="utf-8-sig")

    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="summary", index=False)
            result.monthly.to_excel(writer, sheet_name="monthly", index=False)
            result.trades.to_excel(writer, sheet_name="trades", index=False)
            result.daily.to_excel(writer, sheet_name="daily", index=False)
    except ImportError:
        print("openpyxl 未安装，跳过 Excel 输出；CSV 已正常生成。")


def _print_summary(title: str, summary: dict) -> None:
    def pct(value):
        return "n/a" if not np.isfinite(value) else f"{value:.2%}"

    print(f"\n=== {title} ===")
    print(f"区间: {summary['start']} ~ {summary['end']} | 定投月数: {summary['months']}")
    print(f"累计投入: ¥{summary['total_contribution']:,.2f}")
    print(f"期末资产: ¥{summary['final_value']:,.2f} | 盈亏: ¥{summary['pnl']:,.2f}")
    print(f"XIRR: {pct(summary['xirr'])} | 年化TWR: {pct(summary['annualized_twr'])}")
    print(f"Sharpe: {summary['sharpe']:.3f} | 最大回撤: {pct(summary['max_drawdown'])}")
    print(
        f"交易次数: {summary['trade_count']} | "
        f"再平衡次数: {summary['rebalance_events']} | "
        f"再平衡交易: {summary['rebalance_trade_count']} | "
        f"总费用: ¥{summary['total_fees']:,.2f}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="多ETF定投 + 定期再平衡回测（Longbridge）")
    parser.add_argument(
        "--portfolio",
        default=cfg.DEFAULT_PORTFOLIO,
        help="ETF及目标权重，例如 515450.SH:0.8,513130.SH:0.2",
    )
    parser.add_argument(
        "--monthly",
        type=float,
        default=cfg.MONTHLY_CONTRIBUTION,
        help="每月总定投金额",
    )
    parser.add_argument(
        "--rebalance-months",
        type=int,
        default=cfg.REBALANCE_MONTHS,
        help="每多少个定投月做一次全组合再平衡；0 表示只定投不再平衡",
    )
    parser.add_argument("--start", default=cfg.START_DATE)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--adjust",
        choices=["actual", "forward"],
        default=cfg.PRICE_ADJUST,
    )
    parser.add_argument("--refresh", action="store_true", help="强制刷新 Longbridge 缓存")
    parser.add_argument("--commission", type=float, default=cfg.COMMISSION)
    parser.add_argument("--min-commission", type=float, default=cfg.MIN_COMMISSION)
    parser.add_argument(
        "--lot-sizes",
        default="",
        help="可覆盖交易单位，例如 515450.SH:100,513130.SH:100",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="不运行“仅定投、不再平衡”对照组",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.monthly <= 0:
        raise ValueError("--monthly must be > 0")
    if args.rebalance_months < 0:
        raise ValueError("--rebalance-months must be >= 0")

    weights = parse_portfolio(args.portfolio)
    lot_sizes = parse_lot_sizes(args.lot_sizes, weights)
    prices = load_price_table(
        weights,
        start=args.start,
        end=args.end,
        adjust=args.adjust,
        refresh=args.refresh,
    )

    print("\n组合目标:")
    for symbol, weight in weights.items():
        print(f"  {symbol}: {weight:.1%} | lot={lot_sizes[symbol]}")
    if args.rebalance_months:
        print(
            f"每月定投: ¥{args.monthly:,.2f} | "
            f"每 {args.rebalance_months} 个月再平衡"
        )
    else:
        print(f"每月定投: ¥{args.monthly:,.2f} | 不再平衡")
    print(
        f"共同交易区间: {prices['date'].iloc[0].date()} ~ "
        f"{prices['date'].iloc[-1].date()} ({len(prices)} 天)"
    )

    scfg = StrategyConfig(
        weights=weights,
        monthly_contribution=args.monthly,
        rebalance_months=args.rebalance_months,
        commission_rate=args.commission,
        min_commission=args.min_commission,
        lot_sizes=lot_sizes,
    )
    result = run_strategy(prices, scfg)
    _print_summary("定投 + 定期再平衡", result.summary)
    export_result(result, "portfolio")

    if not args.no_benchmark and args.rebalance_months > 0:
        benchmark_cfg = StrategyConfig(
            weights=weights,
            monthly_contribution=args.monthly,
            rebalance_months=0,
            commission_rate=args.commission,
            min_commission=args.min_commission,
            lot_sizes=lot_sizes,
        )
        benchmark = run_strategy(prices, benchmark_cfg)
        _print_summary("仅按目标权重定投（不再平衡）", benchmark.summary)
        pd.DataFrame([benchmark.summary]).to_csv(
            OUTPUT_DIR / "dca_only_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )

    print(
        "\n输出: portfolio_summary.csv / portfolio_daily.csv / "
        "portfolio_monthly.csv / portfolio_trades.csv / portfolio_backtest.xlsx"
    )


if __name__ == "__main__":
    main()
