# Portfolio DCA + Rebalance Skill

Use this skill when working on the `515450` repository.

## Project goal

The repository implements a **multi-ETF DCA + rebalancing research system** using Longbridge daily market data. It includes baseline backtests, robust weight discovery, Walk-Forward OOS validation, risk decomposition, adjustment reconciliation, and experimental adaptive contribution/rebalance policies.

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

## Current ETF universe

```text
513180.SH  华夏恒生科技ETF
515450.SH  南方标普中国A股大盘红利低波50ETF
513300.SH  华夏纳斯达克100ETF(QDII)
159783.SZ  华夏中证科创创业50ETF
518850.SH  华夏黄金ETF
```

Gold was added deliberately as a distinct real-asset / defensive sleeve rather than another equity sleeve. The preferred gold product is `518850.SH` because the user prefers ChinaAMC products when the investment product itself is sufficiently competitive. The product preference must not be confused with a fixed gold allocation.

## Fund-provider selection preference

When adding or replacing an ETF/fund in this project, **prefer 华夏基金 / ChinaAMC products whenever the ChinaAMC candidate is materially comparable to the best alternatives**.

This is a persistent product-selection preference, not an unconditional issuer lock-in.

Use the following decision order:

1. First define the required exposure / index / asset role. Do not change the intended exposure merely to use a ChinaAMC product.
2. Identify the strongest investable products for that exposure.
3. Compare at least the important practical dimensions when data is available: tracking quality, fees, liquidity / turnover, fund size, listing history, spread / tradability, and data availability in Longbridge.
4. If the ChinaAMC product is broadly comparable and has no meaningful structural disadvantage, choose the ChinaAMC product by default.
5. A small disadvantage is acceptable when it is unlikely to materially affect long-run implementation, because consolidating holdings under ChinaAMC has user value through account / membership benefits.
6. Do **not** choose ChinaAMC if doing so creates a material disadvantage, such as clearly worse liquidity, substantially higher fees, poor tracking, insufficient history, unreliable data availability, or a meaningfully different underlying exposure.
7. When choosing a non-ChinaAMC product despite this preference, explicitly record why the product-quality advantage is large enough to override the ChinaAMC preference.

In short:

```text
same exposure + similar quality -> prefer ChinaAMC
material quality disadvantage -> choose the better product
```

The fund-company preference affects **which vehicle represents an exposure**. It must never be used as evidence for how much portfolio weight that exposure deserves.

## Default portfolio is only a benchmark

```text
513180.SH 20%
515450.SH 20%
513300.SH 20%
159783.SZ 20%
518850.SH 20%
```

This equal-weight mix is **not** an assumed optimum or recommendation. It exists only for quick runs and benchmark comparison. Weight research must continue to search the configured bounded grid.

With the default five-asset universe and default constraints:

```text
Weight step: 5%
Min per ETF: 10%
Max per ETF: 50%
Full weight grid: 976 combinations
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

## Default research parameters

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
1. weight_sweep.py        -> broad full-grid weight discovery
2. policy_sweep.py        -> jointly test weights + contribution/rebalance rules
3. walk_forward.py        -> strict chronological OOS validation
4. risk_analysis.py       -> capital weights vs actual risk concentration
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

Prefer broad stable regions over fragile point optima. Pay particular attention to whether the gold weight remains in a similar range across top candidates, folds, and OOS windows.

## Adaptive policy exploration

With the current five-ETF universe, `policy_sweep.py` treats 20/20/20/20/20 only as a benchmark.

Default policy set:

- target vs underweight contribution;
- periodic rebalancing every 1 / 3 / 6 / 12 months;
- threshold rebalancing at 3% / 5% / 10% drift;
- no sell-based full rebalancing.

This is 16 execution rules. With the default 976-weight grid, Stage 1 screens:

```text
976 × 16 = 15,616 full-history combinations
```

Each policy must keep its own top candidates before fold validation so one rebalance style cannot pre-filter the weights for every other style.

Primary outputs:

```text
adaptive_joint_screen.csv
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

Gold is included specifically to test whether the portfolio gains a genuinely distinct risk driver. Equal capital weights or low HHI alone are not proof of diversification.

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
- five-asset default grid has 976 candidates at 5% / 10%-50%;
- full-grid candidates remain inside bounds;
- no test-period leakage in Walk-Forward;
- risk shares close to 100%;
- underweight DCA never sells on ordinary contribution months;
- threshold rebalance only fires after drift exceeds the configured threshold;
- periodic cadence is respected;
- policy ranking does not collapse to one historical return metric;
- equal-weight default is treated as benchmark, not search center.
