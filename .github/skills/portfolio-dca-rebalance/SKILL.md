# Portfolio DCA + Rebalance Skill

Use this skill when working on the `515450` repository.

## Project goal

The repository implements a **multi-ETF periodic investment + periodic rebalancing** strategy using Longbridge daily market data.

Do not reintroduce the removed grid, Brownian-bridge intraday simulation, Monte Carlo grid triggering, AkShare, HFQ CSV, or index-extension paths unless the user explicitly asks for them.

## Canonical entrypoints

```bash
python backtest.py
python weight_sweep.py
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

## Defaults

```text
Portfolio: 513180.SH 25%, 515450.SH 25%, 513300.SH 25%, 159783.SZ 25%
Monthly contribution: 5000
Rebalance: every 3 contribution months
Adjustment: actual
SH/SZ lot size: 100
```

## Weight exploration

Use `weight_sweep.py` when the user asks for a reasonable, robust, optimal, or exploratory allocation across the portfolio ETFs.

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

`BacktestResult`
: Contains `summary`, `daily`, `monthly`, and `trades`.

## Validation

Run:

```bash
python -m unittest -v
```

When changing accounting or search logic, verify at minimum:

- total contribution equals monthly contribution × contribution months;
- no negative holdings;
- no buy can spend more than available cash;
- rebalance months occur at the configured cadence;
- DCA-only mode never creates rebalance trades;
- weights sum to 1 after parsing/search generation;
- search weights stay within configured min/max bounds;
- output metrics use cash-flow-aware returns rather than treating contributions as investment gains;
- robust ranking does not reduce to full-period return alone.
