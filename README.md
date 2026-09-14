# 多 ETF 定投与再平衡研究框架

这是一个基于 **Longbridge 日线行情**的个人长期资产配置研究项目。

项目的目标不是找出一个看起来精确的“历史最优比例”，而是回答更实际的几个问题：

- 这四只 ETF 长期应该如何分配权重？
- 25% / 25% / 25% / 25% 是否只是方便，还是确实合理？
- 每月新增资金应该机械按目标比例买，还是优先补低配资产？
- 再平衡应该固定每 1 / 3 / 6 / 12 个月做，还是等偏离达到阈值再做？
- 某个历史表现好的比例，在未来未知年份里还能不能成立？
- 名义上的四资产分散，是否实际上仍然集中在同一个成长风险因子？
- 未复权和前复权口径会不会改变结论？

因此，这个仓库已经从一个单纯的“ETF 回测脚本”，发展成一个围绕 **权重发现、执行规则、样本外验证、风险分解和数据口径对账** 的小型研究框架。

---

## 当前 ETF 池

```text
513180.SH
515450.SH
513300.SH
159783.SZ
```

`config.py` 当前默认写成：

```text
25% / 25% / 25% / 25%
```

但这只是一个 **benchmark / 默认启动参数**：

> **不是推荐比例，也不是搜索中心。**

真正的权重研究默认会完整探索：

```text
单只最低权重   10%
单只最高权重   50%
权重步长        5%
完整候选       375 组
```

如果 5% 网格已经表现出稳定区域，再考虑缩小范围做 2.5% 精扫；不建议一开始就追求 1% 甚至小数点级别的“最优权重”。

---

# 研究原则

这个项目目前最重要的不是继续增加功能，而是坚持下面几条研究纪律。

### 1. 不把历史第一名直接当答案

历史最优点很容易只是噪声。更值得关注的是：

- Top 区域是否集中在一片相似权重；
- 相邻参数变化后结果是否仍然稳定；
- 最差时间段是否仍然能接受；
- 样本外是否继续有效。

### 2. 权重和执行规则分开研究

一个权重在“每 3 个月机械再平衡”下表现好，不代表它在“低配优先定投 + 5% 阈值再平衡”下仍然最好。

因此 `policy_sweep.py` 会联合研究：

```text
目标权重
×
定投资金分配方式
×
再平衡规则
```

### 3. 样本外优先于样本内漂亮

`walk_forward.py` 严格执行：

```text
过去数据选参数
→
未来数据只负责验证
```

测试期不会反过来参与本轮参数选择。

### 4. 资本分散不等于风险分散

25% / 25% / 25% / 25% 只说明资金平均，不说明风险平均。

如果三只成长型 ETF 高度相关，它们完全可能合计贡献组合 70%~80% 的波动风险。

### 5. 长期收益默认使用前复权口径

研究默认：

```text
Longbridge forward
```

即前复权价格。

需要检查原始市场价格、整手、费用和复权敏感性时，再显式切到：

```bash
python backtest.py --adjust actual
```

---

# 项目结构

| 文件 | 作用 |
| --- | --- |
| `backtest.py` | 稳定基线：定投 + 固定周期全组合再平衡 |
| `adaptive_strategy.py` | 实验引擎：低配优先定投、周期/阈值再平衡 |
| `weight_sweep.py` | 375 组权重的稳健搜索 |
| `policy_sweep.py` | 权重 + 定投方式 + 再平衡规则联合搜索 |
| `walk_forward.py` | 严格时间顺序的样本外验证 |
| `risk_analysis.py` | 相关性、风险贡献、PCA、滚动风险集中度 |
| `adjustment_analysis.py` | actual vs forward 复权口径对账 |
| `longbridge_data.py` | Longbridge 日 K 获取、标准化和本地缓存 |
| `config.py` | 默认组合和基础参数 |
| `ADAPTIVE_POLICY.md` | 自适应定投 / 再平衡方法说明 |
| `ADJUSTMENT.md` | 复权研究说明 |
| `LONGBRIDGE.md` | Longbridge 数据层说明 |

