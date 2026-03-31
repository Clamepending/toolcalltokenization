from __future__ import annotations

import unittest

from toolcalltokenization.speculative_decoding import (
    TraceEpisode,
    build_prompt_completion,
    infer_task_family,
    prefix_token_match_length,
    split_episodes_holdout,
    split_train_valid_test,
)


class SpeculativeDecodingTest(unittest.TestCase):
    def test_infer_task_family(self) -> None:
        self.assertEqual(infer_task_family("search for socks and open first result"), "search")
        self.assertEqual(infer_task_family("add to cart and stop before checkout"), "cart")
        self.assertEqual(infer_task_family("go to checkout and review order"), "checkout")

    def test_split_episodes_holdout_rounds_up(self) -> None:
        episodes = [
            TraceEpisode(f"ep{i}", "amazon.com", "search", "task", ["A", "B", "C", "D", "E", "F"])
            for i in range(5)
        ]
        train, test = split_episodes_holdout(episodes, heldout_ratio=0.2, min_heldout=1)
        self.assertEqual(len(train), 4)
        self.assertEqual(len(test), 1)

    def test_split_train_valid_test(self) -> None:
        episodes = [
            TraceEpisode(f"ep{i}", "amazon.com", "search", "task", ["A", "B", "C", "D", "E", "F"])
            for i in range(10)
        ]
        train, valid, test = split_train_valid_test(episodes, heldout_ratio=0.2, valid_ratio_within_train=0.25)
        self.assertEqual(len(test), 2)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(train), 6)

    def test_build_prompt_completion(self) -> None:
        episode = TraceEpisode("ep", "amazon.com", "search", "task", ["A", "B", "C", "D", "E", "F"])
        example = build_prompt_completion(episode, prefix_ratio=0.5, min_prefix_actions=2, min_suffix_actions=2)
        self.assertEqual(example["prompt_actions"], ["A", "B", "C"])
        self.assertEqual(example["completion_actions"], ["D", "E", "F"])
        self.assertTrue(example["prompt_text"].endswith("\n"))
        self.assertTrue(example["completion_text"].endswith("\n"))

    def test_prefix_token_match_length(self) -> None:
        self.assertEqual(prefix_token_match_length([1, 2, 3], [1, 2, 9]), 2)
        self.assertEqual(prefix_token_match_length([7, 8], [1, 2]), 0)


if __name__ == "__main__":
    unittest.main()
