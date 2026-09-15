# 多 ETF 定投与再平衡研究框架

这是一个基于 **Longbridge 日线行情**的个人长期资产配置研究项目。

项目不追求一个看起来很精确的“历史最优比例”，而是研究：

- 五类资产长期应该如何分配；
- 每月新增资金应该机械按目标比例买，还是优先补低配资产；
- 再平衡应该按固定周期还是按权重偏离触发；
- 历史上表现好的比例能否在未来未知年份继续成立；
- 名义上的资金分散是否真的形成了风险分散；
- 黄金加入后，是否真正提供了不同于股票成长因子的风险来源；
- 前复权与原始价格口径是否会改变结论。

当前项目已经从简单的 ETF 回测脚本，发展成一个围绕 **权重发现、执行规则、样本外验证、风险分解和数据口径对账** 的小型研究框架。

---

# 当前 ETF universe

| 代码 | 资产 / 作用 | 基金管理人 |
| --- | --- | --- |
| `513180.SH` | 恒生科技 | 华夏基金 |
| `515450.SH` | A股红利低波 | 南方基金 |
| `513300.SH` | 纳斯达克100 | 华夏基金 |
| `159783.SZ` | 科创创业50 | 华夏基金 |
| `518850.SH` | 黄金 | 华夏基金 |

新增的黄金资产使用：

```text
518850.SH 华夏黄金ETF
```

选择它的原因不是假定它收益最高，而是：

1. 黄金本身提供与股票不同的实物资产 / 防御风险因子；
2. 产品成立时间足以覆盖当前组合公共历史；
3. Longbridge 可以正常识别并返回该标的行情；
4. 在产品本身足够合格的前提下，优先使用华夏基金产品，便于账户和会员体系统一。

> **基金公司的偏好只决定用哪只黄金 ETF，不决定黄金应该配多少。**

---

# 默认组合只是 benchmark

`config.py` 当前默认：

```text
513180.SH  20%
515450.SH  20%
513300.SH  20%
159783.SZ  20%
518850.SH  20%
```

这只是方便直接运行的 **五等权 benchmark**：

> **不是推荐比例，也不是搜索中心。**

真正的权重研究默认完整探索：

```text
单只最低权重   10%
单只最高权重   50%
权重步长        5%
完整候选       976 组
```

如果 5% 网格已经出现稳定区域，再考虑 2.5% 精扫；不建议一开始就追求 1% 或小数点级别的“最优权重”。

---

# 研究原则

## 1. 不把历史第一名直接当答案

历史最优点很容易只是噪声。真正值得关注的是：

- Top 区域是否集中在一片相似权重；
- 相邻参数变化后结果是否仍然稳定；
- 最差时间段是否仍然能接受；
- Walk-Forward 样本外是否继续有效；
- 黄金权重是否在不同窗口里仍落在相近区间。

## 2. 权重和执行规则一起研究

一个比例在“每 3 个月再平衡”下表现好，不代表它在“低配优先定投 + 5% 阈值再平衡”下仍然最好。

因此项目联合研究：

```text
目标权重
×
月度资金分配方式
×
再平衡规则
```

## 3. 样本外优先于样本内漂亮

`walk_forward.py` 严格执行：

```text
过去数据选参数
→
未来数据只负责验证
```

测试期不会反过来参与本轮参数选择。

## 4. 资本分散不等于风险分散

20% × 5 只说明资金平均，不说明风险平均。

股票类 ETF 可能共同承担主要波动，而黄金可能只占较小风险贡献；也可能在某些年份反过来成为主要波动来源。`risk_analysis.py` 用实际协方差和风险贡献判断，而不是只看资本权重。

## 5. 长期收益默认使用前复权口径

默认：

```text
Longbridge forward
```

即前复权价格。

如需检查原始市场价格、整手、费用和复权敏感性：

```bash
python backtest.py --adjust actual
```

---

# 项目结构

| 文件 | 作用 |
| --- | --- |
| `backtest.py` | 稳定基线：定投 + 固定周期全组合再平衡 |
| `adaptive_strategy.py` | 实验引擎：低配优先定投、周期/阈值再平衡 |
| `weight_sweep.py` | 完整权重网格的稳健搜索 |
| `policy_sweep.py` | 权重 + 定投方式 + 再平衡规则联合搜索 |
| `walk_forward.py` | 严格时间顺序的样本外验证 |
| `risk_analysis.py` | 相关性、风险贡献、PCA、滚动风险集中度 |
| `adjustment_analysis.py` | actual vs forward 复权口径对账 |
| `longbridge_data.py` | Longbridge 日 K 获取、标准化和本地缓存 |
| `config.py` | 默认 ETF universe 和基础参数 |
| `ADAPTIVE_POLICY.md` | 自适应定投 / 再平衡方法说明 |
| `ADJUSTMENT.md` | 复权研究说明 |
| `LONGBRIDGE.md` | Longbridge 数据层说明 |

