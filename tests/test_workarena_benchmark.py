import unittest

from toolcalltokenization.workarena_benchmark import (
    choose_target_label,
    is_machine_label,
    normalize_target_role,
    stringify_action_value,
    target_hints,
    workarena_observation_text,
    workarena_task_name,
    workarena_trace_row,
)


class WorkArenaBenchmarkTests(unittest.TestCase):
    def test_workarena_task_name(self):
        self.assertEqual(
            workarena_task_name("browsergym/workarena.servicenow.order-ipad-pro"),
            "order_ipad_pro",
        )

    def test_normalize_target_role_prefers_semantic_role(self):
        self.assertEqual(normalize_target_role({"tag": "input", "type": "text"}), "input")
        self.assertEqual(normalize_target_role({"tag": "label"}), "choice")
        self.assertEqual(normalize_target_role({"tag": "button"}), "button")

    def test_choose_target_label_uses_stable_fields_before_text_blob(self):
        meta = {
            "aria_label": "",
            "placeholder": "",
            "name": "",
            "id": "quantity",
            "value": "",
            "text": "1 2 3 4 5",
        }
        self.assertEqual(choose_target_label(meta), "quantity")

    def test_stringify_action_value_handles_multiple_shapes(self):
        self.assertEqual(stringify_action_value("abc"), "abc")
        self.assertEqual(stringify_action_value({"label": "Submit"}), "Submit")
        self.assertEqual(stringify_action_value(["a", {"value": "b"}]), "a|b")

    def test_workarena_trace_row_sets_family_fields(self):
        row = workarena_trace_row(
            task_name="order_ipad_pro",
            env_id="browsergym/workarena.servicenow.order-ipad-pro",
            seed=0,
            goal="Order an iPad.",
            task_family="service catalog",
            step_index=0,
            action_name="click",
            meta={"tag": "button", "text": "Order Now", "url": "https://example.com"},
            value="",
            step_duration_ms=123.4,
        )
        self.assertEqual(row["website"], "servicenow")
        self.assertEqual(row["task_family"], "service catalog")
        self.assertEqual(row["website_task_family"], "servicenow::service catalog")
        self.assertEqual(row["target_role"], "button")
        self.assertEqual(row["target_label"], "Order Now")

    def test_target_hints_prefers_selector_then_label_without_duplicates(self):
        row = {"selector": "IO:abc123", "target_label": "IO:abc123"}
        self.assertEqual(target_hints(row), ["IO:abc123"])

    def test_is_machine_label_detects_servicenow_ids(self):
        self.assertTrue(is_machine_label("IO:f3776ac9"))
        self.assertTrue(is_machine_label("ni.IO:abc_label"))
        self.assertFalse(is_machine_label("Order Now"))

    def test_workarena_observation_text_filters_named_interactive_nodes(self):
        obs = {
            "url": "https://example.com/catalog",
            "axtree_object": {
                "nodes": [
                    {"role": {"value": "link"}, "name": {"value": "Hardware"}},
                    {"role": {"value": "button"}, "name": {"value": "Order Now"}},
                    {"role": {"value": "generic"}, "name": {"value": "ignored"}},
                ]
            },
        }
        text = workarena_observation_text(obs, max_named_nodes=5)
        self.assertIn("https://example.com/catalog", text)
        self.assertIn("link:Hardware", text)
        self.assertIn("button:Order Now", text)
        self.assertNotIn("ignored", text)


if __name__ == "__main__":
    unittest.main()
