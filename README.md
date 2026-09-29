<p align="right"><strong>English</strong> | <a href="./README_CN.md">中文</a></p>

# Multi-ETF DCA & Rebalancing Research Framework

This is a personal long-term asset-allocation research project built on **Longbridge daily market data**.

The scope is intentionally narrow: **research only — no automated order placement and no live-trading execution system.** For a low-frequency DCA and rebalancing strategy, the main research value lies in asset selection, long-term target weights, rebalancing rules, and portfolio risk structure rather than trading automation.

## Current ETF Universe

| Ticker | Exposure / Role | Fund Manager |
| --- | --- | --- |
| `513180.SH` | Hang Seng TECH | ChinaAMC |
| `515450.SH` | China A-share dividend low-volatility | China Southern Asset Management |
| `513300.SH` | Nasdaq-100 | ChinaAMC |
| `159783.SZ` | STAR 50 + ChiNext 50 | ChinaAMC |
| `518850.SH` | Gold | ChinaAMC |

ETF selection rule: **for comparable exposures, prefer ChinaAMC products when tracking quality, fees, fund size, liquidity, history length, and Longbridge data quality are not meaningfully worse.** This preference only affects which ETF represents an asset class; it does not determine how much portfolio weight that asset class should receive.

## Current Default Research Portfolio

`config.py` currently stores the joint top-ranked in-sample result as of **2026-09-20**, using explicit dividend total returns, Sharpe ratios based on historical risk-free rates, and the full `policy_sweep`:

~~~text
513180.SH  10%
515450.SH  15%
513300.SH  35%
159783.SZ  10%
518850.SH  30%
~~~

The default execution rule is **monthly target rebalancing**.

This is the current research system's best executable in-sample result. It does **not** imply that the exact allocation has been sufficiently validated out of sample. A 20% equal-weight portfolio remains the neutral benchmark.

See `PORTFOLIO_RESEARCH_2026-09-20.md` for the detailed rationale.

## Final Weight Search Boundaries

The framework supports **independent lower and upper bounds for every ETF**.

Current defaults:

```text
513180.SH   10% ~ 50%
515450.SH   10% ~ 50%
513300.SH   10% ~ 50%
159783.SZ   10% ~ 50%
518850.SH    0% ~ 30%
Weight step          5%
```

Gold is deliberately allowed to fall to **0%**. This makes it possible for the research to conclude that the current five-asset framework does not need gold, rather than forcing a gold allocation through a universal 10% floor.

Under the current boundaries, the 5% grid contains:

```text
1,554 weight combinations
```

`policy_sweep.py` compares 16 DCA / rebalancing execution policies by default, so Stage 1 currently evaluates:

```text
1,554 × 16 = 24,864 full-history backtests
```

These counts are configuration-dependent. If the search boundaries change, trust the runtime output rather than treating the current numbers as model assumptions.

---

# Research Principles

## 1. Do not treat the historical winner as the answer

The real questions are:

- Is the top-performing region concentrated or broad?
- Is the worst historical period still acceptable?
- Does the conclusion survive walk-forward out-of-sample testing?
- Do small parameter changes completely alter the result?
- Does the gold allocation remain in a similar range over time, or repeatedly jump between 0% and its upper bound?

## 2. Study weights and execution rules together

The framework jointly studies:

```text
Target weights
×
Monthly contribution allocation method
×
Rebalancing rule
```

A weight vector that works well under fixed three-month rebalancing is not automatically optimal under an underweight-first contribution rule plus threshold rebalancing.

## 3. Prioritize out-of-sample validation

`walk_forward.py` strictly follows:

```text
Train / select weights on the previous 3 years
Validate on the next 12 months fully out of sample
Roll forward and repeat
```

The test period cannot participate in parameter selection for that window.

## 4. Capital diversification is not the same as risk diversification

Five equal capital weights do not imply five equal risk contributions.

`risk_analysis.py` evaluates:

- volatility;
- correlation;
- component risk contribution;
- risk share;
- diversification ratio;
- first PCA component;
- effective risk bets;
- rolling and calendar-year risk concentration.

The main purpose of adding gold is to test whether it truly contributes a risk source that differs from equity growth factors.

## 5. Use explicit total returns for long-term analysis by default

Default return construction:

```text
Longbridge actual + dividends.csv
```

When raw-price, board-lot, and transaction-cost sensitivity matter:

```bash
python backtest.py --adjust actual
```

`adjustment_analysis.py` reconciles three return conventions:

```text
actual / explicit total_return / Longbridge forward
```

## 6. Sharpe uses historical risk-free rates

Sharpe no longer assumes a zero risk-free rate.

The project maintains `risk_free.csv`, which stores historical **1-year China government bond yield curve** data. `update_risk_free.py` refreshes the snapshot through AKShare's `bond_china_yield` interface using ChinaBond data conventions.

For each ETF trading day, the framework uses only the 1-year government-bond yield published **on that date or the most recent prior date**. Matching is strictly backward-looking, with no future information.

Annualized yields are converted into equivalent daily returns using 242 trading days, and Sharpe is calculated from portfolio daily returns minus the corresponding daily risk-free return.

---

# Data Alignment Rules

Earlier versions required every ETF to have a valid price on the same date and used a date `inner join`. If one ETF was suspended, missing, or omitted by the data source on a given day, the entire date disappeared from portfolio history.

