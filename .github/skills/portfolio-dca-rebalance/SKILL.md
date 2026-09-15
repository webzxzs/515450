# Portfolio DCA + Rebalance Skill

Use this skill when working on the `515450` repository.

## Project goal

This is a **research-only multi-ETF DCA + rebalancing project** using Longbridge daily market data. It is not a live-trading or order-execution system.

Canonical entrypoints:

```bash
python backtest.py
python weight_sweep.py
python policy_sweep.py
python walk_forward.py
python risk_analysis.py
python adjustment_analysis.py
```

Do not add live-order automation, intraday simulation, Brownian bridge / Monte Carlo grid logic, AkShare, HFQ CSV, or other removed legacy paths unless explicitly requested.

## Current ETF universe

```text
513180.SH  华夏恒生科技ETF
515450.SH  南方标普中国A股大盘红利低波50ETF
513300.SH  华夏纳斯达克100ETF(QDII)
159783.SZ  华夏中证科创创业50ETF
518850.SH  华夏黄金ETF
```

## Fund-provider preference

For the same exposure, prefer 华夏基金 / ChinaAMC when the ChinaAMC product is broadly comparable on tracking quality, fees, liquidity, size, history, tradability and Longbridge data availability.

```text
same exposure + similar quality -> prefer ChinaAMC
material quality disadvantage -> choose the better product
```

Issuer preference only chooses the vehicle. It must never justify portfolio weight.

## Default portfolio is only a benchmark

```text
20% / 20% / 20% / 20% / 20%
```

This is not a recommendation or search center.

## Final research weight bounds

The grid supports per-symbol bounds. Current defaults:

```text
513180.SH   10% ~ 50%
515450.SH   10% ~ 50%
513300.SH   10% ~ 50%
159783.SZ   10% ~ 50%
518850.SH    0% ~ 30%
step              5%
```

Gold is deliberately allowed to reach 0%, so research can conclude that no gold allocation is needed. With the current bounds the default grid has **1,554** allocations. With 16 policy variants, `policy_sweep.py` Stage 1 currently screens **24,864** combinations. Treat these counts as derived values, not permanent assumptions.

## Data alignment

`longbridge_data.py` is the only production market-data adapter.

`load_price_table()` must not delete an entire portfolio date just because one ETF lacks a close. The rule is:

1. outer-join observed dates;
2. start only after every portfolio ETF has at least one observed price;
3. forward-fill the last close for valuation;
4. retain `tradable_<SYMBOL>` flags;
5. never trade a symbol on a date where its tradable flag is false;
6. other tradable ETFs may still trade that day.

Synthetic price tables without tradable flags are treated as fully tradable for backwards-compatible tests.

## Price basis

Default research basis is Longbridge `forward` adjustment. Use `actual` only for raw-price / execution-sensitivity checks. Do not fabricate dividend cash flows when Longbridge does not provide reliable ETF dividend history.

## Research sequence

```text
1. weight_sweep.py
2. policy_sweep.py
3. walk_forward.py
4. risk_analysis.py
5. adjustment_analysis.py
6. only then consider changing long-term defaults
```

Do not promote one historical champion directly into defaults. Prefer stable regions, worst-period resilience, and OOS persistence.

## Baseline and adaptive engines

`backtest.py` is the stable baseline: monthly contributions, periodic rebalancing, fees, lot sizes and residual cash.

`adaptive_strategy.py` supports:

- `target` contribution mode;
- `underweight` contribution mode;
- `periodic`, `threshold`, `either`, or `none` rebalancing.

Research candidates may contain a **0% sleeve**. Strategy validation must allow zero target weights while requiring at least two positive sleeves.

## Risk analysis

Inspect:

- annualized volatility;
- correlation;
- component risk contribution / risk share;
- diversification ratio;
- PCA first-component share;
- effective risk bets;
- rolling and yearly concentration.

Equal capital weights do not imply equal risk.

## Validation

Run:

```bash
python -m unittest -v
```

At minimum preserve tests for:

- contribution and cash accounting;
- no negative holdings / leverage;
- symbol-specific weight bounds;
- 0% gold candidates;
- non-tradable-date behavior;
- no Walk-Forward train/test leakage;
- risk shares approximately summing to 100%;
- underweight DCA not selling on ordinary contribution months;
- threshold and periodic cadence correctness;
- equal-weight benchmark not acting as search center.

## Project status

Feature development is intentionally considered complete after the final research hardening above. Future work should primarily run real Longbridge history, interpret outputs, and refine conclusions rather than add more machinery.
