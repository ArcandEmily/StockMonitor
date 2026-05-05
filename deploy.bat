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
    echo.
    echo  ⚠️  已生成 .env，请在打开的记事本中填入你的 DeepSeek API Key
    echo     获取地址: https://platform.deepseek.com/
    echo.
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
