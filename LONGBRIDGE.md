# Longbridge 数据说明

本项目只支持 Longbridge 作为正式市场数据源。

## 登录

安装 Longbridge CLI 后完成授权：

```bash
longbridge auth login
```

## 主回测

```bash
python backtest.py
```

默认使用 Longbridge 实际历史价格（`actual`）。

强制刷新缓存：

```bash
python backtest.py --lb-refresh
```

前复权敏感性测试：

```bash
python backtest.py --lb-adjust forward
```

## 数据缓存

`longbridge_data.py` 会把标准化后的 OHLCV 缓存在仓库外：

- Windows: `%LOCALAPPDATA%/515450-backtest/longbridge/`
- Linux/macOS: `$XDG_CACHE_HOME/515450-backtest/longbridge/`，未设置时使用 `~/.cache/...`

也可通过环境变量覆盖：

```bash
BACKTEST_LONGBRIDGE_CACHE=/your/cache/path
```

历史数据按年份分段拉取，避免单次 K 线数量限制；缓存会按标的与复权方式分别保存。

## 标的映射

- `515450` -> `515450.SH`
- `513130` -> `513130.SH`

## 参数扫描

```bash
python longbridge_dual_sweep2.py
python longbridge_dual_sweep2_mp.py
```

扫描入口同样使用 Longbridge 数据，不依赖仓库中的历史 CSV。
