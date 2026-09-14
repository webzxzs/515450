# Longbridge 数据源

这个分支为现有回测增加 **Longbridge 主数据通道**，但不会覆盖原来的 AkShare / HFQ CSV 基线。

## 为什么不直接覆盖 `index_data_hfq.csv`

现有项目使用 AkShare `hfq`（后复权）数据，而 Longbridge 历史 K 线提供：

- `actual`：实际历史成交价格（CLI 默认，`adjust=none`）
- `forward`：前复权价格（CLI `--adjust forward`）

Longbridge 没有与当前 AkShare `hfq` 完全等价的历史 K 线口径。这个项目又使用固定股数、固定月预算，因此价格的绝对水平会直接影响回测，不能把 QFQ/实际价静默伪装成 HFQ。

所以迁移方式是：**保留旧基线 + 新增 Longbridge 入口 + 结果并行比较。**

## 1. 前置条件

安装并登录 Longbridge CLI：

```bash
longbridge update
longbridge auth login
```

确认行情可以读取：

```bash
longbridge kline 515450.SH --period day --count 3
longbridge kline 513130.SH --period day --count 3
```

项目不会保存 Longbridge token，也不会要求把密钥写进仓库。

## 2. 双标回测（推荐）

```bash
python longbridge_dual_backtest.py
```

默认使用 Longbridge **actual / 未复权实际历史价**。现有策略参数仍由 `dual_backtest.py` 管理，原来的参数继续可用：

```bash
python longbridge_dual_backtest.py \
  --hldb-monthly 4500 \
  --hst-buy-pct 0.08 \
  --hst-g1-sell-pct 0.20 \
  --hst-g2-sell-pct 0.50 \
  --hst-shares 100 \
  --n-sims 10
```

Longbridge 专属参数：

```bash
# 强制重新拉取
python longbridge_dual_backtest.py --lb-refresh

# 改用前复权（用于敏感性对比，不建议与旧 HFQ 结果直接横比）
python longbridge_dual_backtest.py --lb-adjust forward

# 控制最早请求日期
python longbridge_dual_backtest.py --lb-start 2020-01-01
```

## 3. 单标 515450 回测

```bash
python longbridge_backtest.py --symbol 515450
```

也可传 Longbridge 标准代码：

```bash
python longbridge_backtest.py --symbol 515450.SH --lb-adjust actual
```

## 4. 缓存

Longbridge 数据不会写回 Git 仓库。默认缓存位置：

- Windows: `%LOCALAPPDATA%/515450-backtest/longbridge/`
- Linux/macOS: `${XDG_CACHE_HOME:-~/.cache}/515450-backtest/longbridge/`

可以自定义：

```bash
# Windows PowerShell
$env:BACKTEST_LONGBRIDGE_CACHE = "D:\market-data\longbridge"

# Linux/macOS
export BACKTEST_LONGBRIDGE_CACHE=/data/market-data/longbridge
```

缓存按 `symbol + adjust` 分离，例如：

```text
515450_SH_actual.csv
513130_SH_actual.csv
515450_SH_forward.csv
```

再次运行时只补缺失日期；`--lb-refresh` 才会忽略已有缓存重新拉取。

## 5. 数据请求策略

`longbridge_data.py` 会：

1. 把 `515450` 映射为 `515450.SH`，`513130` 映射为 `513130.SH`；
2. 使用 `longbridge kline history ... --period day --format json`；
3. 按自然年拆分日期窗口，避免单次历史 K 线数量过大；
4. 统一输出 `date/open/high/low/close/volume/amount`；
5. 去重、排序并保存本地缓存；
6. 将缓存增量刷新到请求截止日期。

## 6. 与现有回测的关系

### `longbridge_dual_backtest.py`

只替换 `dual_backtest.load_hfq_csv()` 这一层。以下逻辑保持原样：

- 双网格策略
- 月度预算
- 布朗桥日内模拟
- 蒙特卡洛
- XIRR / Sharpe / 最大回撤
- ETF 上市前的指数拟合扩展
- Excel / PNG 输出

因此 Longbridge 版本与旧版本的差异主要来自**数据源和复权口径**，便于做 A/B 验证。

### 旧入口仍可用

```bash
python dual_backtest.py
python backtest.py
```

这两个命令继续使用原来的 CSV / AkShare 逻辑，不受 Longbridge 新代码影响。

## 7. 建议验证方式

先分别运行：

```bash
python dual_backtest.py --n-sims 10
python longbridge_dual_backtest.py --n-sims 10
```

重点比较：

- 原始 OHLC 日期覆盖是否一致
- 分红日前后价格跳变
- 网格触发次数
- 累计投入
- 持仓股数
- XIRR / 最大回撤

**不要直接要求 Longbridge actual / forward 与 AkShare HFQ 的最终收益完全一致。** 三种价格口径的经济含义不同。