---

# 快速开始

## 1. 安装 Python 依赖

```bash
pip install numpy pandas openpyxl
```

## 2. 安装并登录 Longbridge CLI

```bash
longbridge auth login
```

项目本身不会保存 Longbridge 凭据。

## 3. 跑一次基础回测

```bash
python backtest.py
```

## 4. 真正做组合研究

建议直接按这个顺序：

```bash
python adjustment_analysis.py
python weight_sweep.py
python policy_sweep.py
python walk_forward.py
python risk_analysis.py
```

这五步比继续增加新的优化器更重要。

---

# 默认参数

```text
ETF 池             513180 / 515450 / 513300 / 159783
默认 benchmark     25% / 25% / 25% / 25%
每月投入           5000 元
基线再平衡         每 3 个定投月
研究价格口径       forward 前复权
沪深 ETF 交易单位  100 份
佣金率             0.0087%
最低佣金           0.1 元
```

所有关键参数都可以通过 CLI 覆盖，不需要改代码。

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
5. 不允许使用外部杠杆；
6. 考虑整手、佣金、最低佣金和残余现金。

示例：

```bash
python backtest.py \
  --portfolio "513180.SH:0.30,515450.SH:0.30,513300.SH:0.20,159783.SZ:0.20" \
  --monthly 6000 \
  --rebalance-months 6
```

权重会自动归一化，因此 `30,30,20,20` 与 `0.30,0.30,0.20,0.20` 等价。

### 主要指标

- XIRR；
- 现金流调整后的年化 TWR；
- Sharpe；
- 最大回撤；
- 期末资产；
- 总手续费；
- 交易次数；
- 再平衡次数；
- 期末各 ETF 权重和份额。

### 输出

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
10% ~ 50% / ETF
5% 步长
375 组权重
3 个连续时间分段
```

它不会只按“历史收益最高”排名，而是同时考虑：

```text
全周期 XIRR          25%
最差分段 XIRR        25%
全周期 Sharpe        15%
最大回撤             15%
分段平均 XIRR        10%
分段稳定性            5%
权重分散度 / HHI      5%
```

最终还会计算 Top 区域的权重中心，并推荐一个最靠近稳定区域中心的 **真实网格候选**，而不是机械选择第一名。

### 更细搜索

```bash
python weight_sweep.py --step 0.025 --min-weight 0.10 --max-weight 0.50
```

建议只在 5% 搜索已经出现明显稳定区域之后再跑。

### 输出

```text
weight_sweep_results.csv
weight_sweep_top.csv
weight_sweep_recommendation.csv
```

---

# 3. 联合策略搜索：`policy_sweep.py`

```bash
python policy_sweep.py
```

这是目前最完整的研究入口。

它不只问：

> 四只 ETF 各配多少？

而是同时问：

> 每月钱怎么投进去？什么时候值得真正卖出并重新平衡？

## 两种月度定投方式

### `target`

每个月的新资金机械按目标权重拆分。

### `underweight`

每个月先看当前组合哪个 ETF 最低配，新增资金优先补低配资产。

普通定投月：

```text
只买，不卖
```

尽量让新增资金承担再平衡工作，减少不必要的卖出和换手。

## 再平衡规则

实验引擎支持：

```text
periodic    固定周期再平衡
threshold   偏离阈值触发
either      周期或阈值任一触发
none        完全不主动卖出式再平衡
```

默认联合搜索实际比较：

```text
定投方式：target / underweight
周期：1 / 3 / 6 / 12 个月
阈值：3% / 5% / 10%
以及：none
```

总计：

```text
16 种执行规则
```

## Stage 1：完整联合筛选

```text
375 组权重 × 16 种规则 = 6000 组完整历史回测
```

每一种规则都会在完整权重网格中独立寻找自己的优秀候选。

因此不存在：

```text
先假定 25% 等权
或
先假定每 3 个月再平衡
再围绕它优化
```

## Stage 2：分段稳健性验证

每一种执行规则默认保留自己的 Top 15 候选，再进行连续时间分段验证。

重点检查：

- 最差分段 XIRR；
- 平均分段 XIRR；
- 分段 XIRR 标准差；
- 最差分段回撤；
- 手续费；
- 再平衡次数；
- 平均权重偏离。

```bash
python policy_sweep.py --screen-top-per-policy 15
```

### 输出

```text
adaptive_joint_screen.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