---

# 快速开始

## 1. 安装依赖

```bash
pip install numpy pandas openpyxl
```

## 2. 登录 Longbridge CLI

```bash
longbridge auth login
```

项目本身不保存 Longbridge 凭据。

## 3. 跑基础回测

```bash
python backtest.py
```

## 4. 做完整组合研究

推荐顺序：

```bash
python adjustment_analysis.py
python weight_sweep.py
python policy_sweep.py
python walk_forward.py
python risk_analysis.py
```

当前阶段，比继续增加新的优化器更重要的是把这些真实数据结果跑出来并解释。

---

# 默认参数

```text
ETF universe         513180 / 515450 / 513300 / 159783 / 518850
默认 benchmark       20% / 20% / 20% / 20% / 20%
每月投入             5000 元
基线再平衡           每 3 个定投月
研究价格口径         forward 前复权
沪深 ETF 交易单位    100 份
佣金率               0.0087%
最低佣金             0.1 元
```

所有关键参数都可以通过 CLI 覆盖。

---

# 1. 基线回测：`backtest.py`

```bash
python backtest.py
```

基线策略保持故意简单：

1. 每月第一个共同交易日投入固定资金；
2. 普通月份按目标权重拆分当月新增资金；
3. 每 N 个定投月对整个账户做一次再平衡；
4. 先卖出超配资产，再买入低配资产；
5. 不使用杠杆；
6. 考虑整手、佣金、最低佣金和残余现金。

示例：

```bash
python backtest.py \
  --portfolio "513180.SH:0.25,515450.SH:0.25,513300.SH:0.20,159783.SZ:0.15,518850.SH:0.15" \
  --monthly 6000 \
  --rebalance-months 6
```

权重会自动归一化。

主要指标：

- XIRR；
- 现金流调整后的年化 TWR；
- Sharpe；
- 最大回撤；
- 期末资产；
- 总手续费；
- 交易次数；
- 再平衡次数；
- 期末各 ETF 权重和份额。

输出：

```text
portfolio_summary.csv
portfolio_daily.csv
portfolio_monthly.csv
portfolio_trades.csv
portfolio_backtest.xlsx
dca_only_summary.csv
```

---

# 2. 权重搜索：`weight_sweep.py`

```bash
python weight_sweep.py
```

默认扫描：

```text
5 只 ETF
10% ~ 50% / ETF
5% 步长
976 组权重
3 个连续时间分段
```

综合评分：

```text
全周期 XIRR          25%
最差分段 XIRR        25%
全周期 Sharpe        15%
最大回撤             15%
分段平均 XIRR        10%
分段稳定性            5%
权重分散度 / HHI      5%
```

程序不会机械选择历史第一名，而会计算 Top 区域的权重中心，并返回一个最靠近稳定区域中心的真实网格候选。

尤其关注：

```text
weight_518850.SH
```

如果黄金在优秀候选中长期集中在例如 10%~20%，这个区间比某个精确的 15% 更值得信任；如果它从 10% 到 50% 都能出现，则说明当前样本不足以识别精确黄金权重。

输出：

```text
weight_sweep_results.csv
weight_sweep_top.csv
weight_sweep_recommendation.csv
```

更细搜索：

```bash
python weight_sweep.py --step 0.025
```

只建议在 5% 网格已经出现明显稳定区域后使用。

---

# 3. 联合策略搜索：`policy_sweep.py`

```bash
python policy_sweep.py
```

它同时研究：

- 五只 ETF 各配多少；
- 每月钱怎么投进去；
- 什么时候值得真正卖出并重新平衡。

## 两种定投方式

### `target`

每月新增资金机械按目标权重拆分。

### `underweight`

每个月先看当前组合哪个 ETF 最低配，新增资金优先补低配资产。

普通定投月：

```text
只买，不卖
```

尽量让新增资金承担再平衡工作，减少不必要卖出和换手。

## 再平衡规则

```text
periodic    固定周期再平衡
threshold   偏离阈值触发
either      周期或阈值任一触发
none        完全不主动卖出式再平衡
```

默认实际比较：

```text
定投方式：target / underweight
周期：1 / 3 / 6 / 12 个月
阈值：3% / 5% / 10%
以及：none
```

共 16 种执行规则。

## Stage 1：完整联合筛选

```text
976 组权重 × 16 种规则 = 15,616 组完整历史回测
```

每一种规则都会在完整权重网格中独立寻找自己的优秀候选，所以不存在“先假定 20% 等权”或“先假定每 3 个月再平衡”再围绕它优化。

## Stage 2：分段稳健性验证

