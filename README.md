# 多 ETF 定投 + 再平衡研究

这是一个使用 **Longbridge** 历史行情的多 ETF 长期资产配置研究项目。

当前 ETF 池：

```text
513180.SH
515450.SH
513300.SH
159783.SZ
```

## 关键口径

默认组合：

```text
25% / 25% / 25% / 25%
```

**只是 benchmark，不是推荐比例，也不是搜索中心。**

权重研究默认完整探索：

```text
单只最低权重  10%
单只最高权重  50%
权重步长       5%
完整候选       375 组
```

默认长期收益口径：

```text
Longbridge forward
```

即前复权。需要原始价格敏感性时可显式运行：

```bash
python backtest.py --adjust actual
```

项目没有可靠拿到这四只 A 股 ETF 的逐笔 Longbridge dividend history，因此不会伪造分红现金流。`adjustment_analysis.py` 用于 actual vs forward 对账。

## 当前研究工具

```text
backtest.py            稳定基线回测
weight_sweep.py        完整权重网格探索
policy_sweep.py        权重 + 定投资金方向 + 再平衡规则联合探索
walk_forward.py        严格样本外验证
risk_analysis.py       风险贡献 / 相关性 / PCA
adjustment_analysis.py actual vs forward 对账
adaptive_strategy.py   实验型定投 / 再平衡引擎
```

---

## 1. 稳定基线回测

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

权重会自动归一化。

---

## 2. 权重探索

```bash
python weight_sweep.py
```

综合考虑：

- XIRR；
- Sharpe；
- 最大回撤；
- 最差分段 XIRR；
- 分段平均 XIRR；
- 分段稳定性；
- HHI 权重集中度。

默认：

```text
10% ~ 50% / ETF
5% 步长
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

## 3. 自适应定投 + 再平衡联合探索

```bash
python policy_sweep.py
```

它同时研究“配多少”“钱怎么投进去”“什么时候真的卖出再平衡”。

### 两种定投方式

`target`
: 每月新资金按目标权重拆分。

`underweight`
: 每月新资金优先买当前低配资产，普通月不卖出，让新增现金尽量承担纠偏任务。

### 再平衡规则

实验引擎支持：

```text
periodic   固定周期
threshold  偏离阈值
either     周期或阈值任一触发
none       不做卖出式全组合再平衡
```

`policy_sweep.py` 默认实际比较：

```text
定投方式：target / underweight
固定周期：1 / 3 / 6 / 12 个月
偏离阈值：3% / 5% / 10%
以及：none
```

共 16 种执行规则。

### 完整联合搜索，不围绕 25%

阶段 1 直接运行：

```text
375 组权重 × 16 种执行规则 = 6000 组完整历史回测
```

每一种执行规则独立保留自己的 Top 权重候选，因此不会让某一种再平衡方式先替其他规则筛权重。

阶段 2 再对这些候选做连续时间分段稳健性验证：

- 最差分段 XIRR；
- 分段平均 XIRR；
- 分段 XIRR 标准差；
- 最差分段回撤。

默认每种执行规则保留 15 组进入分段验证：

```bash
python policy_sweep.py --screen-top-per-policy 15
```

25/25/25/25 只是 375 组网格里的普通一行，并带 `is_equal_weight_benchmark` 标记。

输出：

```text
adaptive_joint_screen.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

重点看：

- Top 区域每只 ETF 的均值、范围和标准差；
- underweight DCA 在 Top 中占比；
- 哪种执行规则在多组权重下都稳；
- 手续费、再平衡次数和平均权重偏离；
- 参数是否在边界间大幅跳动。

详见 `ADAPTIVE_POLICY.md`。

---

## 4. Walk-Forward 样本外验证

```bash
python walk_forward.py
```

默认：

```text
过去 3 年：训练 / 选权重
未来 12 个月：完全样本外验证
然后向前滚动
```

测试期数据不能参与本轮权重选择。

输出：

```text
walk_forward_windows.csv
walk_forward_oos_nav.csv
walk_forward_summary.csv
```

重点看 OOS XIRR、胜率、最差窗口和权重稳定性。如果相邻窗口权重从 10% 跳到 50%，不要继续追求更细精度。

---

## 5. 风险贡献分析

```bash
python risk_analysis.py
```

计算：

- 每只 ETF 年化波动率；
- 相关性矩阵；
- component risk contribution；
- risk share；
- diversification ratio；
- PCA 第一主成分解释度；
- effective risk bets；
- rolling 1 年与分年度风险集中度。

资本 25/25/25/25 并不意味着风险 25/25/25/25。

---

## 6. 复权敏感性 / 对账

```bash
python adjustment_analysis.py
```

比较 actual 与 forward 下的：

- 每只 ETF 累计和年化收益；
- adjustment wedge；
- XIRR / TWR / Sharpe / 最大回撤；
- 期末资产、手续费、交易次数。

详见 `ADJUSTMENT.md`。

---

## 推荐研究顺序

```text
1. adjustment_analysis.py
2. weight_sweep.py
3. policy_sweep.py
4. walk_forward.py
5. risk_analysis.py
6. 再决定是否修改长期比例和执行规则
```

真正值得采用的结论应同时满足：

- 权重位于稳定区域，不是单点尖峰；
- 1/3/6/12 月或 3%/5%/10% 的小变化不会彻底反转结论；
- Walk-Forward 样本外仍成立；
- 风险贡献没有隐藏的单因子集中；
- actual / forward 差异可以解释。

## 数据源

只使用 Longbridge。首次使用前：

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

## 测试

```bash
python -m unittest -v
```

仓库也包含 GitHub Actions 离线单元测试；CI 不访问 Longbridge 账户数据。

## 依赖

```bash
pip install numpy pandas openpyxl
```

项目本身不保存 Longbridge 凭据。