最值得先看的不是第一名，而是：

```text
adaptive_top_region.csv
```

如果 Top 区域中某只 ETF 长期稳定在例如 20%~30%，这个区间比某一个精确的 25% 或 27.5% 更值得信任。

如果某只 ETF 在优秀候选中可以从 10% 跳到 50%，说明历史数据并不足以识别它的精确长期权重。

详见 [ADAPTIVE_POLICY.md](ADAPTIVE_POLICY.md)。

---

# 4. Walk-Forward：`walk_forward.py`

```bash
python walk_forward.py
```

默认流程：

```text
过去 3 年
→ 只使用这 3 年选择权重
→ 未来 12 个月完全不改参数进行测试
→ 窗口向前滚动
→ 重复
```

核心原则：

> **任何测试期数据都不能进入本轮训练和参数选择。**

重点看：

- 每个 OOS 窗口的 XIRR；
- OOS 平均 / 中位数 / 最差表现；
- 相对等权组合的胜率；
- 相对当前默认组合的超额；
- 每个窗口选出的权重是否稳定；
- 拼接后的 OOS TWR、Sharpe 和最大回撤。

如果相邻窗口的某只 ETF 权重反复从 10% 跳到 50%，即使平均收益不错，也说明不应该相信一个精确比例。

### 输出

```text
walk_forward_windows.csv
walk_forward_oos_nav.csv
walk_forward_summary.csv
```

注意：各 OOS 窗口是独立验证账户，拼接 NAV 用于风险诊断，不代表一条真实连续账户资金曲线。

---

# 5. 风险分解：`risk_analysis.py`

```bash
python risk_analysis.py
```

它用来回答：

> 名义上的四 ETF 组合，实际上有几个独立风险来源？

计算内容包括：

- 每只 ETF 年化波动率；
- 完整相关性矩阵；
- 组合年化波动率；
- component risk contribution；
- risk share；
- diversification ratio；
- PCA 第一主成分解释度；
- effective risk bets；
- rolling 1 年风险集中度；
- 分年度风险快照。

如果资本权重是：

```text
25 / 25 / 25 / 25
```

但风险贡献是：

```text
10 / 15 / 40 / 35
```

那它显然不是“四等分风险组合”。

### 输出

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

# 6. 复权口径对账：`adjustment_analysis.py`

```bash
python adjustment_analysis.py
```

项目默认使用 `forward` 做长期研究，但不会把复权当成黑盒。

这个脚本会同时比较 `actual` 与 `forward`：

- 每只 ETF 的累计收益；
- 年化收益；
- adjustment wedge；
- XIRR；
- TWR；
- Sharpe；
- 最大回撤；
- 期末资产；
- 手续费；
- 交易次数。

当前 Longbridge 的通用 dividend history 对这四只 A 股 ETF 没有提供可直接使用的完整逐笔分红记录，因此项目**不会伪造分红现金流**。

长期研究使用官方 `forward` K 线作为分红 / 拆分影响后的收益代理，并保留 `actual` 做敏感性和执行口径对照。

详见 [ADJUSTMENT.md](ADJUSTMENT.md)。

---

# 推荐研究流程

当前最建议的使用方式不是继续改代码，而是按下面顺序真正跑结果。

