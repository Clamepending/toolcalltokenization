import unittest

from toolcalltokenization.miniwob_benchmark import (
    bind_macro_steps,
    build_click_button_sequence,
    build_form_sequence_2,
    build_form_sequence_3,
    build_login_user,
    build_use_autocomplete,
    choose_macro,
    default_miniwob_url,
    macro_action_string,
    observation_text,
    primitive_action_description,
    primitive_action_name,
    representative_templates_for_macro,
    render_action,
    semantic_choice,
    semantic_macro_description,
    semantic_macro_name,
    task_name_for_env_id,
)


def make_obs(nodes):
    return {
        "axtree_object": {
            "nodes": nodes,
        }
    }


def ax_node(bid, role, name):
    node = {
        "role": {"value": role},
        "name": {"value": name},
    }
    if bid is not None:
        node["browsergym_id"] = str(bid)
    return node


class MiniwobBenchmarkTests(unittest.TestCase):
    def test_task_name_for_env_id(self):
        self.assertEqual(task_name_for_env_id("browsergym/miniwob.login-user"), "login_user")

    def test_default_miniwob_url_points_to_local_clone(self):
        self.assertIn("data/local/miniwob-plusplus/miniwob/html/miniwob/", default_miniwob_url())

    def test_build_login_user_uses_expected_labels(self):
        obs = make_obs([ax_node("20", "button", "Login")])
        steps = build_login_user(
            'Enter the username "cierra" and the password "11L" into the text fields and press login.',
            obs,
        )
        self.assertEqual([step["target_label"] for step in steps], ["username", "password", "login"])
        self.assertEqual(render_action(steps[0]), "fill('16', 'cierra')")
        self.assertEqual(render_action(steps[2]), "click('20')")

    def test_build_use_autocomplete_marks_autocomplete_fill(self):
        obs = make_obs([ax_node("18", "button", "Submit")])
        steps = build_use_autocomplete('Enter an item that starts with "Com".', obs)
        self.assertTrue(steps[0]["enable_autocomplete"])
        self.assertEqual(render_action(steps[0]), "fill('17', 'Com', True)")
        self.assertEqual(render_action(steps[2]), "click('18')")

    def test_build_click_button_sequence_uses_button_names(self):
        obs = make_obs(
            [
                ax_node("12", "button", "ONE"),
                ax_node("13", "button", "TWO"),
            ]
        )
        steps = build_click_button_sequence("Click button ONE, then click button TWO.", obs)
        self.assertEqual([render_action(step) for step in steps], ["click('12')", "click('13')"])

    def test_build_form_sequence_3_parses_dropdown_and_button(self):
        obs = make_obs(
            [
                ax_node("19", "combobox", ""),
                ax_node("43", "button", "No"),
            ]
        )
        steps = build_form_sequence_3(
            'Choose 5ft 10in from the dropdown, then click the button labeled "No".',
            obs,
        )
        self.assertEqual(render_action(steps[0]), "select_option('19', '5ft 10in')")
        self.assertEqual(render_action(steps[1]), "click('43')")

    def test_build_form_sequence_2_uses_requested_radio_and_textbox(self):
        obs = make_obs([ax_node("24", "button", "Submit")])
        steps = build_form_sequence_2(
            'Check the 3rd radio button and enter the number "44" into the 2nd textbox.',
            obs,
        )
        self.assertEqual(render_action(steps[0]), "click('18')")
        self.assertEqual(render_action(steps[1]), "fill('21', '44')")
        self.assertEqual(render_action(steps[2]), "click('24')")

    def test_bind_macro_steps_resolves_binding_ids(self):
        macro = {
            "step_templates": [
                {"kind": "fill", "bid": "16", "target_role": "textbox", "target_label": "username", "binding_id": "B01"},
                {"kind": "click", "bid": "20", "target_role": "button", "target_label": "login"},
            ]
        }
        bound = bind_macro_steps(macro, {"B01": "cierra"})
        self.assertEqual(bound[0]["value"], "cierra")
        self.assertNotIn("binding_id", bound[0])
        self.assertEqual(macro_action_string(macro, {"B01": "cierra"}), "fill('16', 'cierra')\nclick('20')")

    def test_bind_macro_steps_requires_binding_value(self):
        macro = {"step_templates": [{"kind": "fill", "bid": "16", "binding_id": "B01"}]}
        with self.assertRaises(KeyError):
            bind_macro_steps(macro, {})

    def test_choose_macro_prefers_longer_high_precision_match(self):
        macros = [
            {"macro_id": "m1", "sequence": ["A", "B"], "replay_precision": 0.7, "support": 4, "trigger_prefix_len": 1},
            {"macro_id": "m2", "sequence": ["A", "B", "C"], "replay_precision": 0.7, "support": 3, "trigger_prefix_len": 2},
        ]
        chosen = choose_macro(["A", "B", "C"], macros, policy_mode="oracle_exact", min_replay_precision=0.5)
        self.assertEqual(chosen["macro_id"], "m2")

    def test_choose_macro_uses_trigger_prefix_mode(self):
        macros = [
            {"macro_id": "m1", "sequence": ["A", "B", "C"], "replay_precision": 0.8, "support": 3, "trigger_prefix_len": 2}
        ]
        chosen = choose_macro(["A", "B", "X"], macros, policy_mode="trigger_prefix", min_replay_precision=0.5)
        self.assertEqual(chosen["macro_id"], "m1")

    def test_choose_macro_skips_blocked_macro_ids(self):
        macros = [
            {"macro_id": "m1", "sequence": ["A", "B"], "replay_precision": 0.8, "support": 3, "trigger_prefix_len": 1},
            {"macro_id": "m2", "sequence": ["A", "C"], "replay_precision": 0.7, "support": 2, "trigger_prefix_len": 1},
        ]
        chosen = choose_macro(
            ["A", "B"],
            macros,
            policy_mode="trigger_prefix",
            min_replay_precision=0.5,
            blocked_macro_ids=["m1"],
        )
        self.assertEqual(chosen["macro_id"], "m2")

    def test_representative_templates_for_macro_finds_matching_episode_slice(self):
        represented_rows = {
            "episode_1": [
                {
                    "canonical_action": "TYPE user use=B01",
                    "action_name": "fill",
                    "selector": "16",
                    "target_role": "textbox",
                    "target_label": "username",
                    "binding_uses": ["B01"],
                },
                {
                    "canonical_action": "CLICK login",
                    "action_name": "click",
                    "selector": "20",
                    "target_role": "button",
                    "target_label": "login",
                },
            ]
        }
        macro = {"sequence": ["TYPE user use=B01", "CLICK login"]}
        templates = representative_templates_for_macro(represented_rows, macro)
        self.assertEqual(templates[0]["binding_id"], "B01")
        self.assertEqual(templates[1]["kind"], "click")

    def test_semantic_macro_name_and_description_are_readable(self):
        macro = {"sequence": ["FILL|role=input|label=password|use=B01", "CLICK|role=button|label=login"]}
        name = semantic_macro_name("login_user", macro, 1)
        description = semantic_macro_description("login_user", macro)
        self.assertIn("login_user", name)
        self.assertIn("password", name)
        self.assertIn("username and password", description)

    def test_primitive_action_metadata_is_readable(self):
        step = {"kind": "fill", "bid": "16", "target_role": "textbox", "target_label": "password"}
        self.assertIn("password", primitive_action_name(step, 0))
        self.assertIn("password", primitive_action_description(step))

    def test_observation_text_collects_goal_and_ax_names(self):
        obs = {
            "goal": 'Enter the password "11L" and submit.',
            "axtree_object": {"nodes": [ax_node("20", "button", "Submit"), ax_node("16", "textbox", "Password")]},
        }
        text = observation_text(obs)
        self.assertIn("submit", text.lower())
        self.assertIn("password", text.lower())

    def test_semantic_choice_prefers_matching_macro(self):
        obs = {"goal": 'Enter the username "alice" and password "pw" and press login.', "axtree_object": {"nodes": [ax_node("20", "button", "Login")]}}
        primitive = {"kind": "fill", "bid": "16", "target_role": "textbox", "target_label": "username"}
        macro = {
            "macro_id": "M1",
            "suggested_name": "login_user_fill_username_then_fill_password_then_click_login_m001",
            "suggested_description": "Fill the username and password fields, then click login.",
            "sequence": ["FILL|role=input|label=<TEXT>|use=B01", "FILL|role=input|label=password|use=B02", "CLICK|role=button|label=login"],
            "step_templates": [
                {"kind": "fill", "target_role": "textbox", "target_label": "username"},
                {"kind": "fill", "target_role": "textbox", "target_label": "password"},
                {"kind": "click", "target_role": "button", "target_label": "login"},
            ],
        }
        choice = semantic_choice(goal=obs["goal"], obs=obs, primitive_step=primitive, primitive_index=0, macros=[macro], blocked_macro_ids=[], margin=0.0)
        self.assertEqual(choice["kind"], "macro")

    def test_semantic_choice_guard_blocks_late_macro_fire(self):
        obs = {"goal": 'Enter the username "alice" and password "pw" and press login.', "axtree_object": {"nodes": [ax_node("20", "button", "Login")]}}
        primitive = {"kind": "click", "bid": "20", "target_role": "button", "target_label": "login"}
        macro = {
            "macro_id": "M1",
            "suggested_name": "login_user_fill_username_then_fill_password_then_click_login_m001",
            "suggested_description": "Fill the username and password fields, then click login.",
            "sequence": ["FILL|role=input|label=<TEXT>|use=B01", "FILL|role=input|label=password|use=B02", "CLICK|role=button|label=login"],
            "step_templates": [
                {"kind": "fill", "target_role": "textbox", "target_label": "username"},
                {"kind": "fill", "target_role": "textbox", "target_label": "password"},
                {"kind": "click", "target_role": "button", "target_label": "login"},
            ],
        }
        guarded = semantic_choice(goal=obs["goal"], obs=obs, primitive_step=primitive, primitive_index=2, macros=[macro], blocked_macro_ids=[], margin=0.0)
        unguarded = semantic_choice(
            goal=obs["goal"],
            obs=obs,
            primitive_step=primitive,
            primitive_index=2,
            macros=[macro],
            blocked_macro_ids=[],
            margin=0.0,
            use_start_step_guard=False,
        )
        self.assertEqual(guarded["kind"], "primitive")
        self.assertEqual(unguarded["kind"], "macro")

    def test_semantic_choice_guard_uses_label_specificity(self):
        obs = {"goal": 'Enter the text "hello" and submit.', "axtree_object": {"nodes": [ax_node("14", "textbox", "Text")]}}
        primitive = {"kind": "fill", "bid": "14", "target_role": "textbox", "target_label": "text"}
        password_macro = {
            "macro_id": "M1",
            "suggested_name": "enter_password_fill_password_then_click_submit_m001",
            "suggested_description": "Fill the password field, then click submit.",
            "sequence": ["FILL|role=input|label=password|use=B01", "CLICK|role=button|label=submit"],
            "step_templates": [
                {"kind": "fill", "target_role": "textbox", "target_label": "password"},
                {"kind": "click", "target_role": "button", "target_label": "submit"},
            ],
        }
        choice = semantic_choice(goal=obs["goal"], obs=obs, primitive_step=primitive, primitive_index=0, macros=[password_macro], blocked_macro_ids=[], margin=0.0)
        self.assertEqual(choice["kind"], "primitive")


if __name__ == "__main__":
    unittest.main()
