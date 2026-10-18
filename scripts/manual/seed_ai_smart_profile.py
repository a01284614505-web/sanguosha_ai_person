"""创建浏览器展示夹具（合成称号统计）。仅对隔离的测试历史文件运行，不用于真实战绩。"""
import os, tempfile
from pathlib import Path
from game_engine.game_history import GameHistoryStore
store=GameHistoryStore(os.environ.get('SANGUOSHA_HISTORY_PATH', str(Path(tempfile.gettempdir())/'ai-smart-browser-history.json')))
store.ai_players('ai_smart_browser')
data=store._load()
p=data['profiles']['ai_smart_browser']
p['identity_cards']=10
p['title_stats']={'wins': 100, 'win_streak': 10}
p['equipped_title']='wins_100'
for row, chosen in zip(p['ai_players'].values(), ['wins_10','wins_50','wins_100', '__none__']):
 row['stats']={'wins':100,'win_streak':10}
 row['equipped_title']=chosen
store._save(data)
