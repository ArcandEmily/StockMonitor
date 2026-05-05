# 📈 StockMonitor · 智能股票 + 大宗商品监控

> A股技术分析 + 全球大宗商品行情 + DeepSeek AI 辅助决策 | 支持 Web 仪表盘、命令行、GUI 三种模式

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)](https://flask.palletsprojects.com/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-API-orange)](https://platform.deepseek.com/)

**StockMonitor** 是一个专为 A 股投资者设计的开源工具，自动抓取股票日K线数据，计算 MACD、布林带、均线、RSI、量比等 20+ 技术指标，结合**规则引擎**与 **DeepSeek AI** 给出买卖建议。同时内置**全球大宗商品实时行情模块**，对接华尔街见闻数据源，并由 AI 自动分析各商品对A股产业链的短期影响。

---

## ✨ 功能特色

### 📊 股票分析
- **数据抓取**：通过 akshare 获取东方财富日K线（前复权），含换手率、成交额
- **技术指标**：MACD（金叉/死叉）、布林带（带宽/位置）、5/10/20/60 均线、RSI、量比、OBV
- **支撑压力位**：三种方法融合（局部极值 + 成交量聚类 + 整数关口），自动排序去重
- **AI 辅助决策**：调用 DeepSeek API，返回结构化 JSON（建议入场、止损、短期/长期目标）
- **规则引擎**：多维度评分与 AI 结果交叉验证，输出最终决策（强烈买入 / 买入 / 持有 / 观望 / 卖出）

### 🛢️ 大宗商品（v2 新增）
- **实时行情**：对接**华尔街见闻**（主）、Yahoo Finance（备）、东方财富（备）三级数据源，覆盖原油、黄金、白银、铜、铝、大豆、玉米、小麦、螺纹钢、铁矿石等 11 个品种
- **底部滚动播报**：仪表盘底部常驻大宗商品价格滚动条，涨跌颜色实时标注
- **AI 产业影响分析**：DeepSeek 自动分析每个商品价格变动对 A 股相关行业的短期传导（利多 / 利空 / 中性），并给出代表性个股参考
- **多级降级**：华尔街见闻 → Yahoo → 东方财富 → 静态兜底，任意数据源故障自动切换，不影响运行

### 🌐 Web 仪表盘
- Flask 后端 + 纯 HTML/CSS/JS 前端，深色主题，无需 Node.js/npm
- 股票侧边栏 + 大宗商品标签页双视图
- 实时 MACD / 布林带图表（Chart.js）
- 支持添加 / 删除 / 强制刷新股票

---

## 🚀 一键部署

### Windows（双击运行）

将以下内容保存为项目根目录的 `deploy.bat`，双击即可完成克隆、配置、安装、启动全流程：

```bat
@echo off
chcp 65001 >nul
echo ============================================================
echo   StockMonitor · 一键部署脚本 (Windows)
echo ============================================================

REM ── 1. 检查 Python ──────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或 3.11
    echo 下载地址: https://www.python.org/downloads/
    pause & exit /b 1
)

REM ── 2. 克隆或更新仓库 ────────────────────────────────────────
if exist ".git" (
    echo [1/5] 检测到已有仓库，拉取最新代码...
    git pull
) else (
    echo [1/5] 克隆仓库...
    git clone https://github.com/ArcandEmily/StockMonitor.git .
)

REM ── 3. 创建虚拟环境 ──────────────────────────────────────────
echo [2/5] 创建虚拟环境...
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat

REM ── 4. 安装依赖 ──────────────────────────────────────────────
echo [3/5] 安装依赖（首次约需 1-3 分钟）...
pip install -r requirements.txt -q

REM ── 5. 生成 .env 配置 ────────────────────────────────────────
echo [4/5] 配置环境变量...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
    ) else (
        (
            echo DEEPSEEK_API_KEY=sk-替换为你的DeepSeekKey
            echo DEEPSEEK_BASE_URL=https://api.deepseek.com
            echo DEEPSEEK_MODEL=deepseek-chat
            echo ENABLE_AI=True
            echo AI_MAX_TOKENS=2000
            echo AI_TEMPERATURE=0.2
            echo STOCK_CODES=000001,600519,300750
            echo KLINE_DAYS=250
            echo INTERVAL_MINUTES=60
        ) > .env
    )
    echo [提示] 已生成 .env，请用文本编辑器打开并填写你的 DeepSeek API Key
    echo        文件路径: %CD%\.env
    notepad .env
    echo 填写完成后按任意键继续启动...
    pause >nul
)

REM ── 6. 启动 ──────────────────────────────────────────────────
echo [5/5] 启动 Web 服务...
echo.
echo  ✓ 启动成功后访问: http://localhost:5000
echo  ✓ 按 Ctrl+C 停止服务
echo ============================================================
python server.py
pause
```

### macOS / Linux（一行命令）

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/ArcandEmily/StockMonitor/main/deploy.sh)
```

或手动运行：

```bash
# 克隆项目
git clone https://github.com/ArcandEmily/StockMonitor.git
cd StockMonitor

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置（首次运行）
cp .env.example .env
nano .env   # 填入 DEEPSEEK_API_KEY 和 STOCK_CODES

