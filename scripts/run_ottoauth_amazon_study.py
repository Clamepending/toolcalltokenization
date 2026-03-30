#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.macro_study import (
    fixed_holdout_split,
    promote_macros_for_group,
    support_threshold,
)
from toolcalltokenization.trace_utils import (
    dump_json,
    evaluate_macro_replay,
    group_rows,
    group_sequences,
    load_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an Amazon-focused study on OttoAuth local-agent traces.")
    parser.add_argument("--input", required=True, help="Canonical JSONL trace file.")
    parser.add_argument("--output", required=True, help="Path to JSON output.")
    parser.add_argument("--website", default="amazon.com", help="Website bucket to study.")
    parser.add_argument("--heldout-episodes", type=int, default=2, help="Fixed held-out episode count per bucket.")
    parser.add_argument("--support-policy", choices=("loose", "strict", "adaptive"), default="loose")
    parser.add_argument("--top-k", type=int, default=25)
    parser.add_argument("--max-chunk-len", type=int, default=6)
    parser.add_argument("--trigger-prefix-len", type=int, default=2)
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=6)
    parser.add_argument("--min-replay-precision", type=float, default=0.5)
    parser.add_argument("--min-exact-replays", type=int, default=1)
    parser.add_argument("--min-steps-saved", type=int, default=1)
    return parser.parse_args()


def curve_for_group(group_key: str, sequences: dict[str, list[str]], args: argparse.Namespace) -> dict:
    episode_ids = sorted(sequences)
    if len(episode_ids) < 2:
        return {
            "group_key": group_key,
            "total_episodes": len(episode_ids),
            "status": "insufficient_episodes",
            "points": [],
        }

    heldout = min(args.heldout_episodes, max(1, len(episode_ids) - 1))
    train_pool, eval_sequences = fixed_holdout_split(
        sequences,
        eval_ratio=heldout / len(episode_ids),
        min_eval_episodes=heldout,
    )
    train_ids = sorted(train_pool)
    points = [
        {
            "total_episodes": heldout,
            "train_episodes": 0,
            "heldout_episodes": heldout,
            "compression_ratio": 1.0,
            "decision_reduction_ratio": 0.0,
            "promoted_macros": 0,
            "parameterized_promoted_macros": 0,
            "avg_macro_length": 0.0,
            "max_macro_length": 0,
            "trigger_precision_prefix1": 1.0,
            "trigger_precision_prefix2": 1.0,
        }
    ]
    studies = []

    for train_episodes in range(1, len(train_ids) + 1):
        train_sequences = {episode_id: list(train_pool[episode_id]) for episode_id in train_ids[:train_episodes]}
        support = support_threshold(train_episodes, args.support_policy)
        study = promote_macros_for_group(
            group_key,
            train_sequences,
            eval_sequences,
            canonicalization_mode="dataflow_coarse",
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
        )
        registry = study["registry"]
        replay_p1 = evaluate_macro_replay(registry, eval_sequences, trigger_prefix_len=1)["summary"] if registry else {"replay_precision": 1.0}
        replay_p2 = evaluate_macro_replay(registry, eval_sequences, trigger_prefix_len=2)["summary"] if registry else {"replay_precision": 1.0}
        summary = study["savings"]["summary"]
        points.append(
            {
                "total_episodes": train_episodes + heldout,
                "train_episodes": train_episodes,
                "heldout_episodes": heldout,
                "compression_ratio": summary["compression_ratio"],
                "decision_reduction_ratio": summary["decision_reduction_ratio"],
                "promoted_macros": len(registry),
                "parameterized_promoted_macros": sum(1 for item in registry if item["num_inputs"] > 0),
                "avg_macro_length": round(sum(item["length"] for item in registry) / len(registry), 4) if registry else 0.0,
                "max_macro_length": max((int(item["length"]) for item in registry), default=0),
                "trigger_precision_prefix1": replay_p1["replay_precision"],
                "trigger_precision_prefix2": replay_p2["replay_precision"],
                "steps_saved": summary["steps_saved"],
                "primitive_steps": summary["primitive_steps"],
            }
        )
        studies.append(
            {
                "train_episodes": train_episodes,
                "support_threshold": support,
                "registry": registry,
                "summary": summary,
                "episodes": study["savings"]["episodes"],
            }
        )

    best_point = min(points[1:], key=lambda item: item["compression_ratio"], default=None)
    best_study = None
    if best_point:
        best_study = next(
            (study for study in studies if study["train_episodes"] == best_point["train_episodes"]),
            None,
        )

    return {
        "group_key": group_key,
        "status": "ok",
        "total_episodes": len(episode_ids),
        "train_pool_episodes": len(train_pool),
        "heldout_episodes": heldout,
        "points": points,
        "best_point": best_point,
        "best_registry": (best_study or {}).get("registry", []),
        "best_example_episode": ((best_study or {}).get("episodes", []) or [None])[0],
    }


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    amazon_rows = [row for row in rows if str(row.get("website") or "") == args.website]
    site_sequences = group_sequences(amazon_rows)
    family_groups = group_rows(amazon_rows, "website_task_family")

    curves = {
        args.website: curve_for_group(args.website, site_sequences, args),
    }
    for family_key, family_rows in sorted(family_groups.items()):
        curves[family_key] = curve_for_group(family_key, group_sequences(family_rows), args)

    payload = {
        "input": args.input,
        "website": args.website,
        "episodes": len(site_sequences),
        "event_count": len(amazon_rows),
        "support_policy": args.support_policy,
        "heldout_episodes": args.heldout_episodes,
        "curves": curves,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
