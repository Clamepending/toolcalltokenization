from collections import Counter
import unittest

from toolcalltokenization.trace_utils import (
    apply_bpe_tokens,
    apply_macros,
    canonicalize_event,
    compress_sequence,
    evaluate_next_token_cache,
    mine_frequent_chunks,
    split_sequences,
    train_bpe_tokens,
)


class TraceUtilsTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
