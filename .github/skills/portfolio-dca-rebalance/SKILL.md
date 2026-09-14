# Portfolio DCA + Rebalance Skill

Use this skill when working on the `515450` repository.

## Project goal

The repository implements a **multi-ETF periodic investment + periodic rebalancing** strategy using Longbridge daily market data, plus research tooling for robust weight discovery, out-of-sample validation, and portfolio risk decomposition.

Do not reintroduce the removed grid, Brownian-bridge intraday simulation, Monte Carlo grid triggering, AkShare, HFQ CSV, or index-extension paths unless the user explicitly asks for them.

## Canonical entrypoints

```bash
python backtest.py
python weight_sweep.py
python walk_forward.py
python risk_analysis.py
```

## Core strategy

- Portfolio contains 2 or more ETFs with target weights.
- Add a fixed cash contribution on the first common trading day of each month.
- Normal contribution months: invest that month's cash according to target weights.
- Rebalance month: add the monthly contribution, then rebalance the **entire account** back to target weights.
- Rebalance cadence is every N contribution months (`--rebalance-months`).
- Sell overweight holdings first, then buy underweight holdings; no leverage.
- Respect commissions and per-symbol lot sizes.
- Residual cash from lot rounding remains in the account.
- Run a DCA-only comparison by default.

## Data

`longbridge_data.py` is the only production market-data adapter.

The engine aligns symbols on the intersection of daily trading dates. Cache is external to the repository.

Current data caveat: research still uses the project's existing Longbridge close-price history. Dividend/cash-distribution accounting is a separate future data-layer improvement and should not be silently mixed into weight-method changes.

## Defaults

```text
Portfolio: 513180.SH 25%, 515450.SH 25%, 513300.SH 25%, 159783.SZ 25%
Monthly contribution: 5000
Rebalance: every 3 contribution months
Adjustment: actual
SH/SZ lot size: 100
```

## Research sequence

When the user asks for a reasonable or robust allocation, do not stop at the historical sweep. Use this sequence:

```text
1. weight_sweep.py     -> discovery on full history
2. walk_forward.py     -> strictly chronological OOS validation
3. risk_analysis.py    -> capital weight vs actual risk concentration
4. only then consider changing DEFAULT_PORTFOLIO
```

A candidate allocation is stronger when it lies in a broad stable region, survives OOS windows, and does not hide a single-factor risk concentration.

## Weight exploration

Use `weight_sweep.py` for broad discovery.

Default search constraints:

```text
Step: 5%
Min per ETF: 10%
Max per ETF: 50%
Chronological folds: 3
```

Do **not** choose weights solely by maximum historical return. Rank candidates using the existing multi-objective score: full-period XIRR, Sharpe, max drawdown, worst-fold XIRR, average fold XIRR, fold stability, and diversification. Prefer the recommended candidate near the center of the top-ranked region rather than a fragile single optimum.

Main outputs:

```text
weight_sweep_results.csv
weight_sweep_top.csv
weight_sweep_recommendation.csv
```

## Walk-Forward validation

Use `walk_forward.py` when judging whether the weight-selection process generalizes.

Default protocol:

```text
Train: previous 3 years
Test: next 12 months
Roll: 12 months
Candidate grid: same bounded grid as weight_sweep.py
```

Hard rule: no test-period observation may enter training, ranking, or weight selection.

Each OOS window is an independent DCA validation account. This intentionally isolates parameter-selection quality. The stitched OOS TWR path is a diagnostic risk series, not a literal continuous live-account simulation.

Primary outputs:

```text
walk_forward_windows.csv
walk_forward_oos_nav.csv
walk_forward_summary.csv
```

Important diagnostics:

- mean / median / worst OOS XIRR;
- hit rate and excess XIRR versus equal weight and current default;
- stitched OOS Sharpe / max drawdown / annualized TWR;
- selected-weight mean, std, min, max across windows.

If selected weights jump from one boundary to another across adjacent windows, treat that instability as evidence against precision even if average OOS return is acceptable.

## Risk analysis

Use `risk_analysis.py` to test whether capital diversification is also risk diversification.

Compute and inspect:

- annualized asset volatilities;
- correlation matrix;
- portfolio volatility;
- component risk contribution and risk-share percentages;
- diversification ratio;
- PCA first-component explained share;
- effective risk bets;
- rolling one-year risk concentration;
- calendar-year regime snapshots.

Do not use equal capital weights or HHI alone as evidence of diversification. Three growth ETFs can carry one common risk factor even at equal 25% capital weights.

Primary outputs:

```text
risk_summary.csv
risk_contribution.csv
risk_correlation.csv
risk_covariance_annual.csv
risk_pca.csv
risk_rolling.csv
risk_by_year.csv
```

## Important interfaces

`parse_portfolio(spec)`
: Parse and normalize arbitrary ETF weights.

`load_price_table(...)`
: Load and align Longbridge daily closes.

`run_strategy(prices, StrategyConfig)`
: Pure portfolio backtest; use this for tests and experiments.

`generate_weight_grid(...)`
: Enumerate bounded portfolio allocations for weight search.

`rank_results(...)`
: Rank weight candidates using the robust multi-objective score.

`build_walk_forward_windows(...)`
: Build chronological train -> test windows with no overlap.

`static_risk_report(...)`
: Compute covariance/correlation, risk contributions, diversification ratio, and PCA diagnostics.

`rolling_risk_report(...)`
: Track risk concentration through time.

`BacktestResult`
: Contains `summary`, `daily`, `monthly`, and `trades`.

## Validation

Run:

```bash
python -m unittest -v
```

When changing accounting or research logic, verify at minimum:

- total contribution equals monthly contribution × contribution months;
- no negative holdings;
- no buy can spend more than available cash;
- rebalance months occur at the configured cadence;
- DCA-only mode never creates rebalance trades;
- weights sum to 1 after parsing/search generation;
- search weights stay within configured min/max bounds;
- output metrics use cash-flow-aware returns rather than treating contributions as investment gains;
- robust ranking does not reduce to full-period return alone;
- walk-forward training ends strictly before testing begins;
- no OOS observation is used to choose its own weights;
- risk-share components sum to ~100% (allowing numerical tolerance);
- identical perfectly correlated assets do not create fake diversification benefits;
- rolling risk output includes the latest available date.