每种执行规则默认保留自己的 Top 15 候选，再进行连续时间分段验证。

重点检查：

- 最差分段 XIRR；
- 平均分段 XIRR；
- 分段 XIRR 标准差；
- 最差分段回撤；
- 手续费；
- 再平衡次数；
- 平均权重偏离。

输出：

```text
adaptive_joint_screen.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

最值得先看：

```text
adaptive_top_region.csv
```

不要只看最终第一名。

详见 [ADAPTIVE_POLICY.md](ADAPTIVE_POLICY.md)。

---

# 4. Walk-Forward：`walk_forward.py`

```bash
python walk_forward.py
```

默认：

```text
过去 3 年训练 / 选权重
未来 12 个月完全样本外验证
然后窗口向前滚动
```

核心原则：

> **任何测试期数据都不能进入本轮训练和参数选择。**

重点看：

- 每个 OOS 窗口的 XIRR；
- OOS 平均 / 中位数 / 最差表现；
- 相对五等权 benchmark 的胜率；
- 每个窗口选出的权重是否稳定；
- 黄金权重跨窗口是否稳定；
- 拼接后的 OOS TWR、Sharpe 和最大回撤。

如果相邻窗口某只 ETF 的权重反复从 10% 跳到 50%，即使平均收益不错，也说明不应该相信一个精确比例。

输出：

```text
walk_forward_windows.csv
walk_forward_oos_nav.csv
walk_forward_summary.csv
```

---

# 5. 风险贡献：`risk_analysis.py`

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
- rolling 1 年风险集中度；
- 分年度风险快照。

黄金加入后，这一层尤其重要。

真正要验证的是：

> 加入 518850 后，组合的有效风险因子是否真的增加，而不是只多了一行持仓。

如果 PCA 第一主成分占比下降、effective risk bets 上升、股票类 ETF 风险贡献集中度下降，才说明黄金确实提供了组合层面的分散价值。

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

# 6. 复权敏感性：`adjustment_analysis.py`

```bash
python adjustment_analysis.py
```

比较 actual 与 forward 下的：

- 每只 ETF 累计和年化收益；
- adjustment wedge；
- XIRR / TWR / Sharpe / 最大回撤；
- 期末资产、手续费、交易次数。

详见 [ADJUSTMENT.md](ADJUSTMENT.md)。

---

# 如何判断一个比例值得采用

不要因为某个组合排第一就修改默认比例。

一个候选更值得信任，至少应该同时满足：

1. **不是孤立尖峰**：附近权重组合也表现不错；
2. **分段稳定**：不同历史阶段没有明显崩塌；
3. **Walk-Forward 有效**：未来未知窗口仍有合理表现；
4. **权重稳定**：相邻窗口不会频繁打到 10% / 50% 边界；
5. **风险是真分散**：风险贡献 / PCA 支持，而不是只有资本权重看起来平均；
6. **执行规则稳健**：1/3/6/12 月或 3%/5%/10% 小变化不会完全反转结论；
7. **复权口径可解释**：forward 与 actual 的差异知道从哪里来。

对于黄金尤其应该问：

```text
它是在多数窗口里持续改善风险收益比，
还是只因为某一段黄金大牛市而被历史回测抬高权重？
```

---

# 数据源与缓存

正式行情源只有 Longbridge。

```bash
longbridge auth login
```

当前五只代码：

```text
513180.SH
515450.SH
513300.SH
159783.SZ
518850.SH
```

每只 ETF 分别拉取日线，最后取所有 ETF 都存在数据的**共同交易日交集**。

因此配置中的 `START_DATE=2020-01-01` 不代表组合一定从 2020-01-01 开始；实际起点取决于五只 ETF 的共同历史。

缓存位于仓库外，详见 [LONGBRIDGE.md](LONGBRIDGE.md)。

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

仓库包含 GitHub Actions 离线单元测试。

CI 主要验证：

- 现金与持仓约束；
- 再平衡逻辑；
- 976 组五资产权重网格；
- Walk-Forward 无未来数据泄漏；
- 风险贡献闭合；
- 低配优先定投行为；
- 阈值触发逻辑；
- 复权分析纯函数。

CI **不会**登录用户 Longbridge，也不会证明实时行情或本地授权可用。

---

# 当前项目阶段

当前代码功能已经足够支持这套五资产配置研究。

下一阶段的重点不是继续增加：

```text
更多优化器
更多评分项
更复杂的机器学习
更细的历史拟合
```

而是实际跑：

```text
权重搜索
→ 联合执行策略搜索
→ Walk-Forward
→ 风险分解
→ actual / forward 对账
```

然后把结论收敛成：

```text
合理的目标权重区间
+
实际可执行的定投方式
+
再平衡规则
```

而不是一个看似精确、实际脆弱的“历史最优比例”。
