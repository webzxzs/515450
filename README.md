# 多 ETF 定投与再平衡研究框架

这是一个基于 **Longbridge 日线行情**的个人长期资产配置研究项目。

项目定位很明确：**只做研究，不做自动下单，不做实盘执行系统。** 对这种低频定投与再平衡，研究的价值在于资产选择、长期权重、再平衡规则和风险结构，而不是交易自动化。

## 当前 ETF universe

| 代码 | 资产 / 作用 | 基金管理人 |
| --- | --- | --- |
| `513180.SH` | 恒生科技 | 华夏基金 |
| `515450.SH` | A股红利低波 | 南方基金 |
| `513300.SH` | 纳斯达克100 | 华夏基金 |
| `159783.SZ` | 科创创业50 | 华夏基金 |
| `518850.SH` | 黄金 | 华夏基金 |

基金选择规则：**同类暴露下，如果跟踪质量、费率、规模、流动性、历史长度和 Longbridge 数据质量没有明显劣势，优先选择华夏基金产品。** 这个偏好只影响“用哪只 ETF 代表某类资产”，不决定该资产应该配多少权重。

## 默认组合只是 benchmark

`config.py` 当前快速运行基准为五等权：

```text
513180.SH  20%
515450.SH  20%
513300.SH  20%
159783.SZ  20%
518850.SH  20%
```

它不是推荐比例，也不是搜索中心。

## 最终权重研究边界

项目支持 **每只 ETF 独立上下限**。

当前默认：

```text
513180.SH   10% ~ 50%
515450.SH   10% ~ 50%
513300.SH   10% ~ 50%
159783.SZ   10% ~ 50%
518850.SH    0% ~ 30%
权重步长          5%
```

黄金特意允许到 **0%**。这样研究可以得出“当前五资产框架其实不需要黄金”的结论，而不是因为统一的 10% 下限被迫持有黄金。

在当前边界下，5% 网格共有：

```text
1,554 组权重
```

`policy_sweep.py` 默认比较 16 种定投 / 再平衡执行规则，因此 Stage 1 当前为：

```text
1,554 × 16 = 24,864 组完整历史回测
```

这些数字由配置决定；如果以后修改边界，应以程序运行时输出为准，不要把固定数字当成模型假设。

---

# 研究原则

## 1. 不把历史第一名直接当答案

真正关注：

- Top 区域是否集中；
- 最差时间段是否还能接受；
- Walk-Forward 样本外是否成立；
- 相邻参数变化会不会彻底改变结论；
- 黄金权重是否长期落在相似区间，还是频繁从 0% 跳到上限。

## 2. 权重和执行规则一起研究

项目同时研究：

```text
目标权重
×
月度资金分配方式
×
再平衡规则
```

一个权重在 3 个月固定再平衡下表现好，不代表在“低配优先定投 + 阈值再平衡”下仍然最好。

## 3. 样本外优先

`walk_forward.py` 严格执行：

```text
过去 3 年训练 / 选择权重
未来 12 个月完全样本外验证
然后向前滚动
```

测试期不能参与本轮参数选择。

## 4. 资本分散不等于风险分散

五等权不等于五等风险。`risk_analysis.py` 会分析：

- 波动率；
- 相关性；
- component risk contribution；
- risk share；
- diversification ratio；
- PCA 第一主成分；
- effective risk bets；
- 滚动和分年度风险集中度。

黄金加入的核心价值，就是检验它是否真的提供一个不同于股票成长因子的风险来源。

## 5. 长期收益默认用前复权

默认：

```text
Longbridge forward
```

需要看原始价格、整手和费用敏感性时：

```bash
python backtest.py --adjust actual
```

`adjustment_analysis.py` 用于 actual 与 forward 对账。

---

# 数据对齐规则

早期版本要求所有 ETF 当天都有价格，使用日期 `inner join`。这会导致某一只 ETF 某天停牌、缺数据或数据源遗漏时，整天从组合历史中消失。

现在改为：

```text
所有标的日期取并集
↓
每只 ETF 先有至少一个真实价格后才进入共同研究区间
↓
某天该 ETF 无价格：估值使用上一有效收盘价
↓
同时标记该 ETF 当天不可交易
↓
其他有行情的 ETF 当天仍可正常参与策略
```

因此：

