
# 📈 StockMonitor · 智能股票监控分析工具

> A股技术分析 + DeepSeek AI 辅助决策 | 支持 Web 仪表盘、命令行、GUI 三种模式

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)](https://flask.palletsprojects.com/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-API-orange)](https://platform.deepseek.com/)

**StockMonitor** 是一个专为 A 股投资者设计的开源工具，自动抓取股票日K线数据，计算 MACD、布林带、均线、RSI、量比等 20+ 技术指标，结合**规则引擎**与 **DeepSeek AI** 给出买卖建议。支持 Web 仪表盘、命令行定时调度及 Windows EXE 打包，适合复盘分析和投资辅助。

![Dashboard Preview](https://via.placeholder.com/800x450?text=StockMonitor+Dashboard+Preview)
> *示例截图：深色主题仪表盘，包含 MACD/布林带图表、支撑压力位、AI 分析卡片*

---

## ✨ 功能特色

- 📊 **数据抓取**：通过 akshare 获取东方财富日K线（前复权），含换手率、成交额
- 📐 **技术指标**：MACD（金叉/死叉/背离）、布林带（带宽/位置）、5/10/20/60 均线、RSI、量比、OBV
- 🧩 **支撑压力位**：三种方法融合（局部极值 + 成交量聚类 + 整数关口），自动排序去重
- 🤖 **AI 辅助决策**：构建精细化 Prompt（含最近 10 根 K 线完整数据），调用 DeepSeek API，返回结构化 JSON（建议入场、止损、短期目标、长期目标）
- 🧠 **规则引擎**：多维度评分（MACD、布林带、均线、RSI、量比、支撑压力），与 AI 结果交叉验证，输出最终决策（强烈买入/买入/持有/观望/卖出）
- 🌐 **Web 仪表盘**：Flask 后端 + 动态 HTML/CSS/JS 前端，深色主题，实时图表，支持添加/删除/刷新股票
- ⏱️ **自动调度**：命令行模式可配置轮询间隔、交易时段过滤，异常自动恢复
- 📦 **打包分发**：支持 PyInstaller 打包为单个 EXE 文件，无需 Python 环境即可运行

---

## 🚀 快速开始

### 1. 环境准备

需要 **Python 3.10 或 3.11**。


# 克隆项目
git clone https://github.com/ArcandEmily/StockMonitor.git
cd StockMonitor

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS/Linux

# 安装依赖
pip install -r requirements.txt


### 2. 配置 `.env` 文件

复制配置模板并填写必要信息：


copy .env.example .env        # Windows
cp .env.example .env          # macOS/Linux


最少需要修改以下三项：


DEEPSEEK_API_KEY=sk-你的DeepSeekKey
STOCK_CODES=000001,600519,300750
INTERVAL_MINUTES=60


*如果不使用 AI，可将 `ENABLE_AI=False`，仅用规则引擎。*

### 3. 启动 Web 仪表盘（推荐）


python server.py


启动后访问 `http://localhost:5000` 即可看到动态仪表盘。

### 4. 其他启动方式

- **命令行定时调度**：`python main.py`
- **GUI 桌面程序**：`python gui.py`（需要安装 `matplotlib`）

---

## 📖 使用说明

### Web 仪表盘界面

- **左侧边栏**：显示所有监控股票，点击切换详情；价格旁有小幅 K 线走势图
- **右上角**：显示最终决策和规则引擎信号，提供 **⟳ 刷新** 和 **✕ 删除** 按钮
- **图表区**：MACD 柱线 + DIF/DEA 折线；收盘价与布林带通道
- **技术指标网格**：12 项核心指标及当前状态（超买/超卖/金叉/死叉等）
- **支撑压力位面板**：可视化当前价与最近支撑/压力的距离百分比
- **AI 分析卡片**：展示 AI 给出的决策、置信度、关键理由、风险提示，以及建议入场/止损/目标价

### 添加/删除股票

- 在浏览器控制台执行 `addStock()` 输入代码即可添加（后续将增加界面按钮）
- 或直接修改 `.env` 中的 `STOCK_CODES` 并重启后端

### 自动刷新

- 后端每隔 `INTERVAL_MINUTES` 分钟自动拉取最新数据
- 前端每 60 秒刷新一次股票列表（仅更新价格和决策概要）

---

## 🔧 配置详解

`.env` 文件支持以下全部参数（均有合理默认值）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（启用 AI 时必填） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址（兼容 OpenAI） |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `ENABLE_AI` | `True` | 是否启用 AI 分析 |
| `AI_MAX_TOKENS` | `2000` | AI 返回的最大 token 数 |
| `AI_TEMPERATURE` | `0.2` | 输出随机性（越低越稳定） |
| `STOCK_CODES` | `000001,600519` | 监控股票代码（逗号分隔） |
| `KLINE_DAYS` | `250` | 历史 K 线数量 |
| `SR_WINDOW` | `10` | 局部极值窗口 |
| `SR_COUNT` | `3` | 保留几个支撑/压力位 |
| `INTERVAL_MINUTES` | `60` | 自动调度间隔（分钟） |
| `TRADING_HOURS` | 留空 | 交易时段限制（如 `09:30-11:30,13:00-15:00`） |
| `SUPPORT_TOLERANCE_PCT` | `2.0` | 价格靠近支撑位的百分比阈值 |
| `ENABLE_SOUND` | `False` | 强信号时发出声音（仅 Windows） |

---

## 🧩 API 端点（供前端或第三方调用）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stocks` | 返回所有股票基础信息（价格、决策、价格序列） |
| GET | `/api/stock/<code>` | 返回单只股票的完整指标、AI 分析和图表数据 |
| POST | `/api/stock/add` | 添加新股票，body `{"code":"600519"}` |
| POST | `/api/stock/remove` | 删除股票，body `{"code":"600519"}` |
| POST | `/api/stock/refresh` | 强制刷新指定股票数据 |
| GET | `/api/status` | 服务运行状态 |

所有接口均返回 JSON，并已配置 CORS。

---

## 📁 项目结构


StockMonitor/
├── server.py             # Flask Web 后端（主推）

├── dashboard.html        # 动态前端页面

├── main.py               # 命令行调度入口

├── gui.py                # Tkinter GUI 桌面版

├── config.py             # .env 配置读取

├── fetcher.py            # akshare 数据抓取

├── indicators.py         # 技术指标计算

├── analysis.py           # 支撑压力位识别（三种方法）

├── ai_advisor.py         # Prompt 构建 + DeepSeek API 调用

├── decision.py           # 规则引擎 + 综合决策

├── scheduler.py          # 定时调度逻辑

├── logger_setup.py       # 日志配置（loguru）

├── requirements.txt      # 依赖清单

├── .env.example          # 配置模板

├── build.bat             # 打包 EXE 脚本

└── logs/                 # 运行时自动生成日志目录


---

## 📦 打包为 EXE（Windows）


build.bat


完成后 `dist/StockMonitor_Server.exe` 即为单文件后端，将 `.env` 和 `dashboard.html` 放在同目录下即可运行。

若需更小体积，可使用干净虚拟环境并排除大型库（参考 `build_server.bat`）。

---

## ❓ 常见问题

**Q：必须使用 AI 吗？**  
A：不必须。设置 `ENABLE_AI=False`，则只使用规则引擎（MACD、布林带、均线等评分）给出信号。

**Q：数据是实时的吗？**  
A：不是。数据来自东方财富日K线，一般在收盘后更新，适合复盘分析，不适合盘中高频交易。

**Q：DeepSeek API 返回 JSON 不完整或解析失败怎么办？**  
A：已内置容错解析（自动补全花括号、提取首个 JSON 对象），同时可将 `.env` 中的 `AI_MAX_TOKENS` 增大到 2000~3000。

**Q：如何更换为 GPT-4o 或本地 Ollama？**  
A：修改 `.env` 中三行即可：

DEEPSEEK_API_KEY=sk-你的OpenAI密钥
DEEPSEEK_BASE_URL=https://api.openai.com/v1
DEEPSEEK_MODEL=gpt-4o

本地 Ollama 则将 `BASE_URL` 改为 `http://localhost:11434/v1`。

**Q：Web 仪表盘的图表不显示或数据为空？**  
A：首次启动需等待后台拉取数据（约 10~20 秒），刷新页面即可。检查后端日志是否有报错。

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request。改进方向：
- 增加更丰富的技术指标（如 KDJ、CCI）
- 支持更多数据源（如 tushare、baostock）
- 完善前端交互（添加股票按钮、删除确认）
- 对接 WallStreet.cn 大宗商品接口
- 提供 Docker 镜像部署

---

## 📄 许可证

[MIT License](LICENSE)

---

## ⚠️ 免责声明

本工具仅供学习和技术研究使用，不构成任何投资建议。所有数据均来自第三方公开接口，不代表真实交易数据。股市有风险，投资需谨慎，用户据此操作风险自负。

---

## 🌟 支持项目

如果觉得这个项目对你有帮助，请给一个 ⭐ Star 支持一下～
