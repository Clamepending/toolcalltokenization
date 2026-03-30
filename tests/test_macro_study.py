import unittest

from toolcalltokenization.macro_study import (
    cohort_for_group_key,
    fixed_holdout_split,
    heuristic_macro_name,
    promote_macros_for_group,
    split_group_key,
    support_threshold,
)


class MacroStudyTests(unittest.TestCase):
    def test_split_group_key_defaults_family(self):
        self.assertEqual(split_group_key("amazon::cart"), ("amazon", "cart"))
        self.assertEqual(split_group_key("amazon"), ("amazon", "workflow"))

    def test_cohort_for_group_key_uses_site_and_family(self):
        self.assertEqual(cohort_for_group_key("amazon::cart"), "ecommerce")
        self.assertEqual(cohort_for_group_key("united::flight"), "booking_travel")
        self.assertEqual(cohort_for_group_key("yelp::search"), "search_local")

    def test_support_threshold_policies(self):
        self.assertEqual(support_threshold(1, "loose"), 1)
        self.assertEqual(support_threshold(5, "loose"), 2)
        self.assertEqual(support_threshold(5, "strict"), 3)
        self.assertEqual(support_threshold(12, "adaptive"), 3)

    def test_fixed_holdout_split_keeps_suffix_as_eval(self):
        sequences = {
            "e1": ["A"],
            "e2": ["A"],
            "e3": ["A"],
            "e4": ["A"],
            "e5": ["A"],
        }
        train, eval_sequences = fixed_holdout_split(sequences, eval_ratio=0.2, min_eval_episodes=2)
        self.assertEqual(sorted(train), ["e1", "e2", "e3"])
        self.assertEqual(sorted(eval_sequences), ["e4", "e5"])

    def test_promote_macros_for_group_returns_function_like_macro(self):
        train = {
            "ep1": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button", "CLICK|role=text"],
            "ep2": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button", "CLICK|role=text"],
            "ep3": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button", "CLICK|role=text"],
        }
        eval_sequences = {
            "ep4": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button", "CLICK|role=text"],
            "ep5": ["TYPE|role=input|label=search|use=B01", "CLICK|role=button", "CLICK|role=text"],
        }
        result = promote_macros_for_group(
            "newegg::search",
            train,
            eval_sequences,
            min_support=2,
            min_promoted_support=2,
            min_replay_precision=0.5,
            max_chunk_len=6,
        )
        self.assertEqual(len(result["registry"]), 1)
        self.assertEqual(result["savings"]["summary"]["decision_reduction_ratio"], 0.6667)
        self.assertEqual(result["registry"][0]["suggested_name"], heuristic_macro_name("newegg::search", result["discovered_macros"][0]))


if __name__ == "__main__":
    unittest.main()
