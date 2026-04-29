# 515450 + 513130 杠铃策略回测系统

基于 **双档止盈网格 + 月度定投** 对 A 股红利低波 ETF（515450）与恒生科技 ETF（513130）做组合回测。通过布朗桥蒙特卡洛模拟日内价格路径，评估策略在 2020–2026 年的收益与风险。

---

## 当前策略结果（9:1 先验比例，无未来函数）

| 指标 | 数值 |
|------|------|
| 回测区间 | 2020-08-17 ~ 2026-04-27（5.7 年） |
| 月度预算 | ¥5,000（515450: ¥4,500 / 513130: ¥500） |
| XIRR | **+9.06%** |
| 年化收益 | +4.60% |
| 夏普率 | **0.3308** |
| 最大回撤 | −19.11% |
| 账户总值 | **¥437,991** |
| 总投入 | ¥339,125 |
| 未实现盈亏 | **+¥98,867（+29.15%）** |

> **为什么用 9:1 而非优化出来的 4800:200？**  
> 参数扫描中 4800:200 的 Sharpe=0.3511，但比例本身来自历史数据拟合（未来函数）。9:1 是基于资产属性的先验判断（红利低波防守：恒科进攻 ≈ 9:1），Sharpe=0.3308，差距仅 0.02，不具显著性。

---

## 项目结构

```
515450/
├── dual_backtest.py         # 主引擎：515450 + 513130 双网格杠铃组合回测
├── backtest.py              # 单标的回测（515450 独立，含 MC 和完整图表）
├── config.py                # 单标的回测参数（backtest.py 使用）
├── dual_sweep2.py           # Round 2 参数扫描（顺序，贪心三阶段）
├── dual_sweep2_mp.py        # Round 2 参数扫描（多进程加速版）
├── param_sweep_515450.py    # 515450 单标的参数扫描
├── _fetch_index.py          # 数据获取：恒生科技指数 + ETF 拼接
├── iwencai_etf_selector.py  # 问财 ETF 选股工具（backtest.py 依赖）
│
├── index_data_hfq.csv       # 515450 后复权日线（2020-02-26 起）
├── hst_hfq.csv              # 513130 后复权日线（2021-06-01 起）
├── index_data.csv           # A500 指数日线（用于 515450 扩展）
├── index_hstech.csv         # 恒生科技指数日线（用于 513130 历史延伸）
├── etf_513130.csv           # 513130 原始 ETF 数据（_fetch_index.py 输入）
├── combined_hst.csv         # 513130 + 指数拼接数据（_fetch_index.py 输出）
│
├── dual_backtest.png        # 最新回测图表（组合收益率、月度资金、资产占比）
├── dual_backtest.xlsx       # 最新回测 Excel（MC 汇总、日明细、月明细）
├── dual_sweep2_best.txt     # Round 2 参数扫描 Top-20（含推荐方案标注）
├── dual_sweep2_full.csv     # Round 2 全量扫描结果（924 组合）
│
├── trades.csv               # 515450 回测交易记录
├── daily.csv                # 515450 回测日度数据
├── monthly.csv              # 515450 回测月度数据
├── mc_summary.csv           # 515450 MC 统计汇总
│
├── README.md                # 本文件
└── 策略说明.md               # 策略详细文档（含单标、双标、算法说明）
```

---

## 快速开始

### 运行双标杠铃回测（推荐）

```bash
# 默认参数（9:1 比例，Round 2 最优网格，MC 10次）
python dual_backtest.py

# 自定义预算
python dual_backtest.py --monthly-total 5000 --hldb-monthly 4000

# 完整参数
python dual_backtest.py \
  --hldb-monthly 4500 \
  --hst-buy-pct 0.08 \
  --hst-g1-sell-pct 0.20 \
  --hst-g2-sell-pct 0.50 \
  --hst-shares 100 \
  --n-sims 10
```

输出：`dual_backtest.png`（图表）+ `dual_backtest.xlsx`（Excel）

### 运行单标 515450 回测

```bash
python backtest.py
```

### 参数扫描（双标 Round 2）

```bash
# 顺序版（约 30 分钟）
python dual_sweep2.py

# 多进程版（自动检测 CPU 核数，约 3 分钟 on 16 core）
python dual_sweep2_mp.py
```

输出：`dual_sweep2_best.txt`（Top-20 + 推荐方案）+ `dual_sweep2_full.csv`

---

## 策略参数（当前默认值）

### 515450（HLDB）网格

| 参数 | 值 | 含义 |
|------|----|------|
| G1 买入阈值 | 2% | 跌 2% 触发买入 |
| G1 卖出阈值 | 15% | 涨 15% 止盈（中频） |
| G2 买入阈值 | 3% | 跌 3% 触发买入 |
| G2 卖出阈值 | 50% | 涨 50% 大幅止盈 |
| 每档股数 | 1200 股 | — |

### 513130（HST）网格

| 参数 | 值 | 含义 |
|------|----|------|
| G1/G2 买入阈值 | 8% | 恒科波动大，买入阈值更深 |
| G1 卖出阈值 | 20% | 中频止盈 |
| G2 卖出阈值 | 50% | 大幅止盈 |
| 每档股数 | 100 股 | — |

---

## 核心技术

### 布朗桥日内价格模拟

日线 OHLC 数据只有 4 个价格点，通过布朗桥合成约 181 个 tick 的仿真日内路径，使网格能在日内触发。每段 60 步，3 段连接，clip 到 [low, high] 范围。