# 启动
python server.py
```

将以下内容保存为 `deploy.sh` 放入仓库，配合上面的一行命令使用：

```bash
#!/usr/bin/env bash
set -e
REPO="https://github.com/ArcandEmily/StockMonitor.git"
DIR="StockMonitor"

echo "============================================================"
echo "  StockMonitor · 一键部署脚本 (macOS/Linux)"
echo "============================================================"

# 1. 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi
PYVER=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYVER" -lt 10 ]; then
    echo "[错误] Python 版本过低，需要 3.10 或 3.11"
    exit 1
fi

# 2. 克隆或更新
if [ -d "$DIR/.git" ]; then
    echo "[1/5] 检测到已有仓库，更新代码..."
    cd "$DIR" && git pull
else
    echo "[1/5] 克隆仓库..."
    git clone "$REPO" "$DIR" && cd "$DIR"
fi

# 3. 虚拟环境
echo "[2/5] 创建虚拟环境..."
[ ! -d "venv" ] && python3 -m venv venv
source venv/bin/activate

# 4. 安装依赖
echo "[3/5] 安装依赖..."
pip install -r requirements.txt -q

# 5. 配置
echo "[4/5] 配置环境变量..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        cat > .env <<'EOF'
DEEPSEEK_API_KEY=sk-替换为你的DeepSeekKey
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
ENABLE_AI=True
AI_MAX_TOKENS=2000
AI_TEMPERATURE=0.2
STOCK_CODES=000001,600519,300750
KLINE_DAYS=250
INTERVAL_MINUTES=60
EOF
    fi
    echo ""
    echo "  ⚠️  请编辑 .env 文件，填入你的 DeepSeek API Key："
    echo "     vi .env   或   nano .env"
    echo ""
    read -p "  填写完成后按 Enter 继续..." _
fi

# 6. 启动
echo "[5/5] 启动 Web 服务..."
echo ""
echo "  ✓ 访问地址: http://localhost:5000"
echo "  ✓ 按 Ctrl+C 停止"
echo "============================================================"
python server.py
```

---

## ⚙️ 配置说明（`.env`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek API Key（[获取地址](https://platform.deepseek.com/)，启用 AI 必填） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址，兼容 OpenAI 格式，可换 GPT-4o / Ollama |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `ENABLE_AI` | `True` | 是否启用 AI 分析，`False` 时仅用规则引擎 |
| `AI_MAX_TOKENS` | `2000` | AI 最大返回 token 数 |
| `AI_TEMPERATURE` | `0.2` | 输出随机性，越低越稳定 |
| `STOCK_CODES` | `000001,600519` | 监控股票代码，逗号分隔 |
| `KLINE_DAYS` | `250` | 历史 K 线天数 |
| `SR_WINDOW` | `10` | 局部极值窗口大小 |
| `SR_COUNT` | `3` | 保留支撑/压力位数量 |
| `INTERVAL_MINUTES` | `60` | 自动调度间隔（分钟） |
| `TRADING_HOURS` | 留空 | 交易时段过滤，如 `09:30-11:30,13:00-15:00` |
| `SUPPORT_TOLERANCE_PCT` | `2.0` | 价格靠近支撑位的触发阈值（%） |
| `ENABLE_SOUND` | `False` | 强信号声音提醒（仅 Windows） |

---

## 📡 API 端点

### 股票

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stocks` | 所有股票概要（价格、决策、迷你K线） |
| GET | `/api/stock/<code>` | 单股完整数据（指标、图表、AI分析） |
| POST | `/api/stock/add` | 添加股票 `{"code":"600519"}` |
| POST | `/api/stock/remove` | 删除股票 `{"code":"600519"}` |
| POST | `/api/stock/refresh` | 强制刷新指定股票 |

