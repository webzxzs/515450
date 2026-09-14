# 复权与总收益口径

本项目从这一版开始，默认研究口径使用 Longbridge `forward` 前复权价格。

Longbridge 官方文档说明：`--adjust forward` 会对历史 K 线按拆分/分红进行前复权。因此：

- `weight_sweep.py`：默认使用 forward，避免只看价格收益；
- `walk_forward.py`：默认使用 forward，样本外验证基于总收益代理；
- `risk_analysis.py`：默认使用 forward，风险/相关性不被除息跳空污染；
- `backtest.py`：默认也跟随 `config.PRICE_ADJUST=forward`，用于长期定投收益研究；
- 如需看原始市场价格、整手与手续费的执行敏感性，显式使用 `--adjust actual`。

## 为什么不直接伪造分红现金

Longbridge 通用 `dividend` 接口在当前四只 A 股 ETF（513180.SH / 515450.SH / 513300.SH / 159783.SZ）上返回空历史，因此项目不把未知分红金额猜成现金流。

这意味着：

1. `forward` 回测应理解为“总收益代理”；
2. 历史 adjusted price、历史份额和整手成交是研究代理，不是券商真实成交记录；
3. `actual` 回测用于观察原始价格/成交约束；
4. 两者的差异通过 `adjustment_analysis.py` 显式对账。

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

- `adjustment_assets.csv`：逐 ETF 比较 actual 与 forward 的累计收益、年化收益和 adjustment uplift；
- `adjustment_daily_wedges.csv`：逐日记录 actual return、forward return 及两者差值；
- `adjustment_portfolio_comparison.csv`：同一套定投/再平衡参数分别在 actual 和 forward 上回测，比较 XIRR、TWR、Sharpe、最大回撤、费用和期末资产。

如果某只 ETF 的 actual/forward 差异很大，就说明只用未复权价格会显著低估长期持有收益；如果差异接近 0，则复权对该标的当前样本影响很小。