### 513130 指数拟合历史延伸

513130 于 2021-06 上市，通过对最近 120 个重叠交易日的 log 价格做 OLS 回归，将恒生科技指数历史映射到 ETF 价格空间：

$$\ln P_{ETF} = a + b \cdot \ln P_{index}, \quad b \approx 1.186,\ a \approx -10.55$$

将有效回测起点延伸至 **2020-08-17**（+193 个交易日）。

### 参数扫描方法

Round 2 采用**贪心三阶段**搜索：

| 阶段 | 固定 | 扫描 | 组合数 |
|------|------|------|--------|
| A | HST 默认值 | HLDB 买入对 × HLDB 股数 | 90 |
| B | HLDB 最优值 | HST 买入对 × 卖出 × 股数 | 924 |
| C | HLDB+HST 最优 | 预算比例（200 元步长） | 15 |

---

## 依赖

```
akshare
numpy
pandas
matplotlib
openpyxl
scipy (可选, XIRR 回退实现)
```

```bash
pip install akshare numpy pandas matplotlib openpyxl
```

|------|---------|------|
| 515450 红利低波 ETF | **4000 元** | 防守端：低波动、高股息 |
| 513130 恒生科技 ETF | **1000 元** | 进攻端：高弹性、高波动 |
| **合计** | **5000 元** | — |

---

## 默认参数

### 515450（HLDB）

| 参数 | 值 |
|------|----|
| 月投 | 4000 元 |
| G1 买入 | −1% |
| G1 卖出 | +20% |
| G1 股数 | 900 股 |
| G2 买入 | −1% |
| G2 卖出 | +40% |
| G2 股数 | 900 股 |

### 513130（HST 恒科）

| 参数 | 值 |
|------|----|
| 月投 | 1000 元 |
| G1 买入 | −3% |
| G1 卖出 | +20% |
| G1 股数 | 200 股 |
| G2 买入 | −3% |
| G2 卖出 | +40% |
| G2 股数 | 200 股 |

佣金：万 0.87（单边），最低 0.1 元。7 日内卖出收赎回费（实际运作中须注意，回测暂不扣除）。

---

## 快速开始

### 环境依赖

```bash
pip install pandas numpy matplotlib scipy akshare openpyxl
```

### 运行双标的回测（默认参数）

```bash
python dual_backtest.py
```

### 自定义预算分配

```bash
# 总预算 5000，515450 占 3800，恒科占 1200
python dual_backtest.py --monthly-total 5000 --hldb-monthly 3800

# 指定恒科网格参数
python dual_backtest.py --monthly-total 5000 --hldb-monthly 4000 \
    --hst-buy-pct 0.03 --hst-sell1-pct 0.20 --hst-sell2-pct 0.40 --hst-shares 200
```

### CLI 参数一览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--monthly-total` | 5000 | 月度总预算（元） |
| `--hldb-monthly` | 4000 | 515450 月度额度 |
| `--hst-monthly` | 自动 | 513130 月度额度（默认 = total − hldb） |
| `--hst-buy-pct` | 0.03 | 恒科网格买入阈值（如 0.03 = −3%） |
| `--hst-sell1-pct` | 0.20 | 恒科 G1 卖出阈值 |
| `--hst-sell2-pct` | 0.40 | 恒科 G2 卖出阈值 |
| `--hst-shares` | 200 | 恒科每次网格交易股数 |
| `--n-sims` | 10 | 蒙特卡洛模拟次数 |

### 运行单标的回测（515450）

```bash
python backtest.py
```

### 参数扫描

```bash
python param_sweep.py      # 515450 单标的全参数搜索
python dual_sweep.py       # 双标的预算分配扫描
```

---

## 回测结果

### 双标的组合（2020-08-17 ~ 2026-04）

回测区间：**5.7 年**（延伸后）

| 指标 | 组合 | 515450 单独 | 513130 单独 |
|------|------|------------|------------|
| 年化收益 | +3.85% | +4.80% | −0.66% |
| XIRR | +7.73% | — | — |
| 夏普率 | 0.246 | — | — |
| 最大回撤 | −23.46% | — | — |

> 注：513130 回测区间包含恒科熊市阶段（2021-2022），单独年化为负，但杠铃组合有效降低整体回撤。

### 515450 单标的（2020-02-26 ~ 2026-03，6 年）

| 指标 | 双网格策略 | 纯定投 |
|------|---------|--------|
| 年化收益 | +8.52% | +8.01% |
| 夏普率 | 0.47 | 0.45 |
| 最大回撤 | −27.10% | −27.73% |

---

## 输出文件

运行 `backtest.py` 后生成：

| 文件 | 内容 |
|------|------|
| `backtest_results.png` | 价格+交易点、总资产曲线、回撤、持仓 |
| `monthly_analysis.png` | 月度净加仓 + 月末市值 vs 累计投入 |
| `return_dist.png` | 日收益率分布 |
| `backtest_report.xlsx` | 策略对比、参数、MC 统计、月度明细 |
| `trades.csv` / `daily.csv` / `monthly.csv` | 明细数据 |

---

## 数据来源

- ETF 后复权日线：`akshare.fund_etf_hist_em(adjust="hfq")`
- 恒生科技指数：`akshare.index_investing_global_etf_hist()` 或本地 `index_hstech.csv`
- A500 指数：本地 `index_data.csv`

本地 CSV 缓存避免重复请求；如需刷新，删除对应 CSV 后重新运行即可。
