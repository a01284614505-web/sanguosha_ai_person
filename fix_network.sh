#!/bin/bash
# 快速修复网络问题的脚本

echo "╔════════════════════════════════════════╗"
echo "║     网络问题修复工具                   ║"
echo "╚════════════════════════════════════════╝"
echo ""

echo "这个脚本会帮你切换到国内镜像源，加快下载速度"
echo ""

# 备份原配置
if [ -f ~/.config/pip/pip.conf ]; then
    echo "📋 备份现有pip配置..."
    cp ~/.config/pip/pip.conf ~/.config/pip/pip.conf.backup
    echo "   已备份到: ~/.config/pip/pip.conf.backup"
    echo ""
fi

# 配置国内源
echo "🔧 配置pip使用阿里云镜像源..."
mkdir -p ~/.config/pip
cat > ~/.config/pip/pip.conf << EOF
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host = mirrors.aliyun.com
timeout = 120
EOF

echo "   ✅ 已设置阿里云镜像源"
echo ""

# 显示配置
echo "📝 当前配置:"
cat ~/.config/pip/pip.conf
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "现在可以重新运行安装脚本:"
echo "  bash install.sh"
echo ""
echo "或者直接运行:"
echo "  bash start.sh"
echo ""
echo "💡 其他国内镜像源（如果阿里云仍然慢）:"
echo "  • 清华: https://pypi.tuna.tsinghua.edu.cn/simple"
echo "  • 中科大: https://pypi.mirrors.ustc.edu.cn/simple"
echo "  • 豆瓣: https://pypi.douban.com/simple"
echo ""
echo "修改方法: 编辑 ~/.config/pip/pip.conf"
echo ""
