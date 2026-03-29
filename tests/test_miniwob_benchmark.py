import unittest

from toolcalltokenization.miniwob_benchmark import (
    build_click_button_sequence,
    build_form_sequence_2,
    build_form_sequence_3,
    build_login_user,
    build_use_autocomplete,
    default_miniwob_url,
    render_action,
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


if __name__ == "__main__":
    unittest.main()
