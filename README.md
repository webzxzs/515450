# 多 ETF 定投 + 定期再平衡回测

这是一个使用 **Longbridge** 历史行情的多 ETF 组合回测项目。策略已经从旧的网格/布朗桥/蒙特卡洛体系改为更简单的长期组合策略：

1. 每月固定投入一笔资金；
2. 普通月份按目标权重买入各 ETF；
3. 每隔固定月数，把整个组合重新调回目标权重；
4. 卖出超配资产后再买入低配资产，不使用杠杆；
5. 保留手续费、最低佣金和整手交易约束；
6. 自动与“只定投、不再平衡”做对照。

## 默认组合

```text
513180.SH  25%
515450.SH  25%
513300.SH  25%
159783.SZ  25%
```

默认参数：

```text
每月定投          5000 元
再平衡频率        每 3 个定投月
价格口径          Longbridge actual
沪深 ETF 交易单位 100 份/手
佣金率            0.0087%
最低佣金          0.1 元
```

这些都只是默认值，运行时可直接覆盖。

## 数据源

项目只使用 Longbridge 拉取日 K 数据。数据由 `longbridge_data.py` 缓存在仓库外，不再维护 AkShare、历史 CSV、指数拟合数据或旧网格数据链路。

首次使用前确保 Longbridge CLI 已安装并完成登录：

```bash
longbridge auth login
```

## 快速运行

```bash
python backtest.py
```

强制刷新行情：

```bash
python backtest.py --refresh
```

## 换成任意 ETF 组合

例如调整四只 ETF 权重：

```bash
python backtest.py \
  --portfolio "513180.SH:0.30,515450.SH:0.30,513300.SH:0.20,159783.SZ:0.20" \
  --monthly 6000 \
  --rebalance-months 6
```

权重会自动归一化，所以 `30,30,20,20` 与 `0.3,0.3,0.2,0.2` 等价。

也可以写不带市场后缀的沪深代码；程序会自动补 `.SH` / `.SZ`：

```bash
python backtest.py --portfolio "513180:25,515450:25,513300:25,159783:25"
```

## 再平衡规则

假设 `--rebalance-months 3`：

- 第 1 个月：投入 5000，按目标权重买入；
- 第 2 个月：再次按目标权重投入；
- 第 3 个月：先加入本月 5000，然后把**整个账户**调回目标权重；
- 第 4、5 个月继续定投；
- 第 6 个月再次全组合再平衡。

设置为 `0` 就是纯定投，不做再平衡：

```bash
python backtest.py --rebalance-months 0
```

正常情况下，程序还会自动额外运行一遍纯定投版本作为对照；如不需要：

```bash
python backtest.py --no-benchmark
```

## 交易单位

默认：

- `.SH` / `.SZ`：100 份；
- 其他市场：1 份。

可手动覆盖：

```bash
python backtest.py \
  --portfolio "513180.SH:0.25,515450.SH:0.25,513300.SH:0.25,159783.SZ:0.25" \
  --lot-sizes "513180.SH:100,515450.SH:100,513300.SH:100,159783.SZ:100"
```

如果以后加入港股 ETF，应按实际每手股数覆盖，而不是直接使用默认的 1。

## 主要参数

```text
--portfolio          ETF 与目标权重
--monthly            每月总定投金额
--rebalance-months   每多少个定投月全组合再平衡
--start              回测开始日期
--end                回测结束日期
--adjust             actual / forward
--refresh            强制刷新 Longbridge 缓存
--commission         佣金率
--min-commission     最低佣金
--lot-sizes          各 ETF 交易单位覆盖
--no-benchmark       不运行纯定投对照组
```

## 输出

每次运行生成：

```text
portfolio_summary.csv      # 核心指标
portfolio_daily.csv        # 每日资产、现金、TWR NAV
portfolio_monthly.csv      # 每月定投/再平衡后的组合快照
portfolio_trades.csv       # 所有买卖记录及原因
portfolio_backtest.xlsx    # Excel 汇总

dca_only_summary.csv       # 纯定投对照组摘要
```

核心指标包括 XIRR、现金流调整后的年化 TWR、Sharpe、最大回撤、交易次数、再平衡交易次数和总费用。

## 核心文件

```text
backtest.py        # 策略、组合核算、CLI 与输出
longbridge_data.py # Longbridge 行情获取、标准化和缓存
config.py          # 默认组合与默认参数
LONGBRIDGE.md      # Longbridge 数据层说明
```

## 依赖

```bash
pip install numpy pandas openpyxl
```

另外需要可用的 Longbridge CLI。项目本身不保存 Longbridge 密钥或授权信息。
