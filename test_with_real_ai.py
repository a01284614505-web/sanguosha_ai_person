#!/usr/bin/env python3
"""使用真实AI API测试游戏"""

import asyncio
import json
import os
from websockets.asyncio.client import connect

async def test_game():
    config = {
        'mode': '5人身份局',
        'player_name': '测试玩家',
        'player': {
            'name': '测试玩家',
            'is_ai': False,
            'hero': {'name': '刘备', 'faction': '蜀', 'max_hp': 4, 'skills': [{'name': '仁德'}]}
        },
        'ais': [
            {'name': 'AI曹操', 'provider': 'deepseek', 'model': 'deepseek-chat', 
             'api_key': os.getenv('SANGUOSHA_TEST_API_KEY', ''), 'temperature': 0.8,
             'hero': {'name': '曹操', 'max_hp': 4, 'skills': [{'name': '奸雄'}]}},
            {'name': 'AI关羽', 'provider': 'deepseek', 'model': 'deepseek-chat',
             'api_key': os.getenv('SANGUOSHA_TEST_API_KEY', ''), 'temperature': 0.8,
             'hero': {'name': '关羽', 'max_hp': 4, 'skills': [{'name': '武圣'}]}},
            {'name': 'AI张飞', 'provider': 'deepseek', 'model': 'deepseek-chat',
             'api_key': os.getenv('SANGUOSHA_TEST_API_KEY', ''), 'temperature': 0.8,
             'hero': {'name': '张飞', 'max_hp': 4, 'skills': [{'name': '咆哮'}]}},
            {'name': 'AI诸葛亮', 'provider': 'deepseek', 'model': 'deepseek-chat',
             'api_key': os.getenv('SANGUOSHA_TEST_API_KEY', ''), 'temperature': 0.8,
             'hero': {'name': '诸葛亮', 'max_hp': 3, 'skills': [{'name': '观星'}]}}
        ]
    }
    
    print("\n╔══════════════════════════════════════════╗")
    print("║  🎮 真实AI测试 - DeepSeek API           ║")
    print("╚══════════════════════════════════════════╝\n")
    
    async with connect('ws://localhost:8889') as ws:
        await ws.send(json.dumps({'type': 'create_game', 'config': config}))
        print("✅ 游戏已创建")
        
        turn_count = 0
        max_turns = 2
        
        for i in range(60):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                data = json.loads(msg)
                
                if data['type'] == 'game_created':
                    print(f"🎮 游戏ID: {data['game_id']}\n")
                
                elif data['type'] == 'game_state':
                    state = data['state']
                    if state['current_name'] == '测试玩家':
                        hp_list = ' | '.join([f"{p['name']}:{p['hp']}" for p in state['players']])
                        print(f"\n第{state['round']}回合 {state['phase']} | HP: {hp_list}")
                
                elif data['type'] == 'your_turn':
                    turn_count += 1
                    hand = data.get('hand', [])
                    actions = data.get('actions', [])
                    
                    hand_str = ', '.join([f"{c['name']}{c['suit'][0]}{c['rank']}" for c in hand])
                    print(f"\n⚔️  你的回合 ({turn_count}/{max_turns})")
                    print(f"   手牌: [{hand_str}]")
                    
                    sha_action = None
                    for act in actions:
                        if act['type'] == 'play_card':
                            idx = act.get('card_index', 0)
                            if idx < len(hand) and hand[idx]['name'] == '杀':
                                sha_action = act
                                break
                    
                    if sha_action and turn_count <= max_turns:
                        card_idx = sha_action['card_index']
                        card = hand[card_idx]
                        print(f"   → 出杀: {card['name']}{card['suit']}{card['rank']} (目标=AI曹操)")
                        await ws.send(json.dumps({'type': 'player_action', 'action': {'type': 'play_card', 'card_index': card_idx}, 'target_ids': [1]}))
                    else:
                        print(f"   → 结束阶段")
                        await ws.send(json.dumps({'type': 'player_action', 'action': {'type': 'end_phase'}}))
                        if turn_count >= max_turns:
                            print(f"\n✅ 测试完成")
                            break
                
                elif data['type'] == 'action_result':
                    print(f"   结果: {'✅' if data.get('success') else '❌'}")
            
            except asyncio.TimeoutError:
                print("\n⏰ 超时")
                break

asyncio.run(test_game())
