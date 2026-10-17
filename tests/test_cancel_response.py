"""取消可取消的选择请求（如是否替换判定牌）不得报参数错误。

覆盖：显式 cancel 标志、旧前端发空数组、不可取消请求仍拒绝、
多选请求的空数组仍按数量规则处理、经 submit_action 的整条链路。
"""

import asyncio
import unittest

from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


CONFIG = {
    "mode": "5人身份局", "player_name": "玩家",
    "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
}


def card(tag, name="闪", kind="basic"):
    return Card(tag, name, "spade", 5, kind)


class CancelResponse(unittest.TestCase):
    def setUp(self):
        self.engine = MainEngine(dict(CONFIG))
        self.engine.response_timeout = 0.5
        self.human = self.engine.game_state.players[0]
        self.engine.game_state.current_player = self.human
        self.engine.game_state.current_phase = Phase.PLAY
        for player in self.engine.game_state.players:
            player.hand.clear()
        self.requests = []

        async def capture(**data):
            self.requests.append(data)

        self.engine.on("require_response", capture)

    def _ask_cards(self, cards, **kwargs):
        # 候选必须真的在真人手里，否则引擎会按"候选已过期"处理选牌
        for c in cards:
            if c not in self.human.hand:
                self.human.hand.append(c)
        return asyncio.create_task(self.engine.ask_choose_cards(
            self.human, "是否替换判定牌", cards, **kwargs))

    def test_single_cancelable_accepts_cancel_flag_and_empty_list(self):
        replacement = card("r1")

        async def scenario():
            for value in ({"cancel": True}, []):
                task = self._ask_cards([replacement], min_n=0, max_n=1, cancelable=True)
                await asyncio.sleep(0)
                rid = self.requests[-1]["request_id"]
                self.assertTrue(self.requests[-1]["selection"]["cancelable"])
                receipt = self.engine.submit_response_status(rid, value)
                self.assertEqual(receipt["status"], "accepted", (value, receipt))
                self.assertEqual(await task, [])
            # 取消之后仍能正常选牌
            task = self._ask_cards([replacement], min_n=0, max_n=1, cancelable=True)
            await asyncio.sleep(0)
            rid = self.requests[-1]["request_id"]
            self.assertEqual(self.engine.submit_response_status(rid, 0)["status"], "accepted")
            self.assertEqual(await task, [replacement])

        asyncio.run(scenario())
        self.assertEqual(self.engine._pending_requests, {})

    def test_non_cancelable_still_rejects_cancel_and_empty_list(self):
        replacement = card("r2")

        async def scenario():
            task = self._ask_cards([replacement], min_n=1, max_n=1, cancelable=False)
            await asyncio.sleep(0)
            rid = self.requests[-1]["request_id"]
            for value in ({"cancel": True}, []):
                receipt = self.engine.submit_response_status(rid, value)
                self.assertEqual(receipt["status"], "invalid", (value, receipt))
            self.assertEqual(self.engine.submit_response_status(rid, 0)["status"], "accepted")
            await task

        asyncio.run(scenario())

    def test_multi_empty_list_keeps_count_rule(self):
        first, second = card("m1"), card("m2")

        async def scenario():
            task = self._ask_cards([first, second], min_n=2, max_n=2, cancelable=False)
            await asyncio.sleep(0)
            rid = self.requests[-1]["request_id"]
            self.assertEqual(self.engine.submit_response_status(rid, [])["status"], "invalid")
            self.assertEqual(self.engine.submit_response_status(rid, [0, 1])["status"], "accepted")
            await task

            # 可取消的多选：空数组是合法的"选 0 张"，不应被当成取消而丢失数量校验
            task = self._ask_cards([first, second], min_n=0, max_n=2, cancelable=True)
            await asyncio.sleep(0)
            rid = self.requests[-1]["request_id"]
            self.assertEqual(self.engine.submit_response_status(rid, [])["status"], "accepted")
            self.assertEqual(await task, [])

        asyncio.run(scenario())

    def test_cancel_through_submit_action_like_the_browser(self):
        replacement = card("r3")

        async def scenario():
            task = self._ask_cards([replacement], min_n=0, max_n=1, cancelable=True)
            await asyncio.sleep(0)
            rid = self.requests[-1]["request_id"]
            receipt = self.engine.submit_action(
                {"type": "response", "request_id": rid, "cancel": True}, [])
            self.assertEqual(receipt["status"], "accepted", receipt)
            self.assertEqual(await task, [])

            # 旧前端：option_indices 为空数组
            task = self._ask_cards([replacement], min_n=0, max_n=1, cancelable=True)
            await asyncio.sleep(0)
            rid = self.requests[-1]["request_id"]
            receipt = self.engine.submit_action(
                {"type": "response", "request_id": rid, "option_indices": []}, [])
            self.assertEqual(receipt["status"], "accepted", receipt)
            self.assertEqual(await task, [])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