- **估值连续**；
- 不会因为一只 ETF 缺一天行情而删除整天；
- 不会在停牌 / 缺行情日用前值假装成交；
- synthetic test 没有 `tradable_*` 列时仍按全部可交易处理，兼容原有测试和研究函数。

---

# 项目结构

| 文件 | 作用 |
| --- | --- |
| `backtest.py` | 稳定基线：定投 + 固定周期再平衡 |
| `adaptive_strategy.py` | 低配优先定投、周期 / 阈值再平衡 |
| `weight_sweep.py` | 权重网格 + 稳健多指标排名 |
| `policy_sweep.py` | 权重 + 定投方式 + 再平衡规则联合搜索 |
| `walk_forward.py` | 严格时间顺序样本外验证 |
| `risk_analysis.py` | 相关性、风险贡献、PCA、滚动风险 |
| `adjustment_analysis.py` | actual vs forward 对账 |
| `longbridge_data.py` | Longbridge 日 K 与缓存 |
| `config.py` | ETF universe、研究边界和基础参数 |

---

# 推荐研究顺序

```bash
python adjustment_analysis.py
python weight_sweep.py
python policy_sweep.py
python walk_forward.py
python risk_analysis.py
```

其中最重要的是：

1. `weight_sweep.py` 看权重稳定区域；
2. `policy_sweep.py` 看权重和执行规则是否互相依赖；
3. `walk_forward.py` 看样本外是否还能成立；
4. `risk_analysis.py` 看资本权重背后的真实风险集中度；
5. `adjustment_analysis.py` 检查复权口径是否改变结论。

## `weight_sweep.py`

默认评分：

```text
全周期 XIRR          25%
最差分段 XIRR        25%
全周期 Sharpe        15%
最大回撤             15%
分段平均 XIRR        10%
分段稳定性            5%
权重分散度 / HHI      5%
```

不要只看第一名。更重要的是 Top 区域范围。

## `policy_sweep.py`

默认 16 种规则：

```text
target / underweight 定投
周期再平衡：1 / 3 / 6 / 12 月
阈值再平衡：3% / 5% / 10%
none：不主动卖出式再平衡
```

阶段 1：全权重网格 × 全执行规则。

阶段 2：每种规则保留自己的 Top 候选，再做连续时间分段稳健性验证。

重点输出：

```text
adaptive_joint_screen.csv
adaptive_policy_results.csv
adaptive_policy_top.csv
adaptive_policy_summary.csv
adaptive_top_region.csv
```

## `walk_forward.py`

重点看：

- OOS XIRR；
- 最差窗口；
- 相对等权的胜率；
- 权重稳定性；
- 黄金是否长期稳定为正权重。

如果某资产在相邻窗口不断从 0% / 10% 跳到上限，不应相信精确比例。

---

# Longbridge

项目正式市场数据只使用 Longbridge。

首次使用：

```bash
longbridge auth login
```

强制刷新缓存：

```bash
python backtest.py --refresh
python weight_sweep.py --refresh
python policy_sweep.py --refresh
python walk_forward.py --refresh
python risk_analysis.py --refresh
python adjustment_analysis.py --refresh
```

缓存保存在仓库外，项目不保存 Longbridge 凭据。

---

# 测试

```bash
python -m unittest -v
```

GitHub Actions 只跑离线测试，不访问 Longbridge 账户。

测试覆盖包括：

- 贡献金额与现金约束；
- 周期 / 阈值再平衡；
- underweight 普通月不卖出；
- 0% 权重 sleeve；
- 每标的独立权重边界；
- 缺行情日估值前填与禁止交易；
- Walk-Forward 无数据泄漏；
- 风险贡献和 PCA；
- actual / forward 对账逻辑。

---

# 当前开发状态

**研究功能到这里收口。**

项目已经具备：

- 多 ETF 定投回测；
- 独立资产权重约束；
- 完整权重网格探索；
- 定投 / 再平衡联合搜索；
- Walk-Forward 样本外验证；
- 风险贡献 / PCA；
- 复权敏感性；
- 更稳健的缺失交易日处理；
- 离线 CI。

接下来不应继续堆优化器或交易自动化。真正有价值的工作是：**跑真实 Longbridge 历史数据、解释结果、判断稳定区间，然后形成长期资产配置结论。**
