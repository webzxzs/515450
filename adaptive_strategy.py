#!/usr/bin/env python3
"""Experimental adaptive DCA/rebalancing engine.

This module deliberately lives beside the canonical ``backtest.py`` engine so
new allocation rules can be compared without changing the historical baseline.

Two contribution modes are supported:

``target``
    Split each new monthly contribution by target weights.

``underweight``
    Use new cash to buy the most underweight sleeves first.  It never sells on
    a normal contribution month, so contributions themselves perform as much of
    the rebalancing work as possible.

Full rebalancing can be periodic, threshold-triggered, either, or disabled.
Threshold checks are performed after the monthly contribution has been invested
and use invested-asset weights (cash excluded) so lot-size residual cash does
not create false drift signals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest import (
    BacktestResult,
    _fee,
    _max_affordable_shares,
    _round_down_shares,
    _xirr,
    tradable_column,
)


@dataclass(frozen=True)
class AdaptiveStrategyConfig:
    weights: dict[str, float]
    monthly_contribution: float
    commission_rate: float
    min_commission: float
    lot_sizes: dict[str, int]
    contribution_mode: str = "underweight"
    rebalance_rule: str = "periodic"
    rebalance_months: int = 3
    rebalance_threshold: float = 0.05


def _validate_config(scfg: AdaptiveStrategyConfig) -> None:
    if len(scfg.weights) < 2:
        raise ValueError("Strategy requires at least two ETFs")
    if abs(sum(scfg.weights.values()) - 1.0) > 1e-6:
        raise ValueError("Strategy weights must sum to 1")
    if any(weight < 0 for weight in scfg.weights.values()):
        raise ValueError("Strategy weights must all be >= 0")
    if sum(weight > 0 for weight in scfg.weights.values()) < 2:
        raise ValueError("Strategy requires at least two positive target weights")
    if scfg.monthly_contribution <= 0:
        raise ValueError("monthly_contribution must be > 0")
    if scfg.contribution_mode not in {"target", "underweight"}:
        raise ValueError("contribution_mode must be target or underweight")
    if scfg.rebalance_rule not in {"periodic", "threshold", "either", "none"}:
        raise ValueError("rebalance_rule must be periodic, threshold, either, or none")
    if scfg.rebalance_months < 0:
        raise ValueError("rebalance_months must be >= 0")
    if not 0 <= scfg.rebalance_threshold <= 1:
        raise ValueError("rebalance_threshold must be in [0, 1]")
    if scfg.rebalance_rule in {"periodic", "either"} and scfg.rebalance_months <= 0:
        raise ValueError("periodic/either rebalance requires rebalance_months > 0")
    if scfg.rebalance_rule in {"threshold", "either"} and scfg.rebalance_threshold <= 0:
        raise ValueError("threshold/either rebalance requires rebalance_threshold > 0")


def run_adaptive_strategy(prices: pd.DataFrame, scfg: AdaptiveStrategyConfig) -> BacktestResult:
    """Run adaptive monthly contributions and configurable full rebalancing."""
    _validate_config(scfg)
    symbols = list(scfg.weights)

    if prices.empty:
        raise ValueError("prices is empty")
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").reset_index(drop=True)

    for symbol in symbols:
        if symbol not in data.columns:
            raise ValueError(f"Missing price column: {symbol}")
        if symbol not in scfg.lot_sizes or scfg.lot_sizes[symbol] <= 0:
            raise ValueError(f"Invalid or missing lot size for {symbol}")
        data[symbol] = pd.to_numeric(data[symbol], errors="coerce")
    if data[symbols].isna().any().any():
        raise ValueError("price table contains missing/non-numeric values")

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

    def is_tradable(row: pd.Series, symbol: str) -> bool:
        col = tradable_column(symbol)
        return bool(row[col]) if col in row.index else True

    def position_value(row: pd.Series, symbol: str) -> float:
        return shares[symbol] * float(row[symbol])

    def invested_value(row: pd.Series) -> float:
        return sum(position_value(row, symbol) for symbol in symbols)

    def total_value(row: pd.Series) -> float:
        return cash + invested_value(row)

    def asset_weights(row: pd.Series) -> dict[str, float]:
        invested = invested_value(row)
        if invested <= 1e-12:
            return {symbol: 0.0 for symbol in symbols}
        return {symbol: position_value(row, symbol) / invested for symbol in symbols}

    def max_weight_drift(row: pd.Series) -> float:
        invested = invested_value(row)
        if invested <= 1e-12:
            return 0.0
        current = asset_weights(row)
        return max(abs(current[s] - scfg.weights[s]) for s in symbols)

    def record_trade(
        ts: pd.Timestamp,
        symbol: str,
        side: str,
        reason: str,
        price: float,
        qty: int,
        fee: float,
    ) -> None:
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

    def buy(
        ts: pd.Timestamp,
        row: pd.Series,
        symbol: str,
        desired_shares: int,
        reason: str,
    ) -> int:
        nonlocal cash
        if not is_tradable(row, symbol):
            return 0
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

    def sell(
        ts: pd.Timestamp,
        row: pd.Series,
        symbol: str,
        desired_shares: int,
        reason: str,
    ) -> int:
        nonlocal cash
        if not is_tradable(row, symbol):
            return 0
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

    def invest_target(ts: pd.Timestamp, row: pd.Series) -> None:
        for symbol, weight in scfg.weights.items():
            if weight <= 0:
                continue
            budget = scfg.monthly_contribution * weight
            price = float(row[symbol])
            desired = _round_down_shares(budget / price, scfg.lot_sizes[symbol])
            buy(ts, row, symbol, desired, "DCA_TARGET")

    def invest_underweight(ts: pd.Timestamp, row: pd.Series) -> None:
        """Spend available cash toward target sleeves without selling anything."""
        equity = total_value(row)
        if equity <= 0:
            return

        targets = {symbol: equity * scfg.weights[symbol] for symbol in symbols}
        desired = {
            symbol: _round_down_shares(
                targets[symbol] / float(row[symbol]), scfg.lot_sizes[symbol]
            )
            for symbol in symbols
        }

        while cash > 1e-9:
            candidates: list[tuple[float, str, int]] = []
            for symbol in symbols:
                shortfall = desired[symbol] - shares[symbol]
                if shortfall <= 0 or not is_tradable(row, symbol):
                    continue
                deficit_value = shortfall * float(row[symbol])
                target_value = max(targets[symbol], 1e-12)
                candidates.append((deficit_value / target_value, symbol, shortfall))
            if not candidates:
                break

            candidates.sort(reverse=True)
            bought = False
            for _, symbol, shortfall in candidates:
                lot = scfg.lot_sizes[symbol]
                qty = min(shortfall, lot)
                if buy(ts, row, symbol, qty, "DCA_UNDERWEIGHT") > 0:
                    bought = True
                    break
            if not bought:
                break

    def rebalance(ts: pd.Timestamp, row: pd.Series, reason: str) -> None:
        equity = total_value(row)
        targets = {symbol: equity * scfg.weights[symbol] for symbol in symbols}
        desired = {
            symbol: _round_down_shares(
                targets[symbol] / float(row[symbol]), scfg.lot_sizes[symbol]
            )
            for symbol in symbols
        }

        for symbol in symbols:
            excess = shares[symbol] - desired[symbol]
            if excess > 0:
                sell(ts, row, symbol, excess, reason)
        for symbol in symbols:
            shortfall = desired[symbol] - shares[symbol]
            if shortfall > 0:
                buy(ts, row, symbol, shortfall, reason)

    for _, row in data.iterrows():
        ts = pd.Timestamp(row["date"])
        month = ts.strftime("%Y-%m")
        contribution_today = 0.0
        rebalanced_today = False
        rebalance_trigger = ""

        if month != previous_month:
            previous_month = month
            contribution_count += 1
            cash += scfg.monthly_contribution
            contributed += scfg.monthly_contribution
            contribution_today = scfg.monthly_contribution
            cashflows.append((ts, -scfg.monthly_contribution))

            periodic_due = (
                scfg.rebalance_rule in {"periodic", "either"}
                and contribution_count % scfg.rebalance_months == 0
            )

            if periodic_due:
                rebalance(ts, row, "REBALANCE_PERIODIC")
                rebalanced_today = True
                rebalance_trigger = "periodic"
            else:
                if scfg.contribution_mode == "underweight":
                    invest_underweight(ts, row)
                else:
                    invest_target(ts, row)

                threshold_due = (
                    scfg.rebalance_rule in {"threshold", "either"}
                    and max_weight_drift(row) >= scfg.rebalance_threshold
                )
                if threshold_due:
                    rebalance(ts, row, "REBALANCE_THRESHOLD")
                    rebalanced_today = True
                    rebalance_trigger = "threshold"

            equity = total_value(row)
            drift = max_weight_drift(row)
            snap = {
                "date": ts,
                "month": month,
                "portfolio_value": equity,
                "cash": cash,
                "cumulative_contribution": contributed,
                "rebalanced": rebalanced_today,
                "rebalance_trigger": rebalance_trigger,
                "max_weight_drift": drift,
            }
            current_weights = asset_weights(row)
            for symbol in symbols:
                value = position_value(row, symbol)
                snap[f"{symbol}_shares"] = shares[symbol]
                snap[f"{symbol}_value"] = value
                snap[f"{symbol}_weight"] = current_weights[symbol]
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
    total_traded_gross = float(trades_df["gross"].sum()) if not trades_df.empty else 0.0
    rebalance_trades = (
        int(trades_df["reason"].str.startswith("REBALANCE").sum())
        if not trades_df.empty
        else 0
    )
    rebalance_events = int(monthly_df["rebalanced"].sum()) if not monthly_df.empty else 0
    ending_drift = max_weight_drift(data.iloc[-1])

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
        "total_traded_gross": total_traded_gross,
        "rebalance_events": rebalance_events,
        "rebalance_trade_count": rebalance_trades,
        "ending_cash": float(cash),
        "ending_max_weight_drift": float(ending_drift),
        "mean_monthly_max_weight_drift": (
            float(monthly_df["max_weight_drift"].mean()) if not monthly_df.empty else float("nan")
        ),
        "max_monthly_max_weight_drift": (
            float(monthly_df["max_weight_drift"].max()) if not monthly_df.empty else float("nan")
        ),
        "contribution_mode": scfg.contribution_mode,
        "rebalance_rule": scfg.rebalance_rule,
        "rebalance_months": scfg.rebalance_months,
        "rebalance_threshold": scfg.rebalance_threshold,
    }

    final_asset_weights = asset_weights(data.iloc[-1])
    for symbol, weight in scfg.weights.items():
        summary[f"target_weight_{symbol}"] = weight
        summary[f"ending_weight_{symbol}"] = final_asset_weights[symbol]
        summary[f"ending_shares_{symbol}"] = shares[symbol]

    return BacktestResult(
        summary=summary,
        daily=daily_df,
        monthly=monthly_df,
        trades=trades_df,
    )