The current rule is:

```text
Take the union of all instrument dates
↓
Only enter the shared research window after each ETF has at least one real price
↓
If an ETF has no price on a date:
use the previous valid close for valuation
↓
Mark that ETF as non-tradable on that date
↓
Other ETFs with valid data can still participate normally
```

Therefore:

- **portfolio valuation remains continuous**;
- one ETF missing a single trading day does not delete the whole date;
- forward-filled prices are never used to fake an executable trade on a suspension / missing-data day;
- synthetic tests without `tradable_*` columns still treat all assets as tradable, preserving compatibility with existing tests and research functions.

---

# Project Structure

| File | Purpose |
| --- | --- |
| `backtest.py` | Stable baseline: DCA + fixed-period rebalancing |
| `adaptive_strategy.py` | Underweight-first DCA, periodic / threshold rebalancing |
| `weight_sweep.py` | Weight grid search + robust multi-metric ranking |
| `policy_sweep.py` | Joint search over weights + contribution method + rebalancing rule |
| `walk_forward.py` | Strict chronological out-of-sample validation |
| `risk_analysis.py` | Correlation, risk contribution, PCA, rolling risk |
| `adjustment_analysis.py` | Reconciliation of actual vs forward-adjusted conventions |
| `dividend_data.py` / `dividends.csv` | Explicit ETF cash dividends and total-return reconstruction |
| `update_dividends.py` | Cross-check and refresh dividend snapshots from two AKShare sources |
| `risk_free_data.py` / `risk_free.csv` | Historical 1-year China government-bond risk-free rates and Sharpe alignment |
| `update_risk_free.py` | Refresh the 1-year government-bond yield snapshot |
| `longbridge_data.py` | Longbridge daily bars and local cache handling |
| `config.py` | ETF universe, research boundaries, and base parameters |

---

# Recommended Research Workflow

```bash
python adjustment_analysis.py
python weight_sweep.py
python policy_sweep.py
python walk_forward.py
python risk_analysis.py
```

The most important steps are:

1. `weight_sweep.py` — inspect stable weight regions rather than one exact winner;
2. `policy_sweep.py` — test whether weights and execution rules depend on each other;
3. `walk_forward.py` — verify whether the result survives out of sample;
4. `risk_analysis.py` — inspect the true risk concentration behind capital weights;
5. `adjustment_analysis.py` — verify whether return-adjustment conventions change the conclusion.

## `weight_sweep.py`

Default score:

```text
Full-period XIRR             25%
Worst-segment XIRR           25%
Full-period Sharpe           15%
Maximum drawdown             15%
Average segment XIRR         10%
Segment stability             5%
Weight diversification / HHI  5%
```

Do not focus only on rank #1. The shape and stability of the top region matter more.

## `policy_sweep.py`

The default set contains 16 execution rules:

```text
Contribution: target / underweight
Periodic rebalance: 1 / 3 / 6 / 12 months
Threshold rebalance: 3% / 5% / 10%
none: no active sell-side rebalancing
```

Stage 1: full weight grid × all execution rules.

Stage 2: retain each policy's own top candidates, then validate them across contiguous historical segments for robustness.

Key outputs:

```text
adaptive_joint_screen.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

## `walk_forward.py`

Focus on:

- OOS XIRR;
- worst validation window;
- win rate versus equal weight;
- weight stability;
- whether gold retains a consistently positive allocation.

If an asset repeatedly jumps between 0% / 10% and its upper bound across adjacent windows, the exact weight should not be trusted.

---

# Longbridge

Longbridge is the project's official market-data source.

First-time authentication:

```bash
longbridge auth login
```

Force-refresh cached data:

```bash
python backtest.py --refresh
python weight_sweep.py --refresh
python policy_sweep.py --refresh
python walk_forward.py --refresh
python risk_analysis.py --refresh
python adjustment_analysis.py --refresh
```

Caches are stored outside the repository, and the project does not store Longbridge credentials.

---

# Testing

```bash
python -m unittest -v
```

GitHub Actions runs offline tests only and does not access the Longbridge account.

Current test coverage includes:

- contribution amounts and cash constraints;
- periodic / threshold rebalancing;
- no selling during ordinary underweight-contribution months;
- 0%-weight sleeves;
- independent per-asset weight boundaries;
- forward-filled valuation and disabled trading on missing-price days;
- walk-forward leakage prevention;
- risk contribution and PCA;
- reconciliation logic for actual / explicit total_return / forward;
- cash-dividend total-return reconstruction;
- backward matching of historical risk-free rates and excess-return Sharpe.

---

# Current Development Status

**The research feature set is considered complete for now.**

The project already supports:

- multi-ETF DCA backtesting;
- independent asset weight constraints;
- exhaustive weight-grid exploration;
- joint DCA / rebalancing policy search;
- walk-forward out-of-sample validation;
- risk contribution / PCA analysis;
- price-adjustment sensitivity analysis;
- more robust handling of missing trading days;
- offline CI.

The next valuable step is **not** to add more optimizers or trading automation.

The useful work now is to **run the framework on real Longbridge history, interpret the results, identify stable allocation regions, and turn those findings into a long-term asset-allocation conclusion.**
