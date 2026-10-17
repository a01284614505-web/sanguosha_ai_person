"""B1: real engine request lifecycle and end-of-game invariants."""

import asyncio
import json
import unittest

from game_server import GameServer
from game_engine import MainEngine
from game_engine.state_manager import Card, Phase


CONFIG = {
    "mode": "5人身份局", "player_name": "玩家",
    "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
}


def card(tag, name, kind="trick"):
    return Card(tag, name, "spade", 5, kind)


class B1InputLifecycle(unittest.TestCase):
    def setUp(self):
        self.engine = MainEngine(dict(CONFIG))
        self.engine.response_timeout = 0.1
        self.human, self.target = self.engine.game_state.players[:2]
        self.engine.game_state.current_player = self.human
        self.engine.game_state.current_phase = Phase.PLAY
        for player in self.engine.game_state.players:
            player.hand.clear()
            player.equipment.clear()
            player.judge_area.clear()

    def test_judge_only_target_is_legal_for_both_cards(self):
        judged = card("judge", "乐不思蜀")
        self.target.judge_area.append(judged)
        for name in ("过河拆桥", "顺手牵羊"):
            playing = card(name, name)
            self.human.hand.append(playing)
            self.assertTrue(self.engine.rules.can_play_card(
                self.human, playing, [self.target])[0], name)
            actions = self.engine.get_available_actions(self.human)
            self.assertTrue(any(
                action.get("type") == "play_card"
                and self.target.id in action.get("valid_targets", [])
                for action in actions), name)
            self.human.hand.remove(playing)
        self.target.judge_area.clear()
        self.assertFalse(self.engine.rules.can_play_guohe(
            self.human, card("g", "过河拆桥"), [self.target])[0])
        self.assertFalse(self.engine.rules.can_play_shunshou(
            self.human, card("s", "顺手牵羊"), [self.target])[0])

    def test_end_during_discard_has_no_card_or_stat_or_animation(self):
        cards = [card(f"c{i}", "杀", "basic") for i in range(3)]
        self.human.hand.extend(cards)
        self.human.hp = 1
        requests, animations, ends = [], [], []

        async def collect_request(**data):
            requests.append(data)

        async def collect_animation(**data):
            animations.append(data)

        async def collect_end(**data):
            ends.append(data)

        self.engine.on("require_response", collect_request)
        self.engine.on("card_animation", collect_animation)
        self.engine.on("game_end", collect_end)

        async def scenario():
            task = asyncio.create_task(self.engine._execute_phase_with_ui(Phase.DISCARD))
            await asyncio.sleep(0)
            self.assertEqual(len(requests), 1)
            self.assertTrue(await self.engine.request_end_game("主动结束"))
            self.assertFalse(await self.engine.request_end_game("重复结束"))
            await task

        asyncio.run(scenario())
        self.assertEqual(self.human.hand, cards)
        self.assertEqual(self.engine.game_state.discard_pile, [])
        self.assertEqual(self.engine.stats.row(self.human)["cards_lost"], 0)
        self.assertEqual(animations, [])
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["message"], "主动结束")
        self.assertEqual(self.engine._pending_requests, {})

    def test_bad_duplicate_and_stale_response_cannot_reach_next_request(self):
        first = card("first", "杀", "basic")
        second = card("second", "闪", "basic")
        self.human.hand.extend([first, second])
        requests = []

        async def capture(**data):
            requests.append(data)

        self.engine.on("require_response", capture)

        async def scenario():
            first_task = asyncio.create_task(self.engine.ask_choose_cards(
                self.human, "第一次", [first, second], min_n=2, max_n=2,
                cancelable=False))
            await asyncio.sleep(0)
            old_id = requests[-1]["request_id"]
            for value in ([0], [0, 0], [0, 99], 0, [True, 1]):
                self.assertEqual(self.engine.submit_response_status(old_id, value)["status"], "invalid")
            self.assertEqual(self.engine.submit_response_status(old_id, [0, 1])["status"], "accepted")
            self.assertEqual(self.engine.submit_response_status(old_id, [0, 1])["status"], "duplicate")
            self.assertEqual(await first_task, [first, second])

            second_task = asyncio.create_task(self.engine.ask_choose_cards(
                self.human, "第二次", [second], cancelable=False))
            await asyncio.sleep(0)
            new_id = requests[-1]["request_id"]
            self.assertNotEqual(old_id, new_id)
            self.assertEqual(self.engine.submit_response_status(old_id, 0)["status"], "duplicate")
            self.assertFalse(second_task.done())
            self.assertEqual(self.engine.submit_response_status(new_id, 0)["status"], "accepted")
            self.assertEqual(await second_task, [second])
            self.assertEqual(self.engine.submit_response_status("missing", 0)["status"], "stale")

        asyncio.run(scenario())
        self.assertEqual(self.engine._pending_requests, {})

    def test_end_blocks_late_response_and_damage(self):
        shan = card("shan", "闪", "basic")
        self.human.hand.append(shan)
        requests = []

        async def capture(**data):
            requests.append(data)

        self.engine.on("require_response", capture)

        async def scenario():
            task = asyncio.create_task(self.engine.request_response(self.human, {
                "kind": "respond", "requested_name": "闪",
                "options": [{"card": shan, "owner": self.human, "as_name": "闪"}],
            }))
            await asyncio.sleep(0)
            rid = requests[-1]["request_id"]
            await self.engine.request_end_game()
            self.assertEqual(self.engine.submit_response_status(rid, 0)["status"], "game_ended")
            self.assertFalse((await task)["bool"])
            hp = self.target.hp
            stats = self.engine.stats.snapshot()
            await self.engine.card_system.damage(self.human, self.target, 1)
            self.assertEqual(self.target.hp, hp)
            self.assertEqual(self.engine.stats.snapshot(), stats)

        asyncio.run(scenario())

    def test_server_returns_response_receipts_and_hides_context_card(self):
        shan = card("shan", "闪", "basic")
        self.human.hand.append(shan)
        requests = []

        async def capture(**data):
            requests.append(data)

        class Socket:
            def __init__(self):
                self.messages = []

            async def send(self, raw):
                self.messages.append(json.loads(raw))

        socket = Socket()
        server = GameServer()
        server.engines["42"] = self.engine
        server.ws_map[socket] = "42"
        self.engine.game_id = "42"
        self.engine.on("require_response", capture)

        async def scenario():
            task = asyncio.create_task(self.engine.request_response(self.human, {
                "kind": "respond", "requested_name": "闪",
                "options": [{"card": shan, "owner": self.human, "as_name": "闪"}],
                "context": {"card": shan, "source": self.target},
            }))
            await asyncio.sleep(0)
            request = requests[-1]
            self.assertEqual(request["game_id"], "42")
            self.assertTrue(request["request_id"].startswith("42:"))
            self.assertNotIn("card", request["context"])
            self.assertEqual(request["context"]["source"]["id"], self.target.id)
            rid = request["request_id"]
            for index, status in ((99, "invalid"), (0, "accepted"), (0, "duplicate")):
                await server.do_action(socket, {"action": {
                    "type": "response", "request_id": rid, "option_index": index}})
                self.assertEqual(socket.messages[-1]["status"], status)
                self.assertEqual(socket.messages[-1]["request_id"], rid)
            self.assertTrue((await task)["bool"])

        asyncio.run(scenario())

    def test_end_during_play_animation_keeps_card_in_hand(self):
        playing = card("playing", "过河拆桥")
        self.human.hand.append(playing)
        self.target.hand.append(card("target", "闪", "basic"))

        async def scenario():
            started = asyncio.Event()
            release = asyncio.Event()

            async def animation(**_data):
                started.set()
                await release.wait()

            self.engine.on("card_animation", animation)
            task = asyncio.create_task(self.engine.execute_action(
                self.human, {"type": "play_card", "card_index": 0}, [self.target.id]))
            await started.wait()
            await self.engine.request_end_game("动画中结束")
            before = self.engine.stats.snapshot()
            release.set()
            self.assertFalse(await task)
            self.assertEqual(self.engine.stats.snapshot(), before)

        asyncio.run(scenario())
        self.assertEqual(self.human.hand, [playing])
        self.assertEqual(self.engine.game_state.discard_pile, [])

    def test_end_before_run_does_not_start_turn_or_emit_twice(self):
        ends = []

        async def collect(**data):
            ends.append(data)

        self.engine.on("game_end", collect)
        initial_deck = len(self.engine.game_state.deck)

        async def scenario():
            self.assertTrue(await self.engine.request_end_game("开局即结束"))
            self.assertEqual(await self.engine.run(), "aborted")

        asyncio.run(scenario())
        self.assertEqual(len(ends), 1)
        self.assertEqual(self.engine.completed_turns, 0)
        self.assertEqual(len(self.engine.game_state.deck), initial_deck)


if __name__ == "__main__":
    unittest.main()