```text
Step 1  adjustment_analysis.py
        确认数据口径和复权差异是否可解释

Step 2  weight_sweep.py
        看完整权重空间有没有稳定优秀区域

Step 3  policy_sweep.py
        看权重与定投 / 再平衡规则的联动

Step 4  walk_forward.py
        验证历史选出来的参数在未知未来是否仍有效

Step 5  risk_analysis.py
        检查最后候选组合是否存在隐藏风险集中

Step 6  综合判断
        再决定是否修改长期目标比例和执行规则
```

一个真正值得采用的组合，最好同时满足：

- 不是历史收益单点尖峰；
- Top 区域权重相对集中；
- 小幅改变再平衡频率或阈值，结论不会完全反转；
- Walk-Forward 样本外仍然成立；
- Sharpe 和回撤不是靠单一牛市阶段堆出来的；
- 风险贡献没有隐藏的单因子集中；
- actual / forward 的差异可以解释；
- 手续费和换手没有吞掉理论优势。

---

# 如何解读结果

## 不推荐这样做

```text
看到历史第一名
→
直接把它写进 config.py
→
以后永久执行
```

也不推荐：

```text
35% / 27.5% / 22.5% / 15%
```

仅仅因为它比：

```text
35% / 25% / 25% / 15%
```

历史年化高 0.2%，就认为前者“更科学”。

## 更推荐这样理解

如果多种研究都指向：

```text
513180   20%~30%
515450   30%~40%
513300   15%~25%
159783   15%~25%
```

那么这些**稳定区间**比某一个单独网格点更有价值。

最终实际配置完全可以在这个稳定区间里选择一个更简单、容易执行、容易记忆的整数比例。

---

# 数据与缓存

项目生产数据源只有 Longbridge。

`longbridge_data.py` 会：

- 按年份分段拉取日 K；
- 标准化 OHLCV；
- 显式区分 `actual` / `forward`；
- 将缓存放在仓库之外；
- 只在缺失日期区间增量刷新。

默认缓存位置：

```text
Windows: %LOCALAPPDATA%/515450-backtest/longbridge
Linux/macOS: ${XDG_CACHE_HOME:-~/.cache}/515450-backtest/longbridge
```

也可以通过环境变量覆盖：

```text
BACKTEST_LONGBRIDGE_CACHE
```

强制刷新行情：

```bash
python backtest.py --refresh
python weight_sweep.py --refresh
python policy_sweep.py --refresh
python walk_forward.py --refresh
python risk_analysis.py --refresh
python adjustment_analysis.py --refresh
```

详见 [LONGBRIDGE.md](LONGBRIDGE.md)。

---

# 测试与 CI

离线单元测试：

```bash
python -m unittest -v
```

当前测试覆盖包括：

- 权重解析和归一化；
- 定投与周期再平衡；
- DCA-only；
- 375 组权重网格边界；
- 稳健评分；
- Walk-Forward 训练 / 测试不重叠；
- 风险贡献加总约等于 100%；
- 完全相关资产不会伪造分散收益；
- actual / forward 对齐与收益差异；
- underweight DCA 确实优先补低配；
- 普通低配定投月不会卖出；
- 残余现金不会触发伪权重偏离；
- 阈值再平衡只在真实偏离足够大时触发；
- 默认 16 种联合执行规则完整生成。

GitHub Actions 会自动运行离线测试，但 **CI 不访问 Longbridge 账户或真实行情授权**。

所以：

```text
CI 通过
≠
6000 组真实 Longbridge 回测已经运行
```

真实研究仍需要在已经完成 Longbridge CLI 登录的环境中执行。

---

# 当前项目状态

从代码结构上看，这个项目已经具备比较完整的长期 ETF 组合研究链路：

```text
数据口径
→
基线回测
→
权重搜索
→
执行规则搜索
→
样本外验证
→
风险分解
→
结果证伪
```

现阶段继续增加新的优化算法、遗传算法、贝叶斯搜索或更细的历史参数，价值已经不高，反而更容易制造“精确但脆弱”的答案。

**下一阶段的核心工作应该是：运行真实数据、分析输出、形成一个可解释的权重区间和执行规则，而不是继续扩展功能。**
