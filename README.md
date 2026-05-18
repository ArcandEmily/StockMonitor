# 📈 StockMonitor

> A股技术分析 + 全球大宗商品 + DeepSeek AI 辅助决策
>
> Web 仪表盘 · 蜡烛图 · 板块联动 · 北向资金 · 财报日历 · 价格预警

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![DeepSeek](https://img.shields.io/badge/AI-DeepSeek-orange)](https://platform.deepseek.com/)

---

## 功能一览

### 📊 A 股分析

- **K 线蜡烛图**：ECharts 渲染，带成交量柱、内置缩放拖拽，20 / 40 / 60 日切换
- **技术指标**：MACD · 布林带 · RSI · KDJ · VWAP · OBV · 均线（MA5/10/20/60）· 量比 · 换手率
- **支撑压力位**：局部极值 + 量聚类 + 整数关口三法融合，AI 结合价位给出操作建议
- **板块联动**：自动识别个股所属行业，展示同板块 Top6 涨跌情况
- **北向资金**：近 10 日净流入趋势（沪深港通,东方财富数据）
- **融资融券**：个股融资余额与融券余额
- **财报日历**：一季报 / 半年报 / 年报 / 分红除权预告，精确到距今天数，颜色标注紧迫程度

### 🛢️ 全球大宗商品 & 外汇

- **39 个品种实时行情**，覆盖能源、贵金属、工业金属、农产品、外汇，对接**华尔街见闻**公开 API
- **Sparkline 迷你趋势图**：每张品种卡片底部显示近 2 小时价格走势
- **分类筛选 Tab**：能源 / 贵金属 / 工业金属 / 农产品 / 外汇 / 黑色系一键过滤
- **底部滚动播报**：全时间段显示最新价格与涨跌幅
- **AI 产业影响分析**：DeepSeek 自动分析每个商品价格变动对 A 股相关行业的传导（利多 / 利空 / 中性），给出代表性个股参考

### 🤖 AI 能力

- **股票综合决策**：规则引擎与 AI 交叉验证，输出强烈买入 / 买入 / 持有 / 观望 / 卖出，附入场价 / 止损价 / 目标价
- **大宗商品产业分析**：结合当前价格变动，分析对 A 股化工 / 钢铁 / 航空 / 农业等板块的短期影响
- **每日市场总结**（按钮触发）：AI 综合所有股票 + 商品 + 外汇数据，生成 200 字简报
- **思考模式**：支持 DeepSeek 思维链推理（`config.yaml` 开关，默认关闭，开启后更准确但费用更高）
- **多模型支持**：兼容 OpenAI API 格式，可切换 GPT-4o / 本地 Ollama

### 🔔 实用工具

- **价格预警**：设置"某股/商品高于/低于某价格"触发规则，浏览器系统通知 + Toast 弹出
- **Excel 导出**：一键下载包含股票与大宗商品两张表的 `.xlsx` 文件
- **亮色 / 暗色主题**：快捷键 `T` 或工具栏按钮切换，偏好持久化
- **键盘快捷键**：`/` 搜索、`1~9` 切换股票、`C` 大宗商品页、`R` 刷新、`E` 导出、`?` 帮助
- **连接状态指示**：顶部彩色圆点，绿色 = 正常 / 黄色 = 延迟 / 红色 = 断开，15 秒心跳检测

### ⚙️ 工程特性

- **自选股持久化**：`watchlist.json` 自动保存，重启后恢复
- **AI 分析缓存**：`analysis_cache.json` 保存上次结果，启动即显示，后台异步刷新
- **并发抓取**：`ThreadPoolExecutor(max_workers=5)` 并行拉取多只股票，比串行快 3–5 倍
- **数据源并行探测**：启动时 4 个 K 线源 (通达信 / 东财 / 新浪 / 腾讯) 并行测试，~5 秒完成
- **YAML 配置**：`config.yaml` 替代 `.env`，层级清晰，有注释，支持实时修改重启生效
- **四级数据降级**：通达信 (mootdx) → 东财 (akshare) → 新浪 → 腾讯，任意源故障自动跳过 10 分钟
- **WebSocket 验证**：`ws_test.py` 独立可运行，验证推送可行性（主程序仍用轮询，稳定优先）

---

## 快速开始

### Windows（双击一键部署）

```bat
git clone https://github.com/ArcandEmily/StockMonitor.git
cd StockMonitor
deploy.bat
```

脚本自动完成：建虚拟环境 → 安装依赖 → 打开 `config.yaml` 填写 API Key → 启动服务

### macOS / Linux

```bash
git clone https://github.com/ArcandEmily/StockMonitor.git
cd StockMonitor
bash deploy.sh
```

或远程一行命令：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ArcandEmily/StockMonitor/main/deploy.sh)
```

### 手动安装

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

启动后访问 **http://localhost:5000**

---

## 配置说明（`config.yaml`）

```yaml
ai:
  api_key: "sk-你的密钥"        # DeepSeek API Key（必填）
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  enabled: true
  max_tokens: 2000
  temperature: 0.2
  timeout: 60
  thinking:
    enabled: false             # 思考模式（更准但更贵，默认关闭）
    effort: "high"             # high 或 max

