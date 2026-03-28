import unittest

from toolcalltokenization.macro_runtime import (
    candidate_macros,
    simulate_macro_agent,
    simulate_macro_agent_on_sequence,
)


class MacroRuntimeTest(unittest.TestCase):
    def test_candidate_macros_prefers_higher_precision(self) -> None:
        macros = [
            {
                "suggested_name": "search_short",
                "sequence": ["TYPE|use=B01", "CLICK"],
                "trigger_prefix_len": 1,
                "replay_precision": 0.6,
                "num_inputs": 1,
                "support": 4,
            },
            {
                "suggested_name": "search_long",
                "sequence": ["TYPE|use=B01", "CLICK", "CLICK"],
                "trigger_prefix_len": 1,
                "replay_precision": 0.9,
                "num_inputs": 1,
                "support": 3,
            },
        ]
        candidates = candidate_macros(["TYPE|use=B01", "CLICK", "CLICK"], 0, macros)
        self.assertEqual(candidates[0]["suggested_name"], "search_long")

    def test_simulate_macro_agent_on_sequence_counts_failure_then_fallback(self) -> None:
        summary = simulate_macro_agent_on_sequence(
            ["TYPE|use=B01", "SCROLL", "CLICK"],
            [
                {
                    "suggested_name": "search_macro",
                    "sequence": ["TYPE|use=B01", "CLICK"],
                    "trigger_prefix_len": 1,
                    "replay_precision": 0.7,
                    "num_inputs": 1,
                    "support": 3,
                }
            ],
        )
        self.assertEqual(summary["attempted_macro_calls"], 1)
        self.assertEqual(summary["failed_macro_calls"], 1)
        self.assertEqual(summary["successful_macro_calls"], 0)
        self.assertEqual(summary["agent_decisions"], 4)

    def test_simulate_macro_agent_reduces_decisions_when_macro_succeeds(self) -> None:
        report = simulate_macro_agent(
            {
                "site::search": {
                    "ep1": ["TYPE|use=B01", "CLICK", "SCROLL"],
                    "ep2": ["TYPE|use=B01", "CLICK", "CLICK"],
                }
            },
            {
                "site::search": [
                    {
                        "suggested_name": "search_macro",
                        "sequence": ["TYPE|use=B01", "CLICK"],
                        "trigger_prefix_len": 1,
                        "replay_precision": 0.7,
                        "num_inputs": 1,
                        "support": 3,
                    }
                ]
            },
        )
        self.assertEqual(report["summary"]["successful_macro_calls"], 2)
        self.assertEqual(report["summary"]["steps_saved"], 2)
        self.assertEqual(report["summary"]["groups_with_macros_available"], 1)
        self.assertEqual(report["summary"]["groups_with_successful_macro_calls"], 1)


if __name__ == "__main__":
    unittest.main()
