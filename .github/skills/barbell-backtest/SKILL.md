---
name: barbell-backtest
description: >
  Use when: working with the 515450/513130 barbell grid strategy project.
  Covers running backtests, tuning parameters, interpreting results, fixing
  chart/metric bugs, adding new sweep stages, or updating the codebase.
  Trigger phrases: barbell backtest, dual grid, 515450, 513130, dual_backtest,
  param sweep, grid strategy, XIRR, Sharpe, parameter optimization.
---

# Barbell Grid Strategy — Copilot Skill

## Project at a Glance

| Item | Value |
|------|-------|
| Main script | `dual_backtest.py` |
| Strategy | Double-grid (G1 + G2) + monthly DCA, two ETFs |
| Assets | 515450 红利低波 (HLDB) 90% + 513130 恒科 (HST) 10% |
| Backtest period | 2020-08-17 ~ 2026-04-27 (5.7 yr) |
| Key metrics | Sharpe=0.3308  XIRR=9.06%  MaxDD=-19.11% |
| Output files | `dual_backtest.png`, `dual_backtest.xlsx` |

---

## File Map

| File | Role |
|------|------|
| `dual_backtest.py` | **Core engine** — loads data, runs MC, plots, exports Excel |
| `backtest.py` | Single-asset backtest (515450 only) |
| `config.py` | Single-asset config (used by `backtest.py`) |
| `dual_sweep2.py` | Round 2 greedy 3-stage param sweep (sequential) |
| `dual_sweep2_mp.py` | Round 2 sweep (multi-process, auto-detects CPU cores) |
| `param_sweep_515450.py` | Single-asset grid sweep |
| `_fetch_index.py` | Download HST index + splice with ETF |
| `iwencai_etf_selector.py` | 问财 ETF selector (dependency of `backtest.py`) |
| `dual_sweep2_best.txt` | Top-20 Round 2 results with ★ recommended row |
| `dual_sweep2_full.csv` | Full Round 2 results (924 combos) |

---

## Key API — `dual_backtest.py`

### Module-level globals (patch before calling `bt.run`)

```python
import dual_backtest as db

# Budget
db.HLDB_MONTHLY   = 4500.0   # 515450 monthly budget
db.HST_MONTHLY    = 500.0    # 513130 monthly budget
db.MONTHLY_BUDGET = 5000.0

# HLDB grid
db.HLDB_G1_BUY   = 0.020;  db.HLDB_G2_BUY   = 0.030
db.HLDB_G1_SELL  = 0.15;   db.HLDB_G2_SELL  = 0.50
db.HLDB_G1_SH    = 1200;   db.HLDB_G2_SH    = 1200

# HST grid
db.HST_G1_BUY    = 0.08;   db.HST_G2_BUY    = 0.08
db.HST_G1_SELL   = 0.20;   db.HST_G2_SELL   = 0.50
db.HST_G1_SH     = 100;    db.HST_G2_SH     = 100

db.N_SIMS = 1   # speed up sweeps; use 10 for final runs
```

### Running a backtest

```python
hldb_df   = db.load_with_index_extension(db.HLDB_CSV, db.HLDB_INDEX_CSV, "515450")
hst_df    = db.load_with_index_extension(db.HST_CSV,  db.HST_INDEX_CSV,  "513130")
merged_df = db.build_aligned(hldb_df, hst_df)

rng = np.random.default_rng(42)
bt  = db.DualGridBacktester()
rec_df, _ = bt.run(merged_df, rng)
# rec_df columns: ['date', 'hldb_val', 'hst_val', 'total_val', 'total_inv']
# _ is a list of column name strings (NOT trade tuples)
```

### Metric helpers

```python
sharpe = db.calc_sharpe(rec_df["total_val"].values, rec_df["total_inv"].values)
maxdd  = db.calc_maxdd(rec_df["total_val"].values,  rec_df["total_inv"].values)
days   = (rec_df["date"].iloc[-1] - rec_df["date"].iloc[0]).days
ann    = db.calc_ann(pnl, final_inv, days)

cfs = list(bt.cashflows)          # list of (date, amount) tuples — negative = outflow
cfs.append((rec_df["date"].iloc[-1], final_val))
xirr = db.calc_xirr(cfs)
```