stocks:
  codes:
    - "000001"
    - "600519"
    - "300750"
  kline_days: 250
  interval_minutes: 60         # 自动刷新间隔（分钟）

alerts:
  enable_sound: false
```

**切换到 GPT-4o：**

```yaml
ai:
  api_key: "sk-你的OpenAI密钥"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
```

**切换到本地 Ollama：**

```yaml
ai:
  api_key: "ollama"
  base_url: "http://localhost:11434/v1"
  model: "qwen2.5:7b"
```

---

## API 端点

### 股票

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stocks` | 所有股票概要（价格、决策、迷你K线） |
| GET | `/api/stock/<code>` | 单股完整数据（指标 + 蜡烛图 + KDJ + AI分析） |
| POST | `/api/stock/add` | 添加股票 `{"code":"600519"}` |
| POST | `/api/stock/remove` | 删除股票 `{"code":"600519"}` |
| POST | `/api/stock/refresh` | 强制刷新指定股票 |
| GET | `/api/stock/<code>/sector` | 板块信息 + 同板块成分股涨跌 |
| GET | `/api/stock/<code>/margin` | 融资融券余额 |

### 市场与资金

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market/northbound` | 北向资金近10日净流入趋势 |
| GET | `/api/calendar` | 监控股票的近期财报 / 分红日历 |
| POST | `/api/market/summary` | AI每日市场总结（触发生成） |
| GET | `/api/export` | 导出 Excel（股票 + 大宗商品） |

### 大宗商品

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/commodities` | 全部商品实时行情（含 Sparkline 历史） |
| GET | `/api/commodity/analysis` | DeepSeek AI 产业影响分析 |
| POST | `/api/commodity/refresh` | 强制刷新 + 重新触发AI分析 |

