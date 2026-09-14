# 多 ETF 定投 + 再平衡研究

这是一个使用 **Longbridge** 历史行情的多 ETF 长期资产配置研究项目。

当前 ETF 池：

```text
513180.SH
515450.SH
513300.SH
159783.SZ
```

## 最重要的口径

仓库里的默认组合：

```text
25% / 25% / 25% / 25%
```

**只是方便快速运行的 benchmark，不是推荐比例，也不是搜索中心。**

权重研究默认仍会完整探索：

```text
单只最低权重  10%
单只最高权重  50%
权重步长       5%
完整候选       375 组
```

如果结果稳定，再考虑 2.5% 等更细搜索；不要一开始就假装存在 1% 精度的“最优比例”。

## 默认数据口径：前复权

长期收益研究默认使用：

```text
Longbridge forward
```

即前复权价格。Longbridge 的 forward adjustment 用于处理拆分/分红等调整，因此比未复权价格更适合作为长期总收益研究代理。

需要原始价格敏感性时仍可显式运行：

```bash
python backtest.py --adjust actual
```

项目没有可靠拿到这四只 A 股 ETF 的逐笔 Longbridge dividend history，因此不会伪造分红现金流。`adjustment_analysis.py` 用于对比 actual 与 forward，量化复权带来的差异。

详见：

```text
ADJUSTMENT.md
```

## 当前研究层级

```text
backtest.py            稳定基线回测
weight_sweep.py        完整权重网格探索
policy_sweep.py        权重 + 定投资金方向 + 再平衡规则联合探索
walk_forward.py        严格样本外验证
risk_analysis.py       风险贡献 / 相关性 / PCA
adjustment_analysis.py actual vs forward 对账
```

另外：

```text
adaptive_strategy.py
```

是实验策略引擎，暂时与基线 `backtest.py` 分离，方便公平 A/B。

---

# 1. 稳定基线回测

运行：

```bash
python backtest.py
```

基线策略：

1. 每月固定投入；
2. 普通月按目标权重拆分新资金；
3. 每 N 个定投月全组合再平衡；
4. 先卖超配，再买低配；
5. 不使用杠杆；
6. 考虑手续费、最低佣金、整手和残余现金。

默认：

```text
每月投入          5000 元
再平衡            每 3 个月
复权              forward
沪深 ETF 交易单位 100 份
佣金率            0.0087%
最低佣金          0.1 元
```

示例：

```bash
python backtest.py \
  --portfolio "513180.SH:0.30,515450.SH:0.30,513300.SH:0.20,159783.SZ:0.20" \
  --monthly 6000 \
  --rebalance-months 6
```

权重会自动归一化，`30,30,20,20` 与 `0.3,0.3,0.2,0.2` 等价。

---

# 2. 权重探索

运行：

```bash
python weight_sweep.py
```

不是只找“历史收益最高”的组合，而是同时看：

- XIRR；
- Sharpe；
- 最大回撤；
- 最差分段 XIRR；
- 分段平均 XIRR；
- 分段稳定性；
- HHI 权重集中度。

默认 5% 网格：

```text
10% ~ 50% / ETF
375 组组合
3 个连续时间分段
```

更细搜索：

```bash
python weight_sweep.py --step 0.025
```

输出：

```text
weight_sweep_results.csv
weight_sweep_top.csv
weight_sweep_recommendation.csv
```

---

# 3. 自适应定投 + 再平衡联合探索

这是当前新增的重点。

运行：

```bash
python policy_sweep.py
```

它研究的不只是“配多少”，还研究“钱怎么投进去”和“什么时候真的卖出再平衡”。

## 两种定投方式

### target

每月新资金机械按目标权重拆分。

### underweight

每月新资金优先买当前低配资产，普通月**不卖出**。

目标是让新增现金承担更多纠偏任务，减少不必要的卖出和换手。

## 四类全组合再平衡规则

实验引擎支持：

