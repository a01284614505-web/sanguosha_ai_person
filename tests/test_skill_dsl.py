import unittest
from game_engine.skill_dsl import MAX_STEPS, SkillDSLValidationError, compile_skill, evaluate_condition

class SkillDSLTests(unittest.TestCase):
    def test_compiles_five_representative_effect_programs(self):
        programs = [
            {"version": 1, "trigger": "damage_received", "effects": [{"type": "draw_cards", "target": "owner", "count": 1}]},
            {"version": 1, "trigger": "phase_start", "effects": [{"type": "recover", "target": "owner", "amount": 1}]},
            {"version": 1, "trigger": "damage_dealt", "effects": [{"type": "damage", "target": "target", "amount": 1}]},
            {"version": 1, "trigger": "judge_after", "effects": [{"type": "announce", "text": "判定完成"}]},
            {"version": 1, "trigger": "card_gained", "cost": [{"interaction": "ask_choose_cards", "min": 1, "max": 1}], "targets": {"selector": "chosen_players", "min": 1, "max": 1}, "effects": [{"type": "transfer_card"}]},
        ]
        for program in programs:
            self.assertGreater(compile_skill(program).steps, 0)

    def test_condition_language_has_deterministic_nested_semantics(self):
        expr = {"op": "all", "args": [{"op": "gte", "path": "owner.hp", "value": 2}, {"op": "in", "path": "event.phase", "values": ["play", "draw"]}, {"op": "not", "args": {"op": "eq", "path": "game.round", "value": 0}}]}
        self.assertTrue(evaluate_condition(expr, {"owner": {"hp": 3}, "event": {"phase": "play"}, "game": {"round": 1}}))
        self.assertFalse(evaluate_condition(expr, {"owner": {"hp": 1}, "event": {"phase": "play"}, "game": {"round": 1}}))

    def test_rejects_code_paths_unknown_effects_and_oversized_programs(self):
        bad = [
            {"version": 1, "trigger": "__import__", "effects": [{"type": "announce"}]},
            {"version": 1, "trigger": "phase_start", "effects": [{"type": "python", "code": "open('/etc/passwd')"}]},
            {"version": 1, "trigger": "phase_start", "condition": {"op": "exists", "path": "owner.__class__"}, "effects": [{"type": "announce"}]},
            {"version": 1, "trigger": "phase_start", "effects": [{"type": "announce"}] * MAX_STEPS},
        ]
        for program in bad:
            with self.assertRaises(SkillDSLValidationError): compile_skill(program)

    def test_all_four_interaction_primitives_are_compilable(self):
        for primitive, extra in [("ask_confirm", {}), ("ask_choose_players", {"min": 1, "max": 2}), ("ask_choose_cards", {"min": 1, "max": 2}), ("ask_choose_option", {"choices": ["a", "b"]})]:
            program = {"version": 1, "trigger": "play_action", "cost": [{"interaction": primitive, **extra}], "effects": [{"type": "announce"}]}
            self.assertTrue(compile_skill(program))

if __name__ == "__main__": unittest.main()