### 价格预警

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/alerts` | 获取所有预警规则 |
| POST | `/api/alerts` | 添加预警 `{"code","name","direction","threshold","type"}` |
| DELETE | `/api/alerts/<id>` | 删除预警 |
| GET | `/api/alerts/triggered` | 获取已触发预警（并清空队列） |
| POST | `/api/alerts/reset/<id>` | 重置预警（允许再次触发） |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 服务状态、运行模式、数据就绪情况 |

所有接口均返回 JSON，已配置 CORS，可直接供第三方调用。

---

## 大宗商品数据源

| 数据源 | 域名 | 覆盖品种 | 优先级 |
|--------|------|----------|--------|
| 华尔街见闻 | `api-ddc-wscn.awtmt.com` | 国际商品 + 外汇（30个） | ⭐ 首选 |
| akshare | 新浪财经 | 国内期货（螺纹钢 / 铁矿石 / 上海原油等） | 备用一 |
| 东方财富 | `push2.eastmoney.com` | 国内主力合约 | 备用二 |
| 静态兜底 | 内置 | 全部品种 | 最终保底 |

---

## A 股 K 线数据源

| 数据源 | 协议 | 字段 | 优先级 |
|--------|------|------|--------|
| 通达信 (mootdx) | TCP socket | OHLCV | ⭐ 首选（反爬绝缘） |
| 东方财富 (akshare) | HTTP | OHLCV + PE/PB/行业 | 备用一 |
| 新浪财经 | HTTP | OHLCV | 备用二 |
| 腾讯财经 | HTTP | OHLCV | 备用三 |

> 注：股票**基本面字段**（PE、PB、行业、流通股本）通达信协议不提供，必须走东财通道，所以日志里看到 "东财" 不一定是 K 线失败，可能是 `fetch_stock_info()` 调用。

---

## 键盘快捷键

| 按键 | 功能 |
|------|------|
| `/` | 聚焦搜索框 |
| `1` – `9` | 切换到第 N 只股票 |
| `C` | 跳转大宗商品页 |
| `T` | 切换亮色 / 暗色主题 |
| `R` | 刷新当前股票 |
| `E` | 导出 Excel |
| `?` | 显示快捷键帮助 |
| `Esc` | 关闭所有弹窗 |

---

## 项目结构

> v3.1 起项目从 15 个 `.py` 合并为 **7 个** 核心模块，逻辑分层更清晰。

```
StockMonitor/
│
├── server.py               # Flask 后端（主入口、路由）
├── dashboard.html          # 前端仪表盘（单文件，无需构建）
│
├── config.py               # YAML 配置读取 + loguru 日志初始化
├── config.yaml             # 配置文件（填入 API Key 后使用）
│
├── fetcher.py              # A 股 K 线 + 基本面
│                           #   • 通达信 (mootdx) → 东财 → 新浪 → 腾讯 四级降级
│                           #   • 启动并行探测可用源（~5s）
│                           #   • 失败源自动屏蔽 10 分钟
│
├── analysis.py             # 技术分析 + 决策
│                           #   • 指标：MACD / 布林 / RSI / KDJ / VWAP / OBV / 均线
│                           #   • 支撑压力位（局部极值 + 量聚类 + 整数关口）
│                           #   • 规则引擎 + 最终决策合成
│
├── ai.py                   # DeepSeek AI 调用
│                           #   • AIAdvisor          → 股票综合决策
│                           #   • CommodityAIAdvisor → 大宗商品产业传导
│                           #   • build_prompt       → 提示词组装
│
├── extras.py               # 辅助数据源
│                           #   • 大宗商品行情 (华尔街见闻 / akshare)
│                           #   • 板块联动 (sector_fetcher)
│                           #   • 北向资金 + 融资融券 (capital_fetcher)
│                           #   • 财报 / 分红日历 (calendar_fetcher)
│
├── scheduler.py            # 定时调度（每 N 分钟刷新一轮）
│
├── ws_test.py              # WebSocket 推送可行性验证（独立脚本，可选）
│
├── requirements.txt        # 依赖清单
├── deploy.bat              # Windows 一键部署
├── deploy.sh               # macOS / Linux 一键部署
└── LICENSE
```

**v3.1 合并对照表**：

| 旧文件（v3.0 及之前） | → | 新文件（v3.1） |
|---|---|---|
| `config.py` + `logger_setup.py` | → | `config.py` |
| `fetcher.py` | → | `fetcher.py` ⭐ |
| `indicators.py` + `analysis.py` + `decision.py` | → | `analysis.py` |
| `ai_advisor.py` + `commodity_ai.py` | → | `ai.py` |
| `commodity_fetcher.py` + `sector_fetcher.py` + `capital_fetcher.py` + `calendar_fetcher.py` | → | `extras.py` |
| `scheduler.py` | → | `scheduler.py` |
| `server.py` | → | `server.py` |

---

## 打包为 EXE（Windows）

```bat
rmdir /s /q venv_clean
C:\Python314\python.exe -m venv venv_clean
venv_clean\Scripts\activate
pip install -r requirements.txt pyinstaller

