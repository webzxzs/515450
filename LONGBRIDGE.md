# Longbridge 数据说明

本项目只使用 Longbridge 作为正式行情源。

## 环境准备

Python 依赖：

```bash
python -m pip install -r requirements.txt
```

安装 Longbridge CLI 后完成授权：

```bash
longbridge auth login
```

Longbridge CLI 使用本机已有登录态；仓库不保存 Longbridge 凭据。

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

长期组合研究默认使用前复权：

```bash
python backtest.py --adjust forward
```

这也是 `config.PRICE_ADJUST` 当前默认值。

如需检查原始市场价格、整手和手续费敏感性：

```bash
python backtest.py --adjust actual
```

强制刷新缓存：

```bash
python backtest.py --refresh
```

## 默认标的代码

Longbridge 使用 `CODE.MARKET`，当前默认 ETF universe 为：

```text
513180.SH
515450.SH
513300.SH
159783.SZ
518850.SH
```

其中 `518850.SH` 为华夏黄金ETF。Longbridge 当前可正常返回该标的行情。

CLI 也接受常见沪深纯数字代码，项目会自动补 `.SH` / `.SZ`。

## 多 ETF 数据对齐

组合数据不会因为某一只 ETF 某天缺少收盘价，就把整个日期从研究样本中删除。当前规则与 `backtest.py` / 项目 Skill 保持一致：

```text
所有标的观察日期取并集（outer join）
↓
每只 ETF 至少出现过一个真实价格后，才进入共同研究区间
↓
某 ETF 当天缺行情：估值使用上一有效收盘价
↓
同时将该 ETF 当天标记为不可交易
↓
其他当天有真实行情的 ETF 仍可正常交易
```

因此：

- 组合估值日期保持连续，不会因为单一标的缺一天行情而整天消失；
- 前值只用于估值，不会被当成当天真实成交价；
- `tradable_<SYMBOL>` 标记控制该标的当天是否允许交易；
- synthetic test 若没有 `tradable_*` 列，则按全部可交易处理，以兼容离线测试。
