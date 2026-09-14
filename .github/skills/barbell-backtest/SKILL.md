# Barbell Backtest Skill

Use this project for the 515450 + 513130 dual-ETF barbell strategy.

## Data source

Longbridge is the only supported market-data source.

- 515450 -> `515450.SH`
- 513130 -> `513130.SH`
- default adjustment: `actual`
- optional sensitivity test: `forward`
- cache is managed by `longbridge_data.py` outside the repository

Do not restore or depend on AkShare, HFQ CSV snapshots, or local index-extension CSVs unless the user explicitly asks for a separate migration experiment.

## Main backtest

```bash
python backtest.py
```

Useful options:

```bash
python backtest.py --lb-refresh
python backtest.py --lb-adjust forward
python backtest.py --monthly-total 5000 --hldb-monthly 4500 --n-sims 10
```

`backtest.py` delegates to `longbridge_dual_backtest.py`, which injects Longbridge data into `dual_backtest.py` while leaving the strategy engine/data-source boundary explicit.

## Parameter sweep

Sequential:

```bash
python longbridge_dual_sweep2.py
```

Multiprocessing:

```bash
python longbridge_dual_sweep2_mp.py
```

The underlying `dual_sweep2.py` and `dual_sweep2_mp.py` are core sweep engines. Do not run them directly in the normal workflow because their internal loader interface is intentionally data-source-neutral; use the Longbridge entrypoints above.

## Current strategy defaults

515450:
- monthly budget 4500
- G1 buy 2%, sell 15%, 1200 shares
- G2 buy 3%, sell 50%, 1200 shares

513130:
- monthly budget 500
- G1/G2 buy 8%
- G1 sell 20%, G2 sell 50%
- 100 shares per grid

Total monthly budget: 5000.

## Architecture rule

Keep strategy/accounting logic in `dual_backtest.py` independent from the data provider. Longbridge-specific authentication, symbol normalization, pulling and caching belong in `longbridge_data.py` and thin entrypoint adapters.
