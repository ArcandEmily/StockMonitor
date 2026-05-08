#!/usr/bin/env bash
# StockMonitor · 一键部署脚本 (macOS / Linux)
set -e

REPO="https://github.com/ArcandEmily/StockMonitor.git"
DIR="StockMonitor"
GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"

echo "============================================================"
echo "  StockMonitor · 一键部署脚本 (macOS/Linux)"
echo "============================================================"

echo -e "${GREEN}[1/5]${NC} 检查 Python..."
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[错误]${NC} 未找到 python3"
    echo "  macOS:  brew install python"
    echo "  Ubuntu: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
echo "  $(python3 --version) ✓"

echo -e "${GREEN}[2/5]${NC} 获取代码..."
if [ -d ".git" ]; then
    git pull
elif [ -d "$DIR/.git" ]; then
    cd "$DIR" && git pull
else
    git clone "$REPO" "$DIR" && cd "$DIR"
fi

echo -e "${GREEN}[3/5]${NC} 创建虚拟环境..."
[ ! -d "venv" ] && python3 -m venv venv
source venv/bin/activate

echo -e "${GREEN}[4/5]${NC} 安装依赖..."
pip install -r requirements.txt -q

echo -e "${GREEN}[5/5]${NC} 配置文件..."
if [ ! -f "config.yaml" ]; then
    [ -f "config.yaml.example" ] && cp config.yaml.example config.yaml
    echo ""
    echo -e "  ${YELLOW}⚠️  请编辑 config.yaml，填入你的 DeepSeek API Key：${NC}"
    echo "     获取地址：https://platform.deepseek.com/"
    echo ""
    if command -v nano &>/dev/null; then nano config.yaml
    elif command -v vi &>/dev/null; then vi config.yaml; fi
    read -p "  填写完成后按 Enter 继续..." _
else
    echo "  config.yaml 已存在 ✓"
fi

echo ""
echo "============================================================"
echo -e "  ${GREEN}✓ 启动 StockMonitor${NC}"
echo "  访问地址：http://localhost:5000"
echo "  按 Ctrl+C 停止"
echo "============================================================"
python server.py
