# Portfolio DCA + Rebalance Skill

Use this skill when working on the `515450` repository.

## Project goal

The repository implements a **multi-ETF DCA + rebalancing research system** using Longbridge daily market data. It now includes baseline backtests, robust weight discovery, Walk-Forward OOS validation, risk decomposition, adjustment reconciliation, and experimental adaptive contribution/rebalance policies.

Do not reintroduce the removed grid, Brownian-bridge intraday simulation, Monte Carlo grid triggering, AkShare, HFQ CSV, or index-extension paths unless the user explicitly asks for them.

## Canonical entrypoints

```bash
python backtest.py
python weight_sweep.py
python policy_sweep.py
python walk_forward.py
python risk_analysis.py
python adjustment_analysis.py
```

## Baseline vs research layers

`backtest.py` remains the stable baseline engine:

- fixed monthly cash contribution;
- normal months split contribution by target weights;
- periodic full-account rebalancing;
- commissions, minimum commission, lot sizes, residual cash;
- optional no-rebalance benchmark.

`adaptive_strategy.py` is an experimental engine and must remain separately comparable until its behavior is validated.

It supports:

- `target` contribution mode: split new money by target weights;
- `underweight` contribution mode: direct new money toward underweight sleeves, without selling on normal months;
- `periodic`, `threshold`, `either`, or `none` full-rebalance rules.

Threshold checks occur after monthly contribution purchases and use invested-asset weights, excluding residual cash from lot rounding.

## Data and price basis

`longbridge_data.py` is the only production market-data adapter. Symbols are aligned on common daily trading dates; cache lives outside the repository.

Default price basis is `forward` adjustment for long-horizon return research. `actual` remains available for raw-price / execution-sensitivity checks. `adjustment_analysis.py` reconciles the two.

Do not invent dividend cash flows when Longbridge does not return reliable ETF dividend history. Use documented forward-adjusted prices as the total-return research proxy and state that limitation explicitly.

## Default portfolio is only a benchmark

```text
513180.SH 25%
515450.SH 25%
513300.SH 25%
159783.SZ 25%
```

This is **not** an assumed optimum or recommendation. It exists only for quick runs and benchmark comparison. Weight research must continue to search the configured bounded grid.

Default research parameters:

```text
Monthly contribution: 5000
Adjustment: forward
SH/SZ lot size: 100
Weight step: 5%
Min per ETF: 10%
Max per ETF: 50%
Chronological folds: 3
```

## Research sequence

For a reasonable long-term allocation, prefer:

```text
1. weight_sweep.py      -> broad full-grid weight discovery
2. policy_sweep.py      -> jointly test weights + contribution/rebalance rules
3. walk_forward.py      -> strict chronological OOS validation
4. risk_analysis.py     -> capital weights vs actual risk concentration
5. adjustment_analysis.py -> forward vs actual sensitivity / reconciliation
6. only then consider changing DEFAULT_PORTFOLIO or baseline strategy defaults
```

Do not promote a single historical champion directly into defaults.

## Weight exploration

`weight_sweep.py` searches the full bounded grid and ranks using:

- full-period XIRR;
- Sharpe;
- max drawdown;
- worst-fold XIRR;
- mean-fold XIRR;
- fold stability;
- diversification / HHI.

Prefer broad stable regions over fragile point optima.

## Adaptive policy exploration

`policy_sweep.py` treats 25/25/25/25 only as a benchmark.

Default process:

1. Sweep the **entire weight grid** separately under target DCA and underweight DCA with a common 3-month rebalance baseline.
2. Union the robust top weight regions from both modes.
3. Compare those weights across:
   - target vs underweight contribution;
   - periodic rebalancing every 1 / 3 / 6 / 12 months;
   - threshold rebalancing at 3% / 5% / 10% drift;
   - no sell-based full rebalancing.

Primary outputs:

```text
adaptive_seed_weight_rankings.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

Do not infer a precise target weight if Top candidates span most of the allowed 10%-50% range. Parameter instability is evidence against precision.

## Walk-Forward validation

`walk_forward.py` must keep test observations strictly out of training/ranking/selection.

Default protocol:

```text
Train: previous 3 years
Test: next 12 months
Roll: 12 months
```

Each OOS window is an independent validation account. Stitched OOS TWR is for risk diagnostics and must not be described as a literal continuous live account.

## Risk analysis

`risk_analysis.py` must inspect:

- annualized volatility;
- correlation matrix;
- component risk contribution / risk share;
- diversification ratio;
- PCA first-component explained share;
- effective risk bets;
- rolling and yearly risk concentration.

Equal capital weights or low HHI alone are not proof of diversification.

## Important interfaces

`parse_portfolio(spec)`
: Normalize arbitrary ETF target weights.

`load_price_table(...)`
: Load aligned Longbridge closes.

`run_strategy(prices, StrategyConfig)`
: Stable baseline portfolio backtest.

`run_adaptive_strategy(prices, AdaptiveStrategyConfig)`
: Experimental contribution/rebalance engine.

`generate_weight_grid(...)`
: Enumerate bounded target allocations.

`rank_results(...)`
: Baseline robust multi-objective weight ranking.

`build_walk_forward_windows(...)`
: Chronological train -> test windows.

`static_risk_report(...)`
: Static covariance/correlation, risk contribution, diversification and PCA.

## Validation

Run:

```bash
python -m unittest -v
```

At minimum verify:

- total contribution accounting;
- no negative holdings or overspending;
- weights sum to 1;
- full-grid candidates remain inside bounds;
- no test-period leakage in Walk-Forward;
- risk shares close to 100%;
- underweight DCA never sells on ordinary contribution months;
- threshold rebalance only fires after drift exceeds the configured threshold;
- periodic cadence is respected;
- policy ranking does not collapse to one historical return metric;
- equal-weight default is treated as benchmark, not search center.
