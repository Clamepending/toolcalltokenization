from __future__ import annotations

import unittest

from toolcalltokenization.trace_utils import mine_pair_merge_macros


class PairMergeBaselineTest(unittest.TestCase):
    def test_mine_pair_merge_macros_builds_longer_candidates(self) -> None:
        sequences = {
            "ep1": ["A", "B", "C", "D"],
            "ep2": ["A", "B", "C", "E"],
            "ep3": ["A", "B", "C", "F"],
        }
        macros = mine_pair_merge_macros(
            sequences,
            num_merges=5,
            min_occurrences=2,
            min_support=2,
            top_k=10,
            min_length=2,
            max_length=4,
        )
        sequences_found = {tuple(item["sequence"]) for item in macros}
        self.assertIn(("A", "B", "C"), sequences_found)
        self.assertIn(("B", "C"), sequences_found)
        abc = next(item for item in macros if tuple(item["sequence"]) == ("A", "B", "C"))
        self.assertEqual(abc["support"], 3)


if __name__ == "__main__":
    unittest.main()
