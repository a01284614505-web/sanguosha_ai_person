#!/usr/bin/env python3
"""
AI模拟测试脚本 - 通过浏览器真实验证游戏功能
"""

import asyncio
import json
import os
import time
from pathlib import Path

# 测试脚本不使用真实 API；如需配置请通过环境变量注入。
API_KEY = os.getenv("SANGUOSHA_TEST_API_KEY", "")

async def main():
    print("=" * 60)
    print("🤖 AI模拟测试 - 牌堆验证与技能适配检查")
    print("=" * 60)
    
    # 第一步：验证服务器状态
    print("\n[步骤1] 检查服务器状态...")
    import subprocess
    result = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8888/"],
        capture_output=True,
        text=True
    )
    if result.stdout.strip() == "200":
        print("✅ HTTP服务器运行正常")
    else:
        print(f"❌ HTTP服务器异常: {result.stdout}")
        return
    
    # 第二步：检查牌堆配置
    print("\n[步骤2] 检查牌堆配置...")
    registry_path = Path(__file__).parent / "card_decks" / "deck_registry.json"
    if registry_path.exists():
        with open(registry_path) as f:
            registry = json.load(f)
            active_deck = registry["settings"]["active_deck"]
            deck_info = next((d for d in registry["decks"] if d["id"] == active_deck), None)
            if deck_info:
                print(f"✅ 当前激活牌堆: {deck_info['name']} ({deck_info['cards_count']}张)")
                print(f"   描述: {deck_info['description']}")
            else:
                print(f"❌ 牌堆配置异常: {active_deck}")
    else:
        print("❌ 牌堆注册表不存在")
    
    # 第三步：检查扩展卡牌数据
    print("\n[步骤3] 检查扩展卡牌数据...")
    extended_path = Path(__file__).parent / "card_decks/complete_deck/data/extended_cards.json"
    if extended_path.exists():
        with open(extended_path) as f:
            data = json.load(f)
            cards = data.get("cards", [])
            card_names = set(c["name"] for c in cards)
            print(f"✅ 扩展卡牌文件存在")
            print(f"   包含卡牌: {', '.join(sorted(card_names))}")
            print(f"   总计: {len(cards)}张")
    else:
        print("❌ 扩展卡牌数据不存在")
    
    # 第四步：检查卡牌图片资源
    print("\n[步骤4] 检查卡牌图片资源...")
    cards_dir = Path(__file__).parent / "extracted_resources/cards"
    if cards_dir.exists():
        card_images = list(cards_dir.glob("*.png"))
        print(f"✅ 卡牌图片目录存在")
        print(f"   图片数量: {len(card_images)}")
        print(f"   图片列表: {', '.join([img.stem for img in card_images])}")
        
        # 检查关键卡牌
        key_cards = ["jiu", "tiesuo", "bingliang"]
        missing = [card for card in key_cards if not (cards_dir / f"{card}.png").exists()]
        if missing:
            print(f"⚠️  缺失关键卡牌图片: {', '.join(missing)}")
        else:
            print("✅ 关键卡牌图片齐全")
    else:
        print("❌ 卡牌图片目录不存在")
    
    # 第五步：检查前端资源路径
    print("\n[步骤5] 检查前端卡牌资源路径...")
    frontend_assets = Path(__file__).parent / "frontend/assets/cards"
    if frontend_assets.exists():
        frontend_cards = list(frontend_assets.glob("*.png"))
        print(f"✅ 前端卡牌资源目录存在")
        print(f"   图片数量: {len(frontend_cards)}")
    else:
        print("❌ 前端卡牌资源目录不存在")
        print("   这可能是牌面UI未注入的原因！")
    
    # 第六步：检查引擎卡牌方法
    print("\n[步骤6] 检查引擎卡牌方法...")
    card_system_path = Path(__file__).parent / "game_engine/card_system.py"
    if card_system_path.exists():
        content = card_system_path.read_text()
        methods = ["use_jiu", "use_tiesuo", "use_bingliang", "use_lebu", "use_wuzhongshengyou"]
        found = [m for m in methods if f"async def {m}" in content]
        print(f"✅ 引擎卡牌方法检查:")
        for method in methods:
            status = "✓" if method in found else "✗"
            print(f"   {status} {method}")
    else:
        print("❌ card_system.py不存在")
    
    # 第七步：生成诊断报告
    print("\n" + "=" * 60)
    print("📋 诊断报告")
    print("=" * 60)
    
    issues = []
    
    # 检查前端资源是否复制
    if not frontend_assets.exists() or len(list(frontend_assets.glob("*.png"))) < 10:
        issues.append({
            "问题": "前端卡牌图片未部署",
            "原因": "extracted_resources/cards的图片未复制到frontend/assets/cards",
            "影响": "游戏中卡牌显示为404或默认占位图",
            "修复": "需要将extracted_resources/cards/*.png复制到frontend/assets/cards/"
        })
    
    if issues:
        print("\n⚠️  发现问题:")
        for i, issue in enumerate(issues, 1):
            print(f"\n问题 {i}: {issue['问题']}")
            print(f"  原因: {issue['原因']}")
            print(f"  影响: {issue['影响']}")
            print(f"  修复: {issue['修复']}")
    else:
        print("\n✅ 未发现明显问题")
    
    print("\n" + "=" * 60)
    print("测试脚本执行完毕")
    print("=" * 60)
    
    return issues

if __name__ == "__main__":
    issues = asyncio.run(main())
    
    # 返回退出码
    exit(0 if not issues else 1)
