# 多 ETF 定投 + 定期再平衡回测

这是一个使用 **Longbridge** 历史行情的多 ETF 组合研究项目。策略已经从旧的网格/布朗桥/蒙特卡洛体系改为更简单的长期组合策略：

1. 每月固定投入一笔资金；
2. 普通月份按目标权重买入各 ETF；
3. 每隔固定月数，把整个组合重新调回目标权重；
4. 卖出超配资产后再买入低配资产，不使用杠杆；
5. 保留手续费、最低佣金和整手交易约束；
6. 自动与“只定投、不再平衡”做对照。

项目现在包含四层研究：**正式回测、权重探索、Walk-Forward 样本外验证、风险贡献分析**。

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

## 权重探索

`weight_sweep.py` 用来探索这四只 ETF 的合理长期权重。它不是简单寻找“历史收益最高”的单一点，而是同时考虑：

- 全周期 XIRR；
- 全周期 Sharpe；
- 最大回撤；
- 3 个连续时间子区间里的最差 XIRR；
- 子区间平均 XIRR；
- 子区间收益稳定性；
- 组合集中度。

默认搜索：

```text
单只最低权重   10%
单只最高权重   50%
搜索步长       5%
时间分段       3 段
候选组合       375 组
```

运行：

```bash
python weight_sweep.py
```

更细的 2.5% 搜索：

```bash
python weight_sweep.py --step 0.025 --min-weight 0.10 --max-weight 0.50
```

默认综合评分权重：

```text
全周期 XIRR       25%
最差分段 XIRR     25%
全周期 Sharpe     15%
最大回撤          15%
分段平均 XIRR     10%
分段稳定性         5%
分散度             5%
```

程序会额外计算 Top 候选区域的平均权重，并推荐一个最接近该区域中心的**真实网格候选**，避免把单一历史最优点直接当作最终答案。

输出：

```text
weight_sweep_results.csv
weight_sweep_top.csv
weight_sweep_recommendation.csv
```

## Walk-Forward 样本外验证

`walk_forward.py` 用来回答更重要的问题：**历史上选出来的“好比例”，在当时未知的未来一年里是否仍然有效？**

默认流程：

```text
过去 3 年：训练 / 选权重
未来 12 个月：完全样本外验证
然后窗口向前滚动 12 个月，重复
```

每一个测试窗口的权重只能由它之前的数据决定，测试期不会参与选参。训练期内部仍使用 `weight_sweep.py` 的多目标稳健评分，而不是按单一历史收益挑冠军。

运行：

```bash
python walk_forward.py
```

常用参数：

```bash
python walk_forward.py \
  --train-years 3 \
  --test-months 12 \
  --step 0.05 \
  --min-weight 0.10 \
  --max-weight 0.50
```

主要比较：

- 每个 OOS 窗口选中的比例；
- OOS XIRR / TWR / Sharpe / 最大回撤；
- 相对等权组合的 OOS 超额；
- 相对当前默认组合的 OOS 超额；
- 每只 ETF 被选中权重的均值、波动、最小值、最大值；
- 各 OOS 窗口 TWR 拼接后的 Sharpe、最大回撤和年化 TWR。

输出：

```text
walk_forward_windows.csv   # 每轮训练/测试日期、选中比例、OOS 指标
walk_forward_oos_nav.csv   # 各独立 OOS 窗口的 TWR 拼接路径
walk_forward_summary.csv   # 总体 OOS 表现和权重稳定性
```

注意：这是**参数选择验证器**，不是一条连续实盘账户的完整模拟。每个测试窗口会独立启动一个定投账户，以隔离“选权重是否有效”这个问题；拼接 NAV 只用于统一观察 OOS 风险，不应当冒充真实连续账户的资金曲线。

## 风险贡献 / 相关性 / PCA

`risk_analysis.py` 用来检查“资本上四等分”是否真的等于“风险上四等分”。

运行：

```bash
python risk_analysis.py
```

它会计算：

- 每只 ETF 年化波动率；
- 完整相关性矩阵；
- 组合年化波动率；
- 每只 ETF 的 component risk contribution；
- **capital weight → risk share**；
- diversification ratio；
- PCA 第一主成分解释度；
- effective risk bets；
- rolling 1 年组合波动、平均相关性、PC1 占比、最大风险贡献；
- 分年度风险快照。

如果四只 ETF 是 25%/25%/25%/25%，但三只成长 ETF 合计贡献了 80% 的风险，这里会直接显示出来。

默认滚动窗口：

```text
242 个交易日
每 21 个交易日记录一次
```

也可以修改：

```bash
python risk_analysis.py --rolling-window 484 --rolling-stride 21
```

输出：

```text
risk_summary.csv
risk_contribution.csv
risk_correlation.csv
risk_covariance_annual.csv
risk_pca.csv
risk_rolling.csv
risk_by_year.csv
```

## 推荐研究顺序

不要直接把 `weight_sweep.py` 的第一名写回默认组合。更合理的顺序是：

```text
1. python weight_sweep.py
2. python walk_forward.py
3. python risk_analysis.py
4. 再决定是否修改长期目标权重
```

一个比例只有在下面三件事同时成立时才更值得信任：

- 全样本不是单点尖峰，而是位于一片稳定的优秀区域；
- Walk-Forward 样本外仍能维持合理表现；
- 风险贡献没有隐藏的单一成长因子集中。

## 数据源

项目只使用 Longbridge 拉取日 K 数据。数据由 `longbridge_data.py` 缓存在仓库外，不再维护 AkShare、历史 CSV、指数拟合数据或旧网格数据链路。

首次使用前确保 Longbridge CLI 已安装并完成登录：

```bash
longbridge auth login
```

强制刷新 Longbridge 行情：

```bash
python backtest.py --refresh
python weight_sweep.py --refresh
python walk_forward.py --refresh
python risk_analysis.py --refresh
```

## 快速运行正式回测

```bash
python backtest.py
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

## 正式回测主要参数

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

## 正式回测输出

```text
portfolio_summary.csv
portfolio_daily.csv
portfolio_monthly.csv
portfolio_trades.csv
portfolio_backtest.xlsx
dca_only_summary.csv
```

核心指标包括 XIRR、现金流调整后的年化 TWR、Sharpe、最大回撤、交易次数、再平衡交易次数和总费用。

## 核心文件

```text
backtest.py          # 策略、组合核算、CLI 与输出
weight_sweep.py      # 全历史多目标权重探索
walk_forward.py      # 严格时间顺序的样本外权重验证
risk_analysis.py     # 风险贡献、相关性、PCA、滚动风险
longbridge_data.py   # Longbridge 行情获取、标准化和缓存
config.py            # 默认组合与默认参数
LONGBRIDGE.md        # Longbridge 数据层说明
```

## 测试

```bash
python -m unittest -v
```

## 依赖

```bash
pip install numpy pandas openpyxl
```

另外需要可用的 Longbridge CLI。项目本身不保存 Longbridge 密钥或授权信息。
