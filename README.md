# 515450 + 513130 杠铃策略回测

这是一个以 **515450 红利低波 ETF + 513130 恒生科技 ETF** 为核心的双标网格/定投回测项目。

## 数据源

项目现在只使用 **Longbridge** 拉取 ETF 历史日 K。

- 515450 -> `515450.SH`
- 513130 -> `513130.SH`
- 默认使用 Longbridge `actual` 历史价格
- 可使用 `--lb-adjust forward` 做前复权敏感性测试
- 数据缓存由 `longbridge_data.py` 管理，缓存在仓库外，不提交到 Git
- 不再维护 AkShare、HFQ CSV、指数拟合 CSV 等旧数据链路

首次使用前请确保 Longbridge CLI 已安装并完成登录：

```bash
longbridge auth login
```

## 运行

主入口：

```bash
python backtest.py
```

等价于：

```bash
python longbridge_dual_backtest.py
```

强制刷新 Longbridge 数据：

```bash
python backtest.py --lb-refresh
```

前复权测试：

```bash
python backtest.py --lb-adjust forward
```

原有策略参数仍可直接传入，例如：

```bash
python backtest.py --monthly-total 5000 --hldb-monthly 4500 --n-sims 10
```

## 参数扫描

顺序版：

```bash
python longbridge_dual_sweep2.py
```

多进程版：

```bash
python longbridge_dual_sweep2_mp.py
```

两者都在运行时从 Longbridge 获取数据，再复用原参数扫描引擎。

## 核心文件

```text
backtest.py                    # 主入口，Longbridge 双标回测
longbridge_data.py             # Longbridge K 线适配、缓存、代码映射
longbridge_dual_backtest.py    # Longbridge -> 双标回测引擎适配层
dual_backtest.py               # 双标策略/蒙特卡洛/组合核算核心引擎
longbridge_dual_sweep2.py      # Longbridge 参数扫描入口
longbridge_dual_sweep2_mp.py   # Longbridge 多进程参数扫描入口
dual_sweep2.py                 # 参数扫描核心逻辑
dual_sweep2_mp.py              # 多进程参数扫描核心逻辑
config.py                      # 费用和蒙特卡洛公共参数
```

## 策略默认值

### 515450

- 月度预算：4500 元
- G1 买入：-2%
- G1 卖出：+15%
- G2 买入：-3%
- G2 卖出：+50%
- 每档：1200 股

### 513130

- 月度预算：500 元
- G1/G2 买入：-8%
- G1 卖出：+20%
- G2 卖出：+50%
- 每档：100 股

月度总预算默认 5000 元。

## 依赖

```bash
pip install numpy pandas matplotlib openpyxl
```

另外需要可用的 Longbridge CLI。项目本身不保存 Longbridge 密钥或授权信息。

## 说明

`dual_backtest.py` 仍保留 CSV loader 形式的内部接口，是为了让策略引擎与数据源解耦；正常使用时不要直接运行它，统一通过 `backtest.py` / `longbridge_dual_backtest.py` 进入。当前正式数据源只有 Longbridge。
