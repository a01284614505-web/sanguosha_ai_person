#!/bin/bash
# 安装脚本 - 改进版

echo "╔════════════════════════════════════════╗"
echo "║   AI三国杀酒馆 - 依赖安装脚本         ║"
echo "╚════════════════════════════════════════╝"
echo ""

# 检查Python
echo "1️⃣  检查Python..."
if ! command -v python &> /dev/null; then
    echo "   ⚠️  未安装Python"
    echo "   正在安装..."
    pkg install -y python
    echo "   ✅ Python安装完成"
else
    PYTHON_VER=$(python --version 2>&1)
    echo "   ✅ 已安装 $PYTHON_VER"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 升级pip
echo "2️⃣  升级pip..."
python -m pip install --upgrade pip --quiet
echo "   ✅ pip已更新到最新版"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 安装依赖
echo "3️⃣  安装依赖包..."
echo ""
echo "   需要安装: fastapi, uvicorn, websockets, pydantic, httpx"
echo "   预计时间: 2-5分钟（首次安装）"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 显示详细进度
pip install --progress-bar on fastapi uvicorn[standard] websockets pydantic httpx 2>&1 | while read line; do
    if [[ "$line" =~ "Collecting" ]]; then
        PKG=$(echo "$line" | sed 's/Collecting //')
        echo "  📦 准备: $PKG"
    elif [[ "$line" =~ "Downloading" ]]; then
        echo "  ⬇️  $line"
    elif [[ "$line" =~ "Installing" ]]; then
        echo "  ⚙️  $line"
    elif [[ "$line" =~ "Successfully installed" ]]; then
        echo "  ✅ $line"
    elif [[ "$line" =~ "Requirement already satisfied" ]]; then
        echo "  ✓ $(echo $line | cut -d: -f2)"
    elif [[ "$line" =~ "WARNING: Retrying" ]]; then
        echo "  ⏳ 网络不稳定，正在重试... (这是正常的)"
    elif [[ "$line" =~ "ERROR" ]] || [[ "$line" =~ "error" ]]; then
        echo "  ❌ 错误: $line"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 验证安装
echo "4️⃣  验证安装..."
echo ""

ALL_OK=1
for pkg in "fastapi" "uvicorn" "websockets" "pydantic" "httpx"; do
    if python -c "import $pkg" 2>/dev/null; then
        VERSION=$(python -c "import $pkg; print(getattr($pkg, '__version__', 'unknown'))" 2>/dev/null)
        echo "   ✅ $pkg ($VERSION)"
    else
        echo "   ❌ $pkg - 安装失败"
        ALL_OK=0
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $ALL_OK -eq 1 ]; then
    echo "✨ 安装成功！"
    echo ""
    echo "现在可以启动服务器:"
    echo "  bash start.sh"
    echo ""
    echo "或直接运行:"
    echo "  python test_server.py"
    echo ""
else
    echo "⚠️  部分依赖安装失败"
    echo ""
    echo "可能的原因:"
    echo "  1. 网络连接不稳定"
    echo "  2. pip源速度慢"
    echo ""
    echo "解决方案:"
    echo "  1. 检查网络连接，重新运行此脚本"
    echo "  2. 更换国内源:"
    echo "     pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/"
    echo "  3. 手动安装:"
    echo "     pip install fastapi uvicorn websockets pydantic httpx"
    echo ""
    exit 1
fi
