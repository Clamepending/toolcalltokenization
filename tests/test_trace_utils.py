from collections import Counter
import unittest

from toolcalltokenization.trace_utils import canonicalize_event, compress_sequence, mine_frequent_chunks


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


if __name__ == "__main__":
    unittest.main()
