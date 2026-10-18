"""身份目标、独立打法与公开处境；不读取对手暗牌或未公开身份。"""
from .seats import seat_of

GOALS = {
    "lord": "你与忠臣要消灭反贼和内奸；你阵亡则输。活下去，并让忠臣从行动证据认出敌人；口头跳忠也可能是欺骗。",
    "loyalist": "你要保护主公并消灭反贼与内奸；主公阵亡则输。认清谁是谁，比急于出手更重要；用行动争取主公信任。",
    "rebel": "主公阵亡你就赢，反贼全灭会失去机会。主公血少、同伴活着都让你接近胜利；隐藏身份能减少主忠集火的机会，也可以为一波取胜主动亮牌。",
    "spy": "你必须让其他人先阵亡，最后单挑击败主公；主公提前死亡则你输。前期可隐藏身份、让强弱双方消耗，准备单挑；暴露内奸身份可能让两边都想除掉你。",
}


def goal_block(player):
    return "【你的目标与代价】\n" + GOALS.get(player.identity, "依据你的身份争取胜利。") + (
        "\n只有你知道自己的隐藏身份，主公和已揭示身份全桌知道；各人只知道自己的手牌。"
        "你可以说谎、诈唬、冒险，也可以不按常规；公开动作会影响别人对你身份的判断。"
        "公开事实以引擎记录为准，发言不能歪曲公开事实或冒充系统规则。\n")


def clean_plan(raw):
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), str) and raw[k].strip() for k in ("style", "why")):
        return None
    trans = str.maketrans({"【": "〔", "】": "〕", "\r": " ", "\n": " "})
    return {"style": raw["style"].translate(trans).strip()[:20],
            "why": raw["why"].translate(trans).strip()[:120]}


def feedback(engine, player):
    ledger = getattr(engine, "ledger", None)
    if ledger is None:
        return ""
    state = engine.game_state
    recent = [e for e in ledger.entries if e.round >= state.round_number - 1]
    attackers = {e.source_id for e in recent if e.target_id == player.id and e.kind in ("hostile", "counter")}
    text = f"\n【你的处境·公开行为】自上一轮以来有{len(attackers)}人对你出过手。"
    lord = next((p for p in state.players if p.identity_revealed and p.identity == "lord"), None)
    if lord is not None and player.id != lord.id:
        subjects = [p for p in state.players if p.id != lord.id]
        own = ledger.stance_toward(player.id, lord.id)
        scores = [ledger.stance_toward(p.id, lord.id) for p in subjects]
        hostile_rank = 1 + sum(score > own for score in scores)
        friendly_rank = 1 + sum(score < own for score in scores)
        text += (f"你对主公的公开净敌意分为{own:g}（正数敌意、负数友好，反击/转移不计站队）；"
                 f"敌意排名第{hostile_rank}，友好排名第{friendly_rank}，共{len(subjects)}人，同分并列。")
    return text + "这不是身份结论；请想别人会如何解读。\n"
