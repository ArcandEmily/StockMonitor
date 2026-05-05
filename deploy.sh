#!/usr/bin/env bash
# StockMonitor · 一键部署脚本 (macOS / Linux)
# 用法：bash deploy.sh
#  或：bash <(curl -fsSL https://raw.githubusercontent.com/ArcandEmily/StockMonitor/main/deploy.sh)

set -e

REPO="https://github.com/ArcandEmily/StockMonitor.git"
DIR="StockMonitor"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

echo "============================================================"
echo "  StockMonitor · 一键部署脚本 (macOS/Linux)"
echo "============================================================"
echo ""

# ── 1. 检查 Python ───────────────────────────────────────────
echo -e "${GREEN}[1/5]${NC} 检查 Python 环境..."
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[错误]${NC} 未找到 python3，请先安装 Python 3.10 或 3.11"
    echo "  macOS:  brew install python"
    echo "  Ubuntu: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

PYVER=$(python3 -c "import sys; print(sys.version_info.minor)")
PYMAJ=$(python3 -c "import sys; print(sys.version_info.major)")
if [ "$PYMAJ" -lt 3 ] || [ "$PYVER" -lt 10 ]; then
    echo -e "${RED}[错误]${NC} Python 版本过低（当前 3.$PYVER），需要 3.10+"
    exit 1
fi
echo "  Python 3.$PYVER ✓"

# ── 2. 克隆或更新仓库 ────────────────────────────────────────
echo -e "${GREEN}[2/5]${NC} 获取代码..."
if [ -d ".git" ]; then
    # 已在仓库目录内
    echo "  检测到已有仓库，拉取最新代码..."
    git pull
elif [ -d "$DIR/.git" ]; then
    echo "  检测到已有目录，进入并更新..."
    cd "$DIR"
    git pull
else
    echo "  克隆仓库..."
    git clone "$REPO" "$DIR"
    cd "$DIR"
fi

# ── 3. 虚拟环境 ──────────────────────────────────────────────
echo -e "${GREEN}[3/5]${NC} 创建虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  虚拟环境已创建 ✓"
else
    echo "  虚拟环境已存在，跳过 ✓"
fi
source venv/bin/activate

# ── 4. 安装依赖 ──────────────────────────────────────────────
echo -e "${GREEN}[4/5]${NC} 安装依赖（首次约需 1-3 分钟）..."
pip install -r requirements.txt -q
echo "  依赖安装完成 ✓"

# ── 5. 配置 .env ─────────────────────────────────────────────
echo -e "${GREEN}[5/5]${NC} 配置环境变量..."
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
    echo -e "  ${YELLOW}⚠️  请编辑 .env 文件，填入你的 DeepSeek API Key${NC}"
    echo "     获取地址：https://platform.deepseek.com/"
    echo ""

    # 尝试用合适的编辑器打开
    if command -v nano &>/dev/null; then
        nano .env
    elif command -v vi &>/dev/null; then
        vi .env
    else
        echo "  请手动编辑：$(pwd)/.env"
    fi

    echo ""
    read -p "  填写完成后按 Enter 继续启动..." _
else
    echo "  .env 已存在，跳过 ✓"
fi

# ── 启动 ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo -e "  ${GREEN}✓ 启动 StockMonitor Web 服务${NC}"
echo "  访问地址：http://localhost:5000"
echo "  按 Ctrl+C 停止"
echo "============================================================"
echo ""
python server.py