```text
periodic   固定周期
threshold  偏离阈值
both/either 周期或阈值任一触发
none       只靠新增资金纠偏，不主动卖出再平衡
```

`policy_sweep.py` 默认比较：

```text
定投方式：target / underweight
固定周期：1 / 3 / 6 / 12 个月
偏离阈值：3% / 5% / 10%
以及：不做卖出式再平衡
```

## 不是围绕 25% 优化

联合搜索分两步：

```text
阶段 1
完整 375 权重 × target DCA
完整 375 权重 × underweight DCA
分别找稳健权重区域

阶段 2
合并两边 Top 权重候选
再比较所有定投 / 再平衡规则
```

所以 25/25/25/25 只是保留一条 benchmark，不限制搜索方向。

输出：

```text
adaptive_seed_weight_rankings.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

重点看：

- Top 区域每只 ETF 权重范围；
- 权重标准差；
- underweight DCA 在 Top 中出现比例；
- 哪一种再平衡规则在不同权重下都稳；
- 手续费、交易次数和平均权重偏离。

详见：

```text
ADAPTIVE_POLICY.md
```

---

# 4. Walk-Forward 样本外验证

运行：

```bash
python walk_forward.py
```

默认：

```text
过去 3 年：只用于选权重
未来 12 个月：完全样本外验证
然后向前滚动
```

测试期数据绝不能参与本轮权重选择。

输出：

```text
walk_forward_windows.csv
walk_forward_oos_nav.csv
walk_forward_summary.csv
```

关注：

- 平均 / 中位 / 最差 OOS XIRR；
- 对等权 benchmark 的胜率；
- 对当前默认 benchmark 的胜率；
- 不同窗口选中权重的均值、标准差、最小值和最大值。

如果相邻窗口权重从 10% 跳到 50%，不要继续追求更细精度；这说明参数本身不稳定。

---

# 5. 风险贡献分析

运行：

```bash
python risk_analysis.py
```

计算：

- 每只 ETF 年化波动率；
- 相关性矩阵；
- 组合波动率；
- component risk contribution；
- risk share；
- diversification ratio；
- PCA 第一主成分解释度；
- effective risk bets；
- rolling 1 年风险集中度；
- 分年度风险快照。

即使资本是 25/25/25/25，也可能实际承担的是高度集中的成长风险。

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

---

# 6. 复权敏感性 / 对账

运行：

```bash
python adjustment_analysis.py
```

同时加载 actual 与 forward，比较：

- 每只 ETF 未复权 / 前复权收益；
- 年化收益差；
- 复权差异出现在哪些日期；
- 策略 XIRR / TWR / Sharpe / 最大回撤差异；
- 期末资产、手续费和交易次数差异。

输出：

```text
adjustment_assets.csv
adjustment_daily_wedges.csv
adjustment_portfolio_comparison.csv
```

---

# 推荐研究顺序

当前建议：

```text
1. python adjustment_analysis.py
2. python weight_sweep.py
3. python policy_sweep.py
4. python walk_forward.py
5. python risk_analysis.py
6. 再决定是否修改默认长期比例和执行规则
```

真正值得采用的结论应该同时满足：

- 权重不是历史单点尖峰；
- 执行规则对 1/3/6/12 月或 3%/5%/10% 的小变化不过分敏感；
- Walk-Forward 样本外仍成立；
- 风险贡献没有隐藏的单因子集中；
- actual / forward 敏感性可以解释。

---

# 数据源

只使用 Longbridge。

首次使用前：

```bash
longbridge auth login
```

强制刷新：

```bash
python backtest.py --refresh
python weight_sweep.py --refresh
python policy_sweep.py --refresh
python walk_forward.py --refresh
python risk_analysis.py --refresh
python adjustment_analysis.py --refresh
```

---

# 测试

```bash
python -m unittest -v
```

## 依赖

```bash
pip install numpy pandas openpyxl
```

项目本身不保存 Longbridge 凭据。
