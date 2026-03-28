from collections import Counter
import unittest

from toolcalltokenization.trace_utils import (
    apply_bpe_tokens,
    apply_macros,
    CANONICALIZATION_MODES,
    canonicalize_event,
    compress_sequence,
    evaluate_macro_replay,
    evaluate_next_token_cache,
    group_rows,
    infer_task_family,
    macro_has_binding,
    mine_frequent_chunks,
    represent_rows,
    split_sequences,
    summarize_macro_savings,
    train_bpe_tokens,
)


class TraceUtilsTest(unittest.TestCase):
    def test_canonicalization_modes_are_explicit(self) -> None:
        self.assertEqual(
            CANONICALIZATION_MODES,
            (
                "name_only",
                "value_slots",
                "coarse_signature",
                "target_signature",
                "signature",
                "dataflow",
                "dataflow_coarse",
            ),
        )

    def test_canonicalize_type_uses_slot(self) -> None:
        event = canonicalize_event(
            {
                "action_type": "type",
                "target_role": "input",
                "target_label": "Search",
                "value": "cheap flights to seattle",
                "slot": "search_term",
            }
        )
        self.assertEqual(
            event["canonical_action"],
            "TYPE|role=input|label=search|value=<SEARCH_TERM>",
        )

    def test_canonicalize_name_only_drops_args(self) -> None:
        event = canonicalize_event(
            {
                "action_type": "type",
                "target_role": "input",
                "target_label": "Search",
                "value": "cheap flights to seattle",
            },
            mode="name_only",
        )
        self.assertEqual(event["canonical_action"], "TYPE")

    def test_canonicalize_value_slots_keeps_slot_but_not_target(self) -> None:
        event = canonicalize_event(
            {
                "action_type": "type",
                "target_role": "input",
                "target_label": "Search",
                "value": "cheap flights to seattle",
                "slot": "search_term",
            },
            mode="value_slots",
        )
        self.assertEqual(event["canonical_action"], "TYPE|value=<SEARCH_TERM>")

    def test_canonicalize_target_signature_keeps_target_but_not_value(self) -> None:
        event = canonicalize_event(
            {
                "action_type": "type",
                "target_role": "input",
                "target_label": "Search",
                "value": "cheap flights to seattle",
            },
            mode="target_signature",
        )
        self.assertEqual(event["canonical_action"], "TYPE|role=input|label=search")

    def test_canonicalize_coarse_signature_coarsens_target(self) -> None:
        event = canonicalize_event(
            {
                "action_type": "click",
                "target_role": "button",
                "target_label": "Search for flights to Seattle",
            },
            mode="coarse_signature",
        )
        self.assertEqual(event["canonical_action"], "CLICK|role=button|label=search")

    def test_canonicalize_infers_slot_from_label(self) -> None:
        event = canonicalize_event(
            {
                "action_type": "type",
                "target_role": "input",
                "target_label": "Email",
                "value": "person@example.com",
            }
        )
        self.assertEqual(
            event["canonical_action"],
            "TYPE|role=input|label=email|value=<EMAIL>",
        )

    def test_infer_task_family_prefers_specific_workflow(self) -> None:
        family = infer_task_family("Find flights from Chicago to London and return on April 23.")
        self.assertEqual(family, "flight")

    def test_group_rows_supports_website_task_family(self) -> None:
        grouped = group_rows(
            [
                {"episode_id": "a", "website": "amazon", "task": "Add this item to my cart"},
                {"episode_id": "b", "website": "amazon", "task": "Add another item to my cart"},
                {"episode_id": "c", "website": "amazon", "task": "Find a laptop"},
            ],
            "website_task_family",
        )
        self.assertEqual(sorted(grouped), ["amazon::cart", "amazon::search"])
        self.assertEqual(len(grouped["amazon::cart"]), 2)

    def test_dataflow_mode_alpha_renames_episode_inputs(self) -> None:
        rows = represent_rows(
            [
                {
                    "episode_id": "a",
                    "step_index": 0,
                    "action_type": "type",
                    "target_role": "input",
                    "target_label": "Email",
                    "value": "alice@example.com",
                },
                {
                    "episode_id": "a",
                    "step_index": 1,
                    "action_type": "type",
                    "target_role": "input",
                    "target_label": "Password",
                    "value": "secret-a",
                },
                {
                    "episode_id": "b",
                    "step_index": 0,
                    "action_type": "type",
                    "target_role": "input",
                    "target_label": "Email",
                    "value": "bob@example.com",
                },
                {
                    "episode_id": "b",
                    "step_index": 1,
                    "action_type": "type",
                    "target_role": "input",
                    "target_label": "Password",
                    "value": "secret-b",
                },
            ],
            mode="dataflow_coarse",
        )
        canonical_actions = [row["canonical_action"] for row in rows]
        self.assertEqual(
            canonical_actions,
            [
                "TYPE|role=input|label=email|use=B01",
                "TYPE|role=input|label=password|use=B02",
                "TYPE|role=input|label=email|use=B01",
                "TYPE|role=input|label=password|use=B02",
            ],
        )

    def test_dataflow_mode_tracks_copy_paste_binding(self) -> None:
        rows = represent_rows(
            [
                {
                    "episode_id": "copy-demo",
                    "step_index": 0,
                    "action_type": "copy",
                    "target_role": "p",
                    "target_label": "Order number 12345",
                },
                {
                    "episode_id": "copy-demo",
                    "step_index": 1,
                    "action_type": "paste",
                    "target_role": "textarea",
                    "target_label": "Message",
                    "value": "Order number 12345",
                },
            ],
            mode="dataflow_coarse",
        )
        self.assertEqual(rows[0]["binding_defs"], ["B01"])
        self.assertEqual(rows[1]["binding_uses"], ["B01"])
        self.assertEqual(rows[0]["canonical_action"], "COPY|role=text|label=<TEXT>|def=B01")
        self.assertEqual(rows[1]["canonical_action"], "PASTE|role=input|label=<TEXT>|use=B01")

    def test_macro_has_binding(self) -> None:
        self.assertTrue(macro_has_binding({"sequence": ["TYPE|use=B01", "CLICK"]}))
        self.assertFalse(macro_has_binding({"sequence": ["CLICK", "CLICK"]}))

    def test_frequent_chunk_is_mined(self) -> None:
        sequences = {
            "a": ["CLICK|label=search", "TYPE|value=<TEXT>", "CLICK|label=search"],
            "b": ["CLICK|label=search", "TYPE|value=<TEXT>", "CLICK|label=search"],
        }
        macros = mine_frequent_chunks(sequences, min_support=2, max_chunk_len=3, top_k=10)
        self.assertEqual(
            macros[0]["sequence"],
            ["CLICK|label=search", "TYPE|value=<TEXT>", "CLICK|label=search"],
        )

    def test_compress_sequence_prefers_longest_macro(self) -> None:
        macros = [
            {"macro_id": "M001", "sequence": ["A", "B", "C"], "support": 3},
            {"macro_id": "M002", "sequence": ["A", "B"], "support": 4},
        ]
        compressed, hits = compress_sequence(["A", "B", "C", "D"], macros)
        self.assertEqual(compressed, ["MACRO:M001", "D"])
        self.assertEqual(hits, Counter({"M001": 1}))

    def test_bpe_merges_repeated_pair(self) -> None:
        sequences = {
            "a": ["A", "B", "C"],
            "b": ["A", "B", "D"],
            "c": ["A", "B", "E"],
        }
        merges = train_bpe_tokens(sequences, num_merges=2, min_occurrences=2)
        self.assertEqual(merges[0]["sequence"], ["A", "B"])

        compressed = apply_bpe_tokens(sequences, merges)
        self.assertEqual(compressed["a"][0], "BPE001")

    def test_bpe_requires_cross_episode_support(self) -> None:
        sequences = {
            "a": ["X", "Y", "X", "Y"],
            "b": ["A", "B"],
        }
        merges = train_bpe_tokens(sequences, num_merges=2, min_occurrences=2, min_support=2)
        self.assertEqual(merges, [])

    def test_split_sequences_reserves_holdout(self) -> None:
        sequences = {
            "a": ["A", "B"],
            "b": ["A", "C"],
            "c": ["A", "D"],
        }
        train, test = split_sequences(sequences, train_ratio=0.67, seed=0)
        self.assertTrue(train)
        self.assertTrue(test)
        self.assertEqual(len(train) + len(test), 3)

    def test_next_token_cache_evaluation(self) -> None:
        train = {"train": ["A", "B", "C", "D"]}
        test = {"test": ["A", "B", "C", "X"]}
        summary = evaluate_next_token_cache(train, test, context_len=2)
        self.assertEqual(summary["covered_positions"], 2)
        self.assertEqual(summary["correct_positions"], 1)

    def test_apply_macros(self) -> None:
        sequences = {"a": ["A", "B", "C"]}
        macros = [{"macro_id": "M001", "sequence": ["A", "B"], "support": 2}]
        compressed = apply_macros(sequences, macros)
        self.assertEqual(compressed["a"], ["MACRO:M001", "C"])

    def test_summarize_macro_savings(self) -> None:
        sequences = {
            "a": ["TYPE|use=B01", "CLICK", "TYPE|use=B02", "CLICK"],
            "b": ["TYPE|use=B01", "CLICK", "TYPE|use=B02", "CLICK"],
        }
        macros = [
            {
                "macro_id": "M001",
                "sequence": ["TYPE|use=B01", "CLICK"],
                "support": 2,
                "occurrences": 2,
            }
        ]
        summary = summarize_macro_savings(sequences, macros, decision_tokens_per_step=10, decision_latency_ms=100)
        self.assertEqual(summary["summary"]["steps_saved"], 2)
        self.assertEqual(summary["summary"]["parameterized_macro_calls"], 2)
        self.assertEqual(summary["summary"]["estimated_output_tokens_saved"], 20)

    def test_evaluate_macro_replay(self) -> None:
        eval_sequences = {
            "a": ["TYPE|use=B01", "CLICK", "TYPE|use=B02", "CLICK"],
            "b": ["TYPE|use=B01", "CLICK", "SCROLL"],
        }
        macros = [
            {
                "macro_id": "M001",
                "sequence": ["TYPE|use=B01", "CLICK"],
                "support": 2,
                "occurrences": 2,
            },
            {
                "macro_id": "M002",
                "sequence": ["TYPE|use=B02", "CLICK"],
                "support": 1,
                "occurrences": 1,
            },
        ]
        replay = evaluate_macro_replay(macros, eval_sequences, trigger_prefix_len=1)
        self.assertEqual(replay["summary"]["candidate_triggers"], 3)
        self.assertEqual(replay["summary"]["exact_replays"], 3)
        self.assertEqual(replay["summary"]["parameterized_replay_precision"], 1.0)


if __name__ == "__main__":
    unittest.main()