pyinstaller --onefile --console --clean ^
    --collect-data akshare ^
    --collect-data mootdx ^
    --add-data "dashboard.html;." ^
    --add-data "config.yaml;." ^
    --hidden-import akshare ^
    --hidden-import mootdx ^
    --hidden-import loguru ^
    --hidden-import flask ^
    --hidden-import requests ^
    --hidden-import openai ^
    --hidden-import yaml ^
    server.py
```

打包后只需两个文件即可运行：

```
server.exe      ← 双击运行
config.yaml     ← 修改后重启生效，无需重新打包
```

> v3.1 起 `commodity_fetcher.py` / `commodity_ai.py` 已合并到 `extras.py` / `ai.py`，不再需要 `--add-data` 单独打入；PyInstaller 通过 `import` 自动收集。

详细说明见 `Package_by_yourself.md`。

---

## WebSocket 验证（实验性）

主程序目前使用轮询（稳定优先）。`ws_test.py` 是独立的 WebSocket 可行性验证脚本：

```bash
pip install flask-socketio eventlet
python ws_test.py
# 访问 http://localhost:5001/ws_test
```

页面每 2 秒自动收到服务端推送的模拟价格更新，全程无轮询。待主程序各功能稳定后迁移。

---

## 常见问题

**Q：必须使用 DeepSeek AI 吗？**
A：不必须。`config.yaml` 中设置 `enabled: false`，仅用规则引擎；大宗商品分析自动切换为规则兜底。

**Q：华尔街见闻接口失败怎么办？**
A：程序自动降级到 akshare，再失败降级到静态数据，仪表盘来源标签会显示实际数据来源。

**Q：板块联动 / 北向资金 / 财报日历显示"暂不可用"？**
A：akshare 部分接口需要 A 股交易时段（9:30–15:00）才能返回数据，非交易时间会降级显示空白。

**Q：启动时数据源探测要多久？**
A：v3.1 起改为并行探测，正常 ~5 秒完成。如果某个源长时间超时（>10s），会被标记不可用并跳过 10 分钟，下次自动重试。

**Q：日志里看到 "东财失败" 是 K 线获取失败了吗？**
A：不一定。基本面字段（PE / PB / 行业 / 流通股本）mootdx 协议不提供，必须走东财；这条失败日志可能来自 `fetch_stock_info()` 而不是 K 线。K 线实际使用的源在 `[600519] K 线来源 → 通达信（250 行）` 这条日志里。

**Q：思考模式有多贵？**
A：DeepSeek `effort=high` 约比普通模式贵 2–3 倍，`effort=max` 贵 5 倍以上。建议日常关闭，需要高精度分析时临时开启。

**Q：自选股重启后会丢失吗？**
A：不会。添加/删除股票时自动写入 `watchlist.json`，重启后自动恢复。

**Q：首次启动大宗商品 AI 分析要等多久？**
A：约 15–30 秒。有缓存时（`analysis_cache.json`）启动即显示上次结果，后台异步刷新。

**Q：exe 打包后需要带哪些文件？**
A：只需 `server.exe` + `config.yaml` 两个文件，其余全部内置在 exe 中。

---

## 更新日志

### v3.1（2026-05）

- 🔧 **重构**：15 个 `.py` 合并为 7 个核心模块，目录结构大幅简化
- ⚡ **修复**：数据源探测从 75s → ~5s（4 个源并行探测，东财不再拉 1540 根历史 K 线）
- 📋 **修复**：`fetch_kline()` 始终打印实际使用的源（之前通达信成功时静默，导致看不出优先级）
- 🐛 **修复**：K 线 tooltip 字段错位（ECharts 蜡烛图 `params.value` 会自动前置 `dataIndex`，需跳过首元素）
- 📊 **改进**：默认 K 线源从 akshare 改为 mootdx（TCP 直连，反爬绝缘）

### v3.0 及之前

- 初版功能完整，详见 git history

---

## 免责声明

本工具仅供学习与技术研究使用，**不构成任何投资建议**。所有数据均来自第三方公开接口，不保证实时性与准确性。股市有风险，投资需谨慎，据此操作风险自负。

---

## License

[MIT](LICENSE) © 2026 ArcandEmily

---

⭐ 如果这个项目对你有帮助，欢迎 Star 支持！
