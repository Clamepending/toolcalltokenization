#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.macro_study import (
    fixed_holdout_split,
    load_grouped_sequences,
    promote_macros_for_group,
    promote_pair_merge_macros_for_group,
    support_threshold,
)
from toolcalltokenization.trace_utils import dump_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare brute-force macro mining against greedy pair-merge macros.")
    parser.add_argument("--input", required=True, help="Canonical JSONL trace file.")
    parser.add_argument("--group-by", default="website_task_family", help="Grouping key, e.g. website or website_task_family.")
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="Specific group key to evaluate. May be repeated. If omitted, evaluate top groups by episode count.",
    )
    parser.add_argument("--top-groups", type=int, default=5, help="How many groups to evaluate if --group is omitted.")
    parser.add_argument("--min-group-episodes", type=int, default=3, help="Minimum episodes required for a group.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse")
    parser.add_argument("--heldout-ratio", type=float, default=0.2)
    parser.add_argument("--min-eval-episodes", type=int, default=2)
    parser.add_argument("--support-policy", choices=("loose", "strict", "adaptive"), default="loose")
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--max-chunk-len", type=int, default=6)
    parser.add_argument("--num-merges", type=int, default=50)
    parser.add_argument("--min-occurrences", type=int, default=2)
    parser.add_argument("--trigger-prefix-len", type=int, default=2)
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=6)
    parser.add_argument("--min-replay-precision", type=float, default=0.5)
    parser.add_argument("--min-exact-replays", type=int, default=1)
    parser.add_argument("--min-steps-saved", type=int, default=1)
    parser.add_argument("--allow-generic-click-loops", action="store_true")
    parser.add_argument("--output", required=True, help="Where to write the comparison JSON.")
    return parser.parse_args()


def brief_registry(registry: list[dict], limit: int = 5) -> list[dict]:
    return [
        {
            "registry_id": item["registry_id"],
            "suggested_name": item["suggested_name"],
            "length": item["length"],
            "support": item["support"],
            "replay_precision": item["replay_precision"],
            "eval_steps_saved": item["eval_steps_saved"],
            "num_inputs": item["num_inputs"],
            "sequence": item["sequence"],
        }
        for item in registry[:limit]
    ]


def summarize_study(study: dict) -> dict:
    summary = study["savings"]["summary"]
    registry = study["registry"]
    return {
        "registry_size": len(registry),
        "decision_reduction_ratio": summary["decision_reduction_ratio"],
        "compression_ratio": summary["compression_ratio"],
        "steps_saved": summary["steps_saved"],
        "primitive_steps": summary["primitive_steps"],
        "compressed_steps": summary["compressed_steps"],
        "macro_calls": summary["macro_calls"],
        "episodes_with_macro_use": summary["episodes_with_macro_use"],
        "avg_macro_length": round(sum(item["length"] for item in registry) / len(registry), 4) if registry else 0.0,
        "max_macro_length": max((item["length"] for item in registry), default=0),
        "parameterized_registry_size": sum(1 for item in registry if item["num_inputs"] > 0),
        "top_registry": brief_registry(registry),
    }


def main() -> None:
    args = parse_args()
    grouped = load_grouped_sequences(args.input, args.group_by, canonicalization_mode=args.canonicalization_mode)
    candidates = sorted(
        ((group_key, sequences) for group_key, sequences in grouped.items() if len(sequences) >= args.min_group_episodes),
        key=lambda item: (-len(item[1]), item[0]),
    )
    if args.group:
        wanted = set(args.group)
        candidates = [(group_key, sequences) for group_key, sequences in candidates if group_key in wanted]
    else:
        candidates = candidates[: args.top_groups]

    results = []
    for group_key, sequences in candidates:
        train_pool, eval_sequences = fixed_holdout_split(
            sequences,
            eval_ratio=args.heldout_ratio,
            min_eval_episodes=args.min_eval_episodes,
        )
        support = support_threshold(len(train_pool), args.support_policy)
        brute = promote_macros_for_group(
            group_key,
            train_pool,
            eval_sequences,
            canonicalization_mode=args.canonicalization_mode,
            top_k=args.top_k,
            max_chunk_len=args.max_chunk_len,
            min_support=support,
            min_promoted_support=support,
            trigger_prefix_len=args.trigger_prefix_len,
            min_length=args.min_length,
            max_length=args.max_length,
            min_replay_precision=args.min_replay_precision,
            min_exact_replays=args.min_exact_replays,
            min_steps_saved=args.min_steps_saved,
            allow_generic_click_loops=args.allow_generic_click_loops,
        )
        pair_merge = promote_pair_merge_macros_for_group(
            group_key,
            train_pool,
            eval_sequences,
            canonicalization_mode=args.canonicalization_mode,
            top_k=args.top_k,
            num_merges=args.num_merges,
            min_occurrences=args.min_occurrences,
            min_support=support,
            min_promoted_support=support,
            trigger_prefix_len=args.trigger_prefix_len,
            min_length=args.min_length,
            max_length=args.max_length,
            min_replay_precision=args.min_replay_precision,
            min_exact_replays=args.min_exact_replays,
            min_steps_saved=args.min_steps_saved,
            allow_generic_click_loops=args.allow_generic_click_loops,
        )
        brute_summary = summarize_study(brute)
        pair_summary = summarize_study(pair_merge)
        results.append(
            {
                "group_key": group_key,
                "episode_count": len(sequences),
                "train_episode_count": len(train_pool),
                "eval_episode_count": len(eval_sequences),
                "support_threshold": support,
                "bruteforce": brute_summary,
                "pair_merge": pair_summary,
                "delta_pair_minus_bruteforce": {
                    "decision_reduction_ratio": round(
                        pair_summary["decision_reduction_ratio"] - brute_summary["decision_reduction_ratio"], 4
                    ),
                    "registry_size": pair_summary["registry_size"] - brute_summary["registry_size"],
                    "avg_macro_length": round(pair_summary["avg_macro_length"] - brute_summary["avg_macro_length"], 4),
                    "max_macro_length": pair_summary["max_macro_length"] - brute_summary["max_macro_length"],
                },
            }
        )

    payload = {
        "input": args.input,
        "group_by": args.group_by,
        "canonicalization_mode": args.canonicalization_mode,
        "heldout_ratio": args.heldout_ratio,
        "min_eval_episodes": args.min_eval_episodes,
        "support_policy": args.support_policy,
        "top_k": args.top_k,
        "max_chunk_len": args.max_chunk_len,
        "num_merges": args.num_merges,
        "min_occurrences": args.min_occurrences,
        "results": results,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
