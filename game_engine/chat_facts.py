"""保守的公开事实核对：只检查完整、明确、带次数的陈述；推测、引用、条件句放行。"""
import re
from .seats import player_of

_NUMBERS = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_NUMBER = r"([0-9]{1,2}|[零一两二三四五六七八九十])"
_VERB = r"(杀|拆|顺|乐|决斗|救|给牌)"
# 只识别整句，不把“如果/听说/他说/我猜/这轮”中的片段当作全局事实。
_PATTERNS = [
    re.compile(r"^(\d{1,2})号(?:对)?(\d{1,2})号(总共|一共)?" + _VERB + r"(?:了|过)?" + _NUMBER + r"次$"),
    re.compile(r"^(\d{1,2})号(总共|一共)?" + _VERB + r"(?:了|过)?(\d{1,2})号" + _NUMBER + r"次$"),
]
_LABELS = {"杀": {"杀", "火杀", "雷杀"}, "拆": {"过河拆桥"}, "顺": {"顺手牵羊"},
           "乐": {"乐不思蜀"}, "决斗": {"决斗"}, "救": {"救援"},
           "给牌": {"给牌", "仁德", "遗计", "好施"}}


def contradiction(text, state, ledger):
    if ledger is None or re.search(r'[？?“”「」『』"]|如果|假如|可能|听说|我猜|这轮|上轮|刚才', text):
        return None
    for clause in re.split(r"[，,。！!；;\n]", text.replace("主公", "1号")):
        clause = clause.strip()
        for i, pattern in enumerate(_PATTERNS):
            match = pattern.fullmatch(clause)
            if not match:
                continue
            if i == 0:
                src, dst, total, verb, count = match.groups()
            else:
                src, total, verb, dst, count = match.groups()
            source, target = player_of(state, int(src)), player_of(state, int(dst))
            if source is None or target is None:
                continue
            claimed = int(count) if count.isdigit() else _NUMBERS[count]
            entries = [e for e in ledger.entries if e.source_id == source.id and e.target_id == target.id
                       and e.label in _LABELS[verb]]
            actual = len(entries)
            # “杀过一次”不排除杀过多次；只有明确总计时才核对少报。
            if claimed > actual or (total and claimed != actual) or (claimed == 0 and actual):
                return {"claim": clause, "actual": actual, "claimed": claimed,
                        "ledger_sequences": [e.seq for e in entries],
                        "detail": f"{src}号对{dst}号{verb}：账本记录{actual}次，发言声称{claimed}次"}
    return None
