"""B2 request, movement, visibility and skill state acceptance cases."""

import asyncio
import json
import unittest

from game_engine import MainEngine
from game_engine.skill_runtime_state import SkillStateStore
from game_engine.protocol import ENGINE_EVENT
from game_engine.state_manager import Card


CONFIG = {
    "mode": "5人身份局", "player_name": "玩家",
    "ais": [{"name": f"AI{i}"} for i in range(4)], "deck_id": "standard",
}


def make_card(tag, name="闪"):
    return Card(f"b2_{tag}", name, "heart", 3, "basic")


class B2ContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = MainEngine(dict(CONFIG))
        self.engine.response_timeout = 0.01
        self.human, self.ai = self.engine.game_state.players[:2]
        for player in self.engine.game_state.players:
            player.hand.clear()
            player.equipment.clear()
            player.judge_area.clear()

    def test_hidden_choice_has_no_live_private_object_in_ai_request(self):
        hidden = make_card("hidden", "桃")
        self.human.hand.append(hidden)
        seen = {}

        class Decision:
            async def make_choice_decision(self, _player, request):
                seen.update(request)
                return [0]

        self.engine.ai_decision = Decision()
        result = asyncio.run(self.engine.ask_choose_cards_result(
            self.ai, "请选择他人手牌", [hidden], hidden_indices=[0],
            places=[(self.human, "hand")],
            context={"all_players": self.engine.game_state.players,
                     "secret_card": hidden, "source": self.human},
        ))
        self.assertEqual(result["cards"], [hidden])
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(seen["candidate_cards"], [None])
        self.assertIsNone(seen["options"][0]["card"])
        self.assertNotIn("candidate_places", seen)
        self.assertNotIn("card_owner", seen)
        self.assertNotIn("secret_card", seen["context"])
        self.assertEqual(seen["context"]["source"]["id"], self.human.id)
        self.assertNotIn("hand", seen["context"]["source"])
        self.assertNotIn("identity", seen["context"]["all_players"][0])

    def test_model_choice_uses_masked_prompt_and_engine_validation(self):
        hidden = make_card("model_secret", "桃")
        self.human.hand.append(hidden)
        self.ai.ai_config["api_key"] = "fake-key"
        prompts = []

        async def model_call(_player, kind, prompt):
            prompts.append((kind, prompt))
            return '{"option_indices":[0]}'

        self.engine.ai_decision._call_with_session = model_call
        result = asyncio.run(self.engine.ask_choose_cards_result(
            self.ai, "选择隐藏牌", [hidden], hidden_indices=[0],
            places=[(self.human, "hand")],
        ))
        self.assertEqual(result["cards"], [hidden])
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(prompts[0][0], "choice")
        self.assertNotIn(hidden.id, prompts[0][1])
        self.assertNotIn("桃", prompts[0][1])

        async def invalid_model(_player, _kind, _prompt):
            return '{"option_indices":[999]}'

        self.engine.ai_decision._call_with_session = invalid_model
        result = asyncio.run(self.engine.ask_choose_cards_result(
            self.ai, "非法模型输出", [hidden], hidden_indices=[0],
            places=[(self.human, "hand")], cancelable=False,
        ))
        self.assertEqual(result["cards"], [hidden])
        self.assertEqual(result["status"], "resolved")

    def test_human_and_ai_choices_recheck_original_snapshot(self):
        async def human_case():
            card = make_card("human")
            self.human.hand.append(card)
            emitted = []

            async def capture(**data):
                emitted.append(data)

            self.engine.on("require_response", capture)
            task = asyncio.create_task(self.engine.ask_choose_cards_result(
                self.human, "选择手牌", [card]))
            await asyncio.sleep(0)
            request = emitted[-1]
            self.assertTrue(request["candidate_version"].startswith(request["request_id"]))
            snapshot = json.dumps(self.engine.serialize(), ensure_ascii=False)
            self.assertNotIn("_pending_requests", snapshot)
            self.assertNotIn(request["request_id"], snapshot)
            self.human.hand.remove(card)
            self.engine.game_state.discard_pile.append(card)
            self.assertEqual(self.engine.submit_response_status(request["request_id"], 0)["status"], "accepted")
            result = await task
            self.assertEqual(result["status"], "stale")
            self.assertEqual(result["cards"], [])

        asyncio.run(human_case())

        card = make_card("ai")
        self.ai.hand.append(card)

        class Decision:
            async def make_choice_decision(self, player, _request):
                player.hand.remove(card)
                return [0]

        self.engine.ai_decision = Decision()
        result = asyncio.run(self.engine.ask_choose_cards_result(self.ai, "选择手牌", [card]))
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["cards"], [])

    def test_ai_response_rechecks_card_and_masks_player_context(self):
        card = make_card("respond")
        self.ai.hand.append(card)
        observed = []
        seen = {}

        async def capture(**data):
            observed.append(data)

        class Decision:
            async def make_response_decision(self, player, request):
                seen.update(request)
                player.hand.remove(card)
                return 0

            def record_outcome(self, *_args):
                pass

        self.engine.ai_decision = Decision()
        self.engine.on(ENGINE_EVENT.SELECTION_RESULT, capture)
        result = asyncio.run(self.engine.request_response(self.ai, {
            "kind": "respond", "requested_name": "闪",
            "options": [{"card": card, "owner": self.ai, "as_name": "闪"}],
            "context": {"source": self.human, "secret_card": make_card("secret")},
        }))
        self.assertFalse(result["bool"])
        self.assertEqual(observed[-1]["status"], "stale")
        self.assertNotIn("owner", seen["options"][0])
        self.assertNotIn("hand", seen["context"]["source"])
        self.assertNotIn("secret_card", seen["context"])

    def test_other_players_response_card_stays_opaque(self):
        donor_card = make_card("donor", "桃")
        self.human.hand.append(donor_card)
        option = {"card": donor_card, "owner": self.human, "as_name": "闪",
                  "skill_name": "护驾", "card_index": 0, "hidden": True}
        wire = self.engine._serialize_option(option, 0)
        decision = self.engine._response_decision_view({"options": [option]})["options"][0]
        self.assertIsNone(wire["card"])
        self.assertIsNone(wire["card_index"])
        self.assertNotIn("桃", wire["label"])
        self.assertIsNone(decision["card"])
        self.assertNotIn("owner", decision)
        self.assertNotIn("card_index", decision)
        self.assertEqual(self.engine.ai_decision._playable_options({"options": [decision]}), [0])

    def test_timeout_uses_same_candidate_snapshot_and_validator(self):
        card = make_card("timeout")
        self.human.hand.append(card)
        seen = []

        async def capture(**data):
            seen.append(data)

        class Decision:
            def simple_choice_decision(self, _player, request):
                self_outer.assertEqual(request["options"][0]["card"], card)
                self_outer.human.hand.remove(card)
                return [0]

        self_outer = self
        self.engine.ai_decision = Decision()
        self.engine.on(ENGINE_EVENT.SELECTION_RESULT, capture)
        result = asyncio.run(self.engine.ask_choose_cards_result(
            self.human, "超时后复核", [card], cancelable=True,
        ))
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["cards"], [])
        self.assertEqual(seen[-1]["status"], "timeout")
        self.assertEqual(self.engine._pending_requests, {})

    def test_transfer_emits_one_fact_and_end_blocks_new_move(self):
        card = make_card("transfer")
        self.human.hand.append(card)
        moves = []

        async def capture(**data):
            moves.append(data["move"])

        self.engine.on(ENGINE_EVENT.CARD_MOVE, capture)
        self.assertTrue(asyncio.run(self.engine.skill_manager.transfer_card(
            self.human, self.ai, card, "测试转移")))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["from_zone"], "hand")
        self.assertEqual(moves[0]["to_zone"], "hand")
        self.assertEqual(moves[0]["from_owner"], self.human.id)
        self.assertEqual(moves[0]["to_owner"], self.ai.id)
        self.assertEqual(self.engine.stats.row(self.human)["cards_lost"], 1)
        self.assertEqual(sum(card is stored for player in self.engine.game_state.players
                             for stored in player.hand), 1)
        json.dumps(self.engine.serialize(), ensure_ascii=False)
        self.engine.game_state.game_over = True
        self.assertIsNone(asyncio.run(self.engine.move_card(
            card, "hand", "discard", from_owner=self.ai,
            reason="结束后", actor_id=self.ai.id)))
        self.assertIn(card, self.ai.hand)
        self.assertEqual(len(moves), 1)

    def test_temporary_move_is_visible_to_listener_but_not_loss_stat(self):
        card = make_card("temporary")
        self.human.hand.append(card)
        seen = []

        class Listener:
            async def on_card_move(self, _card, event):
                seen.append(event)

        self.engine.skill_manager.handlers = [Listener()]
        event = asyncio.run(self.engine.move_card(
            card, "hand", "temporary", from_owner=self.human,
            to_owner=self.human, reason="谦逊", visibility="owner"))
        self.assertIsNotNone(event)
        self.assertEqual(seen, [event])
        self.assertEqual(self.engine.stats.row(self.human)["cards_lost"], 0)
        self.assertEqual(self.human.temporary, [card])

    def test_committed_move_keeps_stat_when_end_arrives_during_publish(self):
        card = make_card("race")
        self.human.hand.append(card)

        async def end_on_publish(**_data):
            await self.engine.request_end_game("测试结束")

        self.engine.on(ENGINE_EVENT.CARD_MOVE, end_on_publish)
        event = asyncio.run(self.engine.move_card(
            card, "hand", "discard", from_owner=self.human,
            reason="测试弃置", actor_id=self.human.id))
        self.assertIsNotNone(event)
        self.assertTrue(self.engine.game_aborted)
        self.assertEqual(self.engine.stats.row(self.human)["cards_lost"], 1)
        self.assertIn(card, self.engine.game_state.discard_pile)

    def test_duplicate_entity_id_rejects_move_without_side_effect(self):
        first = make_card("duplicate")
        second = make_card("duplicate")
        self.human.hand.append(first)
        self.ai.hand.append(second)
        before = len(self.engine.game_state.card_move_events)
        event = asyncio.run(self.engine.move_card(
            first, "hand", "discard", from_owner=self.human,
            reason="测试弃置", actor_id=self.human.id))
        self.assertIsNone(event)
        self.assertIn(first, self.human.hand)
        self.assertIn(second, self.ai.hand)
        self.assertNotIn(first, self.engine.game_state.discard_pile)
        self.assertEqual(len(self.engine.game_state.card_move_events), before)

    def test_entity_and_skill_sha_use_one_effect_context_path(self):
        physical = make_card("physical", "杀")
        payment = make_card("payment")
        virtual = make_card("virtual", "杀")
        observed = []

        async def capture_damage(_source, _target, _amount, *, card, context):
            observed.append((card, context["effect_context"].to_dict(), context["sequence"]))

        self.engine.skill_manager.handlers = []
        self.engine.card_system.damage = capture_damage

        async def scenario():
            ordinary = self.engine._new_effect_context(self.human, physical, target=self.ai)
            self.assertTrue(await self.engine.card_system.use_sha(
                self.human, physical, self.ai, effect_context=ordinary))
            self.human.sha_count = 0
            skill = self.engine._new_effect_context(
                self.human, virtual, skill_source="武圣",
                card_cost_ids=[payment.id], target=self.ai,
            )
            self.assertTrue(await self.engine.card_system.use_sha(
                self.human, virtual, self.ai, effect_context=skill))

        asyncio.run(scenario())
        self.assertEqual([row[1]["card_cost_ids"] for row in observed],
                         [[physical.id], [payment.id]])
        self.assertEqual([row[1]["skill_source"] for row in observed], [None, "武圣"])
        self.assertEqual([row[2] for row in observed], [1, 1])
        json.dumps([row[1] for row in observed], ensure_ascii=False)

    def test_skill_sources_and_game_charges_survive_turn_and_serialization(self):
        store = SkillStateStore()
        first = store.register(self.human.id, "限定技", source="hero", charges=1)
        store.add_source(self.human.id, "限定技", "temporary")
        self.assertTrue(store.consume(self.human.id, "限定技", source="hero", charges=1))
        self.assertFalse(store.consume(self.human.id, "限定技", source="hero", charges=1))
        self.assertEqual(first.charges, 0)
        self.assertEqual(first.usage_count, 1)
        store.disable(self.human.id, "限定技", source="hero")
        store.restore(self.human.id, "限定技", source="hero")
        restored = SkillStateStore.from_dict(json.loads(store.to_json()))
        self.assertEqual(restored.get(self.human.id, "限定技", source="hero").charges, 0)
        self.assertTrue(restored.remove_source(self.human.id, "限定技", "temporary"))
        self.assertIsNotNone(restored.get(self.human.id, "限定技", source="hero"))

        # A second source can still pay after the native source is exhausted.
        self.assertTrue(store.remove_source(self.human.id, "限定技", "temporary"))
        store.add_source(self.human.id, "限定技", "borrowed", charges=1)
        self.assertTrue(store.consume(self.human.id, "限定技", charges=1))
        self.assertEqual(store.get(self.human.id, "限定技", source="borrowed").charges, 0)

        store.register(self.human.id, "回合技", source="hero", usage_scope="current_turn")
        self.assertFalse(store.consume(self.human.id, "回合技", current_player_id=self.ai.id,
                                       turn_id=1, charges=0))
        self.assertTrue(store.consume(self.human.id, "回合技", current_player_id=self.human.id,
                                      turn_id=1, charges=0))
        self.assertFalse(store.consume(self.human.id, "回合技", current_player_id=self.human.id,
                                       turn_id=1, charges=0))
        self.assertTrue(store.consume(self.human.id, "回合技", current_player_id=self.human.id,
                                      turn_id=2, charges=0))


if __name__ == "__main__":
    unittest.main()
