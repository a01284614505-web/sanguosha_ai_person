#!/data/data/com.termux/files/usr/bin/bash
# 将Termux工作区完整同步到Download备份区（单向：工作区 → 备份区）

set -u
SOURCE_DIR="/data/data/com.termux/files/home/sanguosha_tavern"
TARGET_DIR="/storage/emulated/0/Download/sanguosha/sanguosha_data"

mkdir -p "$TARGET_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║     AI三国杀酒馆 · 完整备份同步         ║"
echo "╚══════════════════════════════════════════╝"
echo "源目录: $SOURCE_DIR"
echo "目标目录: $TARGET_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sync_dir() {
    local name="$1"
    local src="$SOURCE_DIR/$name"
    local dst="$TARGET_DIR/$name"
    if [ ! -e "$src" ]; then
        echo "⚠️ 跳过不存在目录: $name"
        return
    fi
    rm -rf "$dst"
    mkdir -p "$dst"
    if [ "$name" = "frontend" ]; then
        # Android共享存储不支持符号链接，先排除工作区中的frontend/data链接。
        for item in "$src"/*; do
            [ -e "$item" ] || [ -L "$item" ] || continue
            [ "$(basename "$item")" = "data" ] && continue
            cp -a "$item" "$dst"/
        done
    else
        cp -a "$src"/. "$dst"/
    fi
    find "$dst" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
    find "$dst" -type f -name '*.pyc' -delete 2>/dev/null || true
    echo "✅ $name"
}

for directory in \
    game_engine frontend data worldbook worldbook_generated websocket \
    identity_cards scripts tests docs logs; do
    sync_dir "$directory"
done

# Android共享存储不支持符号链接，frontend/data保存为实体数据副本。
rm -rf "$TARGET_DIR/frontend/data"
cp -a "$TARGET_DIR/data" "$TARGET_DIR/frontend/data"

# 同步根目录运行入口、配置说明和工具脚本。
for pattern in "*.py" "*.sh" "*.md" "*.txt"; do
    for file in "$SOURCE_DIR"/$pattern; do
        [ -f "$file" ] || continue
        cp -p "$file" "$TARGET_DIR/"
    done
done

# 只备份 AI 开发辅助配置；快照和内部备份留在 Termux，避免公共目录无限增长。
if [ -f "$SOURCE_DIR/.aidev/config.json" ]; then
    mkdir -p "$TARGET_DIR/.aidev"
    cp -p "$SOURCE_DIR/.aidev/config.json" "$TARGET_DIR/.aidev/config.json"
    rm -rf "$TARGET_DIR/.aidev/snapshots" "$TARGET_DIR/.aidev/backups"
    echo "✅ .aidev/config.json"
fi

# 不把运行中的PID复制成可误用的活动PID。
rm -f "$TARGET_DIR/logs/game_server.pid"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ 同步完成！$(date '+%Y-%m-%d %H:%M:%S')"
echo "备份目录: $TARGET_DIR"
echo "世界书生成文件: $(find "$TARGET_DIR/worldbook_generated" -type f 2>/dev/null | wc -l)"
echo "测试文件: $(find "$TARGET_DIR/tests" -type f 2>/dev/null | wc -l)"
echo "日志文件: $(find "$TARGET_DIR/logs" -type f 2>/dev/null | wc -l)"
