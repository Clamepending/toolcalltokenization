import unittest

from toolcalltokenization.selector_benchmark import (
    choose_oracle_macro,
    evaluate_selector_replay,
    goal_has_configuration_hint,
    macro_expected_gain,
    macro_start_compatible,
    primitive_action_description,
    primitive_action_name,
)


class SelectorBenchmarkTests(unittest.TestCase):
    def test_macro_expected_gain_prefers_longer_reusable_macro(self):
        short_macro = {"sequence": ["A", "B"], "replay_precision": 1.0}
        long_macro = {"sequence": ["A", "B", "C", "D"], "replay_precision": 0.75}
        self.assertGreater(macro_expected_gain(long_macro), macro_expected_gain(short_macro))

    def test_choose_oracle_macro_prefers_higher_expected_gain(self):
        short_macro = {
            "macro_id": "M001",
            "suggested_name": "short",
            "sequence": ["A", "B"],
            "replay_precision": 1.0,
            "support": 10,
        }
        long_macro = {
            "macro_id": "M002",
            "suggested_name": "long",
            "sequence": ["A", "B", "C", "D"],
            "replay_precision": 0.75,
            "support": 4,
        }
        chosen = choose_oracle_macro(["A", "B", "C", "D"], [short_macro, long_macro], ())
        self.assertEqual(chosen["macro_id"], "M002")

    def test_primitive_action_metadata_is_readable(self):
        row = {
            "action_type": "fill",
            "target_role": "textbox",
            "target_label": "Password",
        }
        self.assertIn("password", primitive_action_name(row))
        self.assertIn("password", primitive_action_description(row))

    def test_goal_has_configuration_hint_detects_structured_task(self):
        row = {
            "task": 'Order a laptop with configuration {"Additional software requirements": "Slack"}',
        }
        self.assertTrue(goal_has_configuration_hint(row))

    def test_macro_start_compatible_checks_kind_role_and_label(self):
        row = {
            "action_type": "fill",
            "target_role": "textbox",
            "target_label": "Username",
        }
        macro = {
            "step_templates": [
                {"kind": "fill", "target_role": "textbox", "target_label": "username"},
                {"kind": "click", "target_role": "button", "target_label": "login"},
            ]
        }
        self.assertTrue(macro_start_compatible(row, macro))
        row["target_label"] = "Password"
        self.assertFalse(macro_start_compatible(row, macro))

    def test_evaluate_selector_replay_recovers_oracle_macro(self):
        rows = [
            {
                "episode_id": "login::0000",
                "step_index": 0,
                "task": 'Enter username "alice" and password "pw" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Username",
                "value": "alice",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0000",
                "step_index": 1,
                "task": 'Enter username "alice" and password "pw" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Password",
                "value": "pw",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0000",
                "step_index": 2,
                "task": 'Enter username "alice" and password "pw" and log in.',
                "action_type": "click",
                "action_name": "click",
                "target_role": "button",
                "target_label": "Login",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0001",
                "step_index": 0,
                "task": 'Enter username "bob" and password "pw2" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Username",
                "value": "bob",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0001",
                "step_index": 1,
                "task": 'Enter username "bob" and password "pw2" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Password",
                "value": "pw2",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0001",
                "step_index": 2,
                "task": 'Enter username "bob" and password "pw2" and log in.',
                "action_type": "click",
                "action_name": "click",
                "target_role": "button",
                "target_label": "Login",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
        ]
        registry = {
            "group_by": "task_name",
            "canonicalization_mode": "dataflow_coarse",
            "registry": [
                {
                    "group_key": "login",
                    "macro_id": "M001",
                    "suggested_name": "login_fill_username_then_fill_password_then_click_login_m001",
                    "suggested_description": "Fill the username and password fields, then click login.",
                    "sequence": [
                        "FILL|role=input|label=<TEXT>|use=B01",
                        "FILL|role=input|label=password|use=B02",
                        "CLICK|role=button|label=login",
                    ],
                    "step_templates": [
                        {"kind": "fill", "target_role": "textbox", "target_label": "username"},
                        {"kind": "fill", "target_role": "textbox", "target_label": "password"},
                        {"kind": "click", "target_role": "button", "target_label": "login"},
                    ],
                    "replay_precision": 1.0,
                    "support": 2,
                }
            ],
        }
        result = evaluate_selector_replay(
            rows,
            registry,
            group_by="task_name",
            canonicalization_mode="dataflow_coarse",
            train_ratio=0.5,
            split_seed=0,
            action_scope="task",
            policy_mode="oracle",
        )
        self.assertEqual(result["summary"]["primitive_steps"], 3)
        self.assertEqual(result["summary"]["agent_decisions"], 1)
        self.assertEqual(result["summary"]["steps_saved"], 2)

    def test_evaluate_selector_replay_supports_llm_policy(self):
        rows = [
            {
                "episode_id": "login::0000",
                "step_index": 0,
                "task": 'Enter username "alice" and password "pw" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Username",
                "value": "alice",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0000",
                "step_index": 1,
                "task": 'Enter username "alice" and password "pw" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Password",
                "value": "pw",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0000",
                "step_index": 2,
                "task": 'Enter username "alice" and password "pw" and log in.',
                "action_type": "click",
                "action_name": "click",
                "target_role": "button",
                "target_label": "Login",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0001",
                "step_index": 0,
                "task": 'Enter username "bob" and password "pw2" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Username",
                "value": "bob",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0001",
                "step_index": 1,
                "task": 'Enter username "bob" and password "pw2" and log in.',
                "action_type": "fill",
                "action_name": "fill",
                "target_role": "textbox",
                "target_label": "Password",
                "value": "pw2",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
            {
                "episode_id": "login::0001",
                "step_index": 2,
                "task": 'Enter username "bob" and password "pw2" and log in.',
                "action_type": "click",
                "action_name": "click",
                "target_role": "button",
                "target_label": "Login",
                "website": "demo",
                "task_name": "login",
                "url": "https://demo.test/login",
            },
        ]
        registry = {
            "group_by": "task_name",
            "canonicalization_mode": "dataflow_coarse",
            "registry": [
                {
                    "group_key": "login",
                    "macro_id": "M001",
                    "suggested_name": "login_fill_username_then_fill_password_then_click_login_m001",
                    "suggested_description": "Fill the username and password fields, then click login.",
                    "sequence": [
                        "FILL|role=input|label=<TEXT>|use=B01",
                        "FILL|role=input|label=password|use=B02",
                        "CLICK|role=button|label=login",
                    ],
                    "step_templates": [
                        {"kind": "fill", "target_role": "textbox", "target_label": "username"},
                        {"kind": "fill", "target_role": "textbox", "target_label": "password"},
                        {"kind": "click", "target_role": "button", "target_label": "login"},
                    ],
                    "replay_precision": 1.0,
                    "support": 2,
                }
            ],
        }

        class FakeChooser:
            def choose(self, *, goal, context_text, candidates):
                macro = next(candidate for candidate in candidates if candidate["kind"] == "macro")
                return {
                    "id": macro["id"],
                    "reason": "macro fits",
                    "cached": False,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                    "raw_content": '{"id":"%s"}' % macro["id"],
                }

        result = evaluate_selector_replay(
            rows,
            registry,
            group_by="task_name",
            canonicalization_mode="dataflow_coarse",
            train_ratio=0.5,
            split_seed=0,
            action_scope="task",
            policy_mode="llm",
            llm_chooser=FakeChooser(),
        )
        self.assertEqual(result["summary"]["policy_mode"], "llm")
        self.assertEqual(result["summary"]["agent_decisions"], 1)
        self.assertEqual(result["summary"]["llm_calls"], 1)
        self.assertEqual(result["summary"]["llm_total_tokens"], 12)


if __name__ == "__main__":
    unittest.main()
