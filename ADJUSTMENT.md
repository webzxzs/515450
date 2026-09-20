# 复权与总收益口径

本项目默认研究口径使用 `total_return`：

`Longbridge actual 市价 + dividends.csv 中逐笔现金分红`，并在除息日按分红再投资构造
总收益价格序列。

- `weight_sweep.py` / `policy_sweep.py` / `walk_forward.py` 默认使用 total_return；
- `risk_analysis.py` 默认使用 total_return，避免现金分红制造虚假价格跳空；
- `backtest.py` 跟随 `config.PRICE_ADJUST=total_return`；
- 如需看原始市场价格、整手与手续费的执行敏感性，显式使用 `--adjust actual`。
- `--adjust forward` 只保留为 Longbridge 复权诊断，不再作为长期研究默认值。

## 显式分红数据

`dividends.csv` 保存当前 universe 已核实的 ETF 现金分红。现在有明确现金分红历史的是
`515450.SH`，2021-11 到 2026-09 共 9 次，累计 0.455 元/份。

当前 universe：

```text
513180.SH
515450.SH
513300.SH
159783.SZ
518850.SH
```

其他标的没有核实到现金分红时，不制造未知现金流；其 total_return 序列等于 actual
价格序列。

515450 的显式分红重建与公开累计净值方向一致，而 Longbridge forward 明显高估该 ETF
的累计总收益，因此 forward 被降级为诊断口径。

## 分红数据更新

联网更新不由回测代码隐式执行，而是通过：

```bash
python update_dividends.py
python update_dividends.py --write
```

更新器先用 AKShare 的 `fund_etf_dividend_sina` 获取 ETF 累计分红并转成逐次现金分红，
再用 `fund_fh_em`（东方财富）补齐权益登记日、除息日和发放日。两套来源逐笔金额和
除息日完全一致后，才允许用 `--write` 覆盖 `dividends.csv`。

回测本身始终读取仓库内的冻结快照，不联网抓分红，以保证结果可复现。

## 对账

运行：

```bash
python adjustment_analysis.py
```

输出：

```text
adjustment_assets.csv
adjustment_daily_wedges.csv
adjustment_portfolio_comparison.csv
```

其中：

- `adjustment_assets.csv`：逐 ETF 比较 actual / explicit total_return / Longbridge forward；
- `adjustment_daily_wedges.csv`：逐日记录 actual return、forward return 及两者差值；
- `adjustment_portfolio_comparison.csv`：同一策略在三种口径上对比。

对当前 universe，最重要的口径差异来自 515450。长期研究以 explicit total_return 为准。