---

## Running from CLI

```bash
# Regenerate chart + Excel with current defaults
python dual_backtest.py --n-sims 10

# Override budget and HST params
python dual_backtest.py \
  --hldb-monthly 4500 \
  --hst-buy-pct 0.08 \
  --hst-g1-sell-pct 0.20 \
  --hst-g2-sell-pct 0.50 \
  --hst-shares 100 \
  --n-sims 10
```

---

## Param Sweep Workflow

### Round 2 stages (greedy, already complete)

| Stage | Fixed | Swept | Combos |
|-------|-------|-------|--------|
| A | HST defaults | HLDB buy pairs × shares | 90 |
| B | HLDB best | HST buy pairs × sell pairs × shares | 924 |
| C | HLDB+HST best | Budget ratio (200 step) | 15 |

```bash
python dual_sweep2_mp.py   # ~3 min on 16-core
```

### Reading sweep results

```python
import pandas as pd
df = pd.read_csv("dual_sweep2_full.csv")
df.sort_values("sharpe", ascending=False).head(10)
```

Best params are in `dual_sweep2_best.txt` — ★ marks the **recommended** 9:1 row.

---

## Data Pipeline

### Data files hierarchy

```
etf_513130.csv          ← raw 513130 ETF OHLC (input to _fetch_index.py)
index_hstech.csv        ← Hang Seng Tech index (downloaded by _fetch_index.py)
combined_hst.csv        ← spliced output (index pre-2021 + ETF post-2021)
hst_hfq.csv             ← 513130 HFQ (used by dual_backtest.py)  ← authoritative
index_data_hfq.csv      ← 515450 HFQ data                        ← authoritative
index_data.csv          ← A500 index (used for index extension fit)
```

### Refreshing 515450 data

```bash
python _fetch_index.py   # updates index_hstech.csv + combined_hst.csv
```

To refresh `hst_hfq.csv` or `index_data_hfq.csv`, use akshare directly.

---

## Common Bugs & Fixes

### Chart shows -100% return at start
**Cause**: `total_inv=0` before first purchase + any `clip(lower=1)` → val/1 - 1 ≈ -100%.  
**Fix**: Filter `total_inv > 0` before computing returns:
```python
valid = rec_df["total_inv"] > 0
rdf_plot = rec_df[valid].copy()
ret = (rdf_plot["total_val"] / rdf_plot["total_inv"] - 1.0) * 100
```

### Lookahead bias in budget ratio
The sweep-optimal 4800:200 split (Sharpe=0.3511) is derived from historical data.  
**Use the prior 9:1 (4500:500)** — Sharpe=0.3308, difference is not significant.  
Grid thresholds (G1_BUY, G2_BUY, etc.) are structural rules — less prone to this bias.

### `trade_list` from `bt.run()` is NOT trade tuples
`rec_df, trade_list = bt.run(...)` — `trade_list` is a list of **column name strings**,  
not `(action, date, price, shares)` tuples. Use `rec_df` for account value tracking.

### Multi-process sweep loop unpacking
```python
# WRONG
for i, (hb1, hb2), hsh in itertools.product(range(n), buy_pairs, shares):

# CORRECT
for (hb1, hb2) in HLDB_BUY_PAIRS:
    for hsh in HLDB_SHARES_GRID:
```

---

## Current Optimal Parameters

```
# HLDB (515450)
G1_BUY=2%   G2_BUY=3%   G1_SELL=15%   G2_SELL=50%   SHARES=1200

# HST (513130)
G1_BUY=8%   G2_BUY=8%   G1_SELL=20%   G2_SELL=50%   SHARES=100

# Budget (9:1 prior, no lookahead)
HLDB=4500  HST=500  TOTAL=5000

# Results
Sharpe=0.3308  Ann=+4.60%  XIRR=+9.06%  MaxDD=-19.11%
```
