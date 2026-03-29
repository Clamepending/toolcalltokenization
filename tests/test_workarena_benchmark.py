import unittest

from toolcalltokenization.workarena_benchmark import (
    choose_target_label,
    normalize_target_role,
    stringify_action_value,
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


if __name__ == "__main__":
    unittest.main()
