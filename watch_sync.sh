#!/bin/bash
# 实时双向同步脚本 - 监控文件变化并自动同步

PROJECT_DIR=~/sanguosha_tavern
DOWNLOAD_DIR=/storage/emulated/0/Download/sanguosha/sanguosha_data

echo "╔══════════════════════════════════════════╗"
echo "║     实时同步监控                         ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "监控目录："
echo "  项目: $PROJECT_DIR"
echo "  下载: $DOWNLOAD_DIR"
echo ""
echo "按 Ctrl+C 停止监控"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 初始同步
echo "🔄 执行初始同步..."
bash ~/sanguosha_tavern/sync_to_download.sh > /dev/null 2>&1
echo "✅ 初始同步完成"
echo ""

# 监控函数
watch_and_sync() {
    LAST_SYNC=0
    
    while true; do
        CURRENT_TIME=$(date +%s)
        
        # 每5秒检查一次
        if [ $((CURRENT_TIME - LAST_SYNC)) -ge 5 ]; then
            # 检查项目文件是否有变化
            if [ -n "$(find $PROJECT_DIR -name '*.md' -o -name '*.txt' -o -name '*.sh' -o -name '*.py' -newer /tmp/last_sync 2>/dev/null)" ]; then
                echo "[$(date '+%H:%M:%S')] 📝 检测到项目文件变化，同步到Download..."
                bash ~/sanguosha_tavern/sync_to_download.sh > /dev/null 2>&1
                touch /tmp/last_sync
                LAST_SYNC=$CURRENT_TIME
            fi
            
            # 检查Download目录是否有新的武将数据
            if [ -d "$DOWNLOAD_DIR/wujiang" ]; then
                if [ -n "$(find $DOWNLOAD_DIR/wujiang -name '*.json' -o -name '*.png' -newer /tmp/last_hero_sync 2>/dev/null)" ]; then
                    echo "[$(date '+%H:%M:%S')] 🎭 检测到新武将数据，同步到项目..."
                    # 复制武将数据
                    if [ -d "$DOWNLOAD_DIR/wujiang" ]; then
                        mkdir -p $PROJECT_DIR/data/heroes
                        cp -r $DOWNLOAD_DIR/wujiang/* $PROJECT_DIR/data/heroes/ 2>/dev/null
                    fi
                    touch /tmp/last_hero_sync
                fi
            fi
        fi
        
        sleep 5
    done
}

# 创建时间戳文件
touch /tmp/last_sync
touch /tmp/last_hero_sync

# 开始监控
watch_and_sync
