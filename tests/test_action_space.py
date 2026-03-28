import unittest

from toolcalltokenization.action_space import (
    PRIMITIVE_ACTIONS,
    build_action_space,
    macro_action_spec,
)


class ActionSpaceTest(unittest.TestCase):
    def test_macro_action_spec_uses_registry_fields(self) -> None:
        action = macro_action_spec(
            {
                "registry_id": "R001",
                "macro_id": "M003",
                "suggested_name": "newegg_search_m003",
                "suggested_description": "Search macro for newegg.",
                "group_key": "newegg::search",
                "sequence": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button"],
                "input_bindings": ["B01"],
                "support": 7,
                "occurrences": 7,
                "replay_precision": 1.0,
                "eval_steps_saved": 2,
                "num_inputs": 1,
            }
        )
        self.assertEqual(action["name"], "newegg_search_m003")
        self.assertEqual(action["parameters"][0]["binding_id"], "B01")
        self.assertEqual(action["metadata"]["support"], 7)

    def test_build_action_space_combines_primitives_and_macros(self) -> None:
        payload = build_action_space(
            {
                "registry": [
                    {
                        "registry_id": "R001",
                        "macro_id": "M003",
                        "suggested_name": "newegg_search_m003",
                        "suggested_description": "Search macro for newegg.",
                        "group_key": "newegg::search",
                        "sequence": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button"],
                        "input_bindings": ["B01"],
                        "support": 7,
                        "occurrences": 7,
                        "replay_precision": 1.0,
                        "eval_steps_saved": 2,
                        "num_inputs": 1,
                    }
                ]
            }
        )
        self.assertEqual(payload["summary"]["primitive_actions"], len(PRIMITIVE_ACTIONS))
        self.assertEqual(payload["summary"]["macro_actions"], 1)
        self.assertEqual(payload["summary"]["total_actions"], len(PRIMITIVE_ACTIONS) + 1)


if __name__ == "__main__":
    unittest.main()
