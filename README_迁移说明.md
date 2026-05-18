# StockMonitor 重构说明（15 → 7）

## 📌 一句话

**所有源代码合并完成，并修复了两个 bug。直接用下面 7 个 `.py` 文件覆盖你目录里的旧文件即可。**

---

## 🐛 修复的 Bug

### Bug 1：数据源探测要 75 秒（你看到的 ~3 分钟）

**原因**：原版本 `probe_data_sources()` **串行**测试 4 个源，且每个源之间隔 `1.5s` 限流。东财探测时还把 `start_date` 写死成 `20200101`，导致每次开机就拉 1540 根历史 K 线，光这一步就 30 秒。

**修复**（`fetcher.py` v3.1-parallel-probe）：
- 4 个源改用 `ThreadPoolExecutor` **并行**探测（4 个不同服务器，不共享限流）
- 东财探测的 start_date 改为 `今天 - 400 天`，只拉 250 根左右
- 输出按 `_KLINE_SOURCES` 顺序排列（不是完成顺序），让你能直观看出优先级

**预期**：探测时间 ~75s → ~5s

### Bug 2："通达信优先级失效"（其实是日志误导）

**原因**：原版本 `fetch_kline()` 第 449 行有这样一段代码：

```python
if name not in ("通达信", "东财"):
    logger.info(f"[{symbol}] K 线来源 → {name}（{len(df)} 行）")
```

意思是：**通达信和东财成功时静默**，只有新浪/腾讯成功才打日志。结果你看到的"东财失败"实际来自 `fetch_stock_info()`（取 PE/PB/行业等基本面字段），**那个函数 mootdx 不支持，本来就只能东财→新浪→腾讯**。

**修复**：
- `fetch_kline()` 现在**始终**打印 `[600519] K 线来源 → 通达信（250 行）`，你能直接看到走的哪个源
- `fetch_stock_info()` 内部加注释，说明为什么必须用东财（mootdx 不提供 PE/PB 字段）

**优先级本身没坏**：`_KLINE_SOURCES` 列表第一个就是通达信，K 线确实是通达信优先。

---

## 📁 文件合并方案

| 旧文件（15 个） | → | 新文件（7 个） |
|---|---|---|
| `config.py` + `logger_setup.py` | → | **`config.py`** |
| `fetcher.py` | → | **`fetcher.py`** （修 bug） |
| `indicators.py` + `analysis.py` + `decision.py` | → | **`analysis.py`** |
| `ai_advisor.py` + `commodity_ai.py` | → | **`ai.py`** |
| `commodity_fetcher.py` + `sector_fetcher.py` + `capital_fetcher.py` + `calendar_fetcher.py` | → | **`extras.py`** |
| `scheduler.py` | → | **`scheduler.py`** （更新 imports） |
| `server.py` | → | **`server.py`** （只改了 imports 区） |

---

## 🛠 升级步骤

### 1. 备份旧目录（建议）

```bash
cd C:\Users\David\Downloads
xcopy /E /I StockMonitor StockMonitor_backup
```

### 2. 删除旧 .py 文件

进入 `StockMonitor\` 目录，**删掉以下 14 个文件**：

```
ai_advisor.py
analysis.py
calendar_fetcher.py
capital_fetcher.py
commodity_ai.py
commodity_fetcher.py
config.py
decision.py
fetcher.py
indicators.py
logger_setup.py
scheduler.py
sector_fetcher.py
server.py
```

> ⚠️ **保留**：`config.yaml` / `dashboard.html` / `watchlist.json` / `analysis_cache.json` / `alerts.json` / `cache/` / `logs/`

### 3. 把新的 7 个文件拷到目录

把本次提供的 7 个文件直接复制到 `StockMonitor\` 根目录：

```
config.py
fetcher.py
analysis.py
ai.py
extras.py
scheduler.py
server.py
```

### 4. 重启

```bash
python server.py
```

观察启动日志：

```
[探测] 测试 4 个数据源 (用 600519)...
  ✓ 通达信 可用 (250 条 / 1.2s)
  ✓ 东财   可用 (250 条 / 2.1s)     ← 现在只拉 250 根，不是 1540 根
  ✓ 新浪   可用 (250 条 / 1.5s)
  ✗ 腾讯   失败 (RuntimeError / 5.0s)，标记不可用
[探测] 可用源: 通达信 / 东财 / 新浪
```

整个探测应该在 **5 秒左右**完成。

之后每只股票分析时，会看到：

```
[000333] K 线来源 → 通达信（250 行）   ← 现在能看到走的是通达信！
```

---

## ⚙️ 配置文件

`config.yaml` **不需要改动**，所有字段沿用原样。

---

## ❓ 如果启动失败

1. **`ImportError: No module named 'extras'`** → 7 个文件没全部复制进去，检查目录
2. **`ImportError: No module named 'mootdx'`** → `pip install mootdx`
3. **AI 不响应** → 检查 `config.yaml` 里 `ai.api_key` 是否填了
4. **腾讯仍然失败** → 正常，腾讯接口本来就不稳定，4 选 3 用就够了

如有其他问题，把启动日志贴给我看。
