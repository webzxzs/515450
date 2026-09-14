# Longbridge 数据说明

本项目只使用 Longbridge 作为正式行情源。

## 登录

安装 Longbridge CLI 后完成授权：

```bash
longbridge auth login
```

## 行情缓存

`longbridge_data.py` 会把标准化后的日线 OHLCV 缓存在仓库外：

- Windows: `%LOCALAPPDATA%/515450-backtest/longbridge/`
- Linux/macOS: `$XDG_CACHE_HOME/515450-backtest/longbridge/`
- 未设置 `XDG_CACHE_HOME` 时使用 `~/.cache/515450-backtest/longbridge/`

也可以用环境变量覆盖：

```bash
BACKTEST_LONGBRIDGE_CACHE=/your/cache/path
```

历史数据按年份分段拉取，缓存按标的和复权方式分别保存。

## 价格口径

默认：

```bash
python backtest.py --adjust actual
```

也支持前复权敏感性测试：

```bash
python backtest.py --adjust forward
```

强制刷新缓存：

```bash
python backtest.py --refresh
```

## 标的代码

Longbridge 使用 `CODE.MARKET`：

```text
515450.SH
513130.SH
510300.SH
```

CLI 也接受常见沪深纯数字代码，项目会自动补市场后缀。

## 多 ETF 数据对齐

回测会分别拉取组合内每只 ETF 的日线，然后取**所有 ETF 都有交易数据的日期交集**。因此实际回测起点会自动落在组合中最晚上市 ETF 有数据之后。