### 大宗商品

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/commodities` | 全部商品实时行情（含数据来源标记） |
| GET | `/api/commodity/analysis` | DeepSeek AI 产业影响分析（JSON） |
| POST | `/api/commodity/refresh` | 强制刷新商品数据 + 重新触发 AI 分析 |
| GET | `/api/status` | 服务状态、运行模式、数据就绪情况 |

所有接口均返回 JSON，已配置 CORS，可直接供第三方调用。

---

## 📁 项目结构

```
StockMonitor/
├── server.py               # Flask Web 后端（主入口）
├── dashboard.html          # 前端仪表盘（单文件，无需构建）
│
├── fetcher.py              # A股 K线数据抓取（akshare）
├── indicators.py           # 技术指标计算（MACD/BB/RSI等）
├── analysis.py             # 支撑压力位识别
├── ai_advisor.py           # 股票 AI 分析（DeepSeek）
├── decision.py             # 规则引擎 + 综合决策
│
├── commodity_fetcher.py    # 大宗商品行情抓取（华尔街见闻/Yahoo/东方财富）
├── commodity_ai.py         # 大宗商品 AI 产业影响分析（DeepSeek）
│
├── config.py               # .env 配置读取
├── scheduler.py            # 定时调度
├── logger_setup.py         # 日志（loguru）
│
├── requirements.txt        # 依赖清单
├── .env                    # 本地配置（不提交 git）
├── .env.example            # 配置模板
├── deploy.bat              # Windows 一键部署
├── deploy.sh               # macOS/Linux 一键部署
└── logs/                   # 运行日志（自动生成）
```

---

## 🗂️ 大宗商品数据源说明

| 数据源 | 覆盖品种 | 优先级 | 备注 |
|--------|----------|--------|------|
| 华尔街见闻 | 国际+国内全品种 | ⭐ 首选 | 批量拉取，2分钟本地缓存 |
| Yahoo Finance | 国际期货（原油/金/银/铜等） | 备用一 | 单品种查询 |
| 东方财富 | 国内主力合约（螺纹钢/铁矿石等） | 备用二 | 上期所/大商所/郑商所 |
| 静态兜底 | 全品种 | 兜底 | 三路均失败时返回固定值，不报错 |

---

## ❓ 常见问题

**Q：必须使用 DeepSeek AI 吗？**
A：不必须。设置 `ENABLE_AI=False`，仅用规则引擎；大宗商品模块会自动切换为规则兜底分析。

**Q：数据是实时的吗？**
A：股票数据来自东方财富日K线，收盘后更新，适合复盘，不适合高频交易。大宗商品行情每 5 分钟刷新一次。

**Q：如何更换为 GPT-4o 或本地 Ollama？**
A：修改 `.env` 三行：
```
DEEPSEEK_API_KEY=sk-你的OpenAI密钥
DEEPSEEK_BASE_URL=https://api.openai.com/v1
DEEPSEEK_MODEL=gpt-4o
```
本地 Ollama 将 `BASE_URL` 改为 `http://localhost:11434/v1`，`API_KEY` 填任意字符串。

**Q：首次启动大宗商品 AI 分析要等多久？**
A：约 15~30 秒，后端在启动时异步触发抓取+分析，前端会自动轮询直到结果就绪。

**Q：华尔街见闻接口访问失败怎么办？**
A：程序会自动降级到 Yahoo Finance，无需任何操作，仪表盘来源标签会显示实际数据来源。

**Q：AI 返回 JSON 解析失败？**
A：已内置容错解析，同时可将 `.env` 中 `AI_MAX_TOKENS` 增大至 2000~3000。

---

## 📦 打包为 EXE（Windows）

```bat
build.bat
```

完成后 `dist/StockMonitor_Server.exe` 即为单文件后端，将 `.env`、`dashboard.html`、`commodity_fetcher.py`、`commodity_ai.py` 放在同目录下即可运行。

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request，改进方向：

- 增加更多技术指标（KDJ、CCI、BOLL背离）
- 支持更多数据源（tushare、baostock）
- 大宗商品品种扩充（动力煤、棉花、橡胶等）
- 提供 Docker 镜像一键部署
- 完善前端交互动画与移动端适配

---

## 📄 许可证

[MIT License](LICENSE)

---

## ⚠️ 免责声明

本工具仅供学习和技术研究使用，**不构成任何投资建议**。所有数据均来自第三方公开接口，不代表真实交易数据。股市有风险，投资需谨慎，用户据此操作风险自负。

---

## 🌟 支持项目

如果觉得这个项目对你有帮助，请给一个 ⭐ Star 支持一下～
