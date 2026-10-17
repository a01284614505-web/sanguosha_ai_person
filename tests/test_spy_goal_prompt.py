"""AI 内奸不应把"杀死主公"当成胜利目标：提示词里要写清内奸的真实目标与胜负规则。"""

import unittest

from game_engine import MainEngine


CONFIG = {
    "mode": "5人身份局", "player_name": "玩家",
    "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
}

SPY_GOAL = ("在反贼和忠臣全部阵亡之前，主公阵亡等于你失败。主公体力很低时不要攻击主公，"
            "他濒死时应考虑用桃救他；先帮弱势的一方，维持局面平衡，最后再与主公单挑。")


class SpyGoalPrompt(unittest.TestCase):
    def setUp(self):
        self.engine = MainEngine(dict(CONFIG))
        players = self.engine.game_state.players
        identities = ["lord", "rebel", "loyalist", "spy"]
        for player, identity in zip(players, identities):
            player.identity = identity
            player.alive = True
        players[0].hp = 1  # 主公只剩 1 体力
        for extra in players[len(identities):]:
            extra.alive = False
        self.lord, self.rebel, self.loyalist, self.spy = players[:4]
        self.decision = self.engine.ai_decision

    def prompt_of(self, player):
        return "\n".join(m["content"] for m in self.decision.get_session(player)["messages"])

    def test_spy_prompt_contains_goal_in_chinese(self):
        text = self.prompt_of(self.spy)
        self.assertIn(SPY_GOAL, text)
        self.assertIn("身份：内奸", text)
        self.assertNotIn("身份：spy", text)

    def test_other_identities_do_not_get_spy_goal(self):
        for player, name in ((self.lord, "主公"), (self.rebel, "反贼"), (self.loyalist, "忠臣")):
            text = self.prompt_of(player)
            self.assertNotIn(SPY_GOAL, text)
            self.assertIn(f"身份：{name}", text)
            self.assertIn("【你的目标】", text)

    def test_global_rules_match_check_victory(self):
        rules = self.decision.worldbook_manager.build_global_rules()
        self.assertIn("主公阵亡时：若场上只剩内奸一人存活，内奸胜；否则反贼胜（不论是谁杀死主公）。", rules)
        self.assertIn("反贼与内奸全部阵亡且主公存活，主公和忠臣胜。", rules)
        self.assertNotIn("反贼杀死主公即胜", rules)


if __name__ == "__main__":
    unittest.main()
