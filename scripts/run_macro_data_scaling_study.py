#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.macro_study import (
    cohort_for_group_key,
    fixed_holdout_split,
    load_grouped_sequences,
    promote_macros_for_group,
    split_group_key,
    support_threshold,
)
from toolcalltokenization.trace_utils import dump_json


DEFAULT_REPRESENTATIVE_GROUPS = [
    "amazon",
    "amazon::cart",
    "newegg::search",
    "uniqlo::cart",
    "united::flight",
    "yelp::search",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a data-scaling study for browser-action macros.")
    parser.add_argument("--input", required=True, help="Canonical JSONL trace file.")
    parser.add_argument("--output", required=True, help="Path to JSON study output.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Recorded canonicalization mode.")
    parser.add_argument("--top-k", type=int, default=25, help="Maximum mined macros per bucket.")
    parser.add_argument("--max-chunk-len", type=int, default=6, help="Longest chunk length to consider.")
    parser.add_argument("--trigger-prefix-len", type=int, default=2, help="Trigger prefix length for replay gating.")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum macro length required for promotion.")
    parser.add_argument("--max-length", type=int, default=6, help="Maximum macro length required for promotion.")
    parser.add_argument("--min-replay-precision", type=float, default=0.5, help="Minimum held-out replay precision required for promotion.")
    parser.add_argument("--min-exact-replays", type=int, default=1, help="Minimum exact held-out replays required for promotion.")
    parser.add_argument("--min-steps-saved", type=int, default=1, help="Minimum held-out steps saved required for promotion.")
    parser.add_argument("--eval-ratio", type=float, default=0.2, help="Held-out suffix ratio.")
    parser.add_argument("--min-eval-episodes", type=int, default=2, help="Minimum held-out episodes per bucket.")
    parser.add_argument("--min-total-episodes", type=int, default=6, help="Minimum total episodes for site/family aggregation.")
    parser.add_argument(
        "--support-policy",
        action="append",
        choices=("loose", "strict", "adaptive"),
        help="Support threshold policy to evaluate. Defaults to loose, strict, and adaptive.",
    )
    parser.add_argument(
        "--representative-group",
        action="append",
        help="Representative site or site::family bucket to report explicitly. Can be provided multiple times.",
    )
    return parser.parse_args()


def choose_group_sequences(
    group_key: str,
    site_groups: dict[str, dict[str, list[str]]],
    site_family_groups: dict[str, dict[str, list[str]]],
) -> tuple[str, dict[str, list[str]]] | None:
    if "::" in group_key:
        sequences = site_family_groups.get(group_key)
        if sequences is None:
            return None
        return "website_task_family", sequences
    sequences = site_groups.get(group_key)
    if sequences is None:
        return None
    return "website", sequences


def summarize_curve(points: list[dict]) -> dict:
    if not points:
        return {"max_weighted_ratio": 0.0, "episodes_to_80pct_of_peak": None, "peak_train_episodes": None}
    peak_point = max(points, key=lambda item: (item["weighted_decision_reduction_ratio"], item["train_episodes"]))
    peak_ratio = float(peak_point["weighted_decision_reduction_ratio"])
    threshold = peak_ratio * 0.8
    first_cross = next(
        (item["train_episodes"] for item in points if float(item["weighted_decision_reduction_ratio"]) >= threshold),
        None,
    )
    return {
        "max_weighted_ratio": round(peak_ratio, 4),
        "episodes_to_80pct_of_peak": first_cross,
        "peak_train_episodes": int(peak_point["train_episodes"]),
    }


def representative_group_curve(
    group_key: str,
    sequences: dict[str, list[str]],
    args: argparse.Namespace,
    support_policies: list[str],
) -> dict:
    train_pool, eval_sequences = fixed_holdout_split(
        sequences,
        eval_ratio=args.eval_ratio,
        min_eval_episodes=args.min_eval_episodes,
    )
    episode_ids = sorted(train_pool)
    curves = {}

    for policy in support_policies:
        points = []
        for train_episodes in range(2, len(episode_ids) + 1):
            train_sequences = {episode_id: train_pool[episode_id] for episode_id in episode_ids[:train_episodes]}
            support = support_threshold(train_episodes, policy)
            study = promote_macros_for_group(
                group_key,
                train_sequences,
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
            )
            summary = study["savings"]["summary"]
            registry = study["registry"]
            points.append(
                {
                    "train_episodes": train_episodes,
                    "support_threshold": support,
                    "promoted_macros": len(registry),
                    "parameterized_promoted_macros": sum(1 for item in registry if item["num_inputs"] > 0),
                    "avg_macro_length": round(sum(item["length"] for item in registry) / len(registry), 4) if registry else 0.0,
                    "decision_reduction_ratio": summary["decision_reduction_ratio"],
                    "steps_saved": summary["steps_saved"],
                    "primitive_steps": summary["primitive_steps"],
                }
            )
        curves[policy] = {
            "points": points,
            "summary": summarize_curve(
                [
                    {
                        "train_episodes": item["train_episodes"],
                        "weighted_decision_reduction_ratio": item["decision_reduction_ratio"],
                    }
                    for item in points
                ]
            ),
        }

    return {
        "group_key": group_key,
        "scope": "website" if "::" not in group_key else "website_task_family",
        "cohort": cohort_for_group_key(group_key),
        "site": split_group_key(group_key)[0],
        "task_family": split_group_key(group_key)[1],
        "total_episodes": len(sequences),
        "train_pool_episodes": len(train_pool),
        "eval_episodes": len(eval_sequences),
        "curves": curves,
    }


def category_curves(
    site_family_groups: dict[str, dict[str, list[str]]],
    args: argparse.Namespace,
    support_policies: list[str],
) -> dict:
    eligible = {
        group_key: sequences
        for group_key, sequences in site_family_groups.items()
        if len(sequences) >= args.min_total_episodes and cohort_for_group_key(group_key) != "other"
    }

    categories: dict[str, dict] = {}
    cohort_names = sorted({cohort_for_group_key(group_key) for group_key in eligible})
    for cohort_name in cohort_names:
        category_entry = {"groups": sorted(group_key for group_key in eligible if cohort_for_group_key(group_key) == cohort_name), "curves": {}}
        for policy in support_policies:
            per_train = {}
            for group_key, sequences in eligible.items():
                if cohort_for_group_key(group_key) != cohort_name:
                    continue
                train_pool, eval_sequences = fixed_holdout_split(
                    sequences,
                    eval_ratio=args.eval_ratio,
                    min_eval_episodes=args.min_eval_episodes,
                )
                episode_ids = sorted(train_pool)
                for train_episodes in range(2, len(episode_ids) + 1):
                    train_sequences = {episode_id: train_pool[episode_id] for episode_id in episode_ids[:train_episodes]}
                    support = support_threshold(train_episodes, policy)
                    study = promote_macros_for_group(
                        group_key,
                        train_sequences,
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
                    )
                    summary = study["savings"]["summary"]
                    per_train.setdefault(train_episodes, []).append(
                        {
                            "decision_reduction_ratio": summary["decision_reduction_ratio"],
                            "steps_saved": summary["steps_saved"],
                            "primitive_steps": summary["primitive_steps"],
                            "promoted_macros": len(study["registry"]),
                        }
                    )

            points = []
            for train_episodes in sorted(per_train):
                items = per_train[train_episodes]
                primitive_steps = sum(item["primitive_steps"] for item in items)
                steps_saved = sum(item["steps_saved"] for item in items)
                weighted_ratio = round(steps_saved / primitive_steps, 4) if primitive_steps else 0.0
                points.append(
                    {
                        "train_episodes": train_episodes,
                        "groups_evaluated": len(items),
                        "groups_with_macros": sum(1 for item in items if item["promoted_macros"] > 0),
                        "mean_decision_reduction_ratio": round(sum(item["decision_reduction_ratio"] for item in items) / len(items), 4),
                        "weighted_decision_reduction_ratio": weighted_ratio,
                        "mean_promoted_macros": round(sum(item["promoted_macros"] for item in items) / len(items), 4),
                    }
                )
            category_entry["curves"][policy] = {
                "points": points,
                "summary": summarize_curve(points),
            }
        categories[cohort_name] = category_entry

    return categories


def recommendation_summary(category_data: dict) -> dict:
    recommendations = {}
    for cohort_name, cohort_entry in category_data.items():
        loose_points = cohort_entry["curves"].get("loose", {}).get("points", [])
        if not loose_points:
            continue
        first_ten = next((item["train_episodes"] for item in loose_points if item["weighted_decision_reduction_ratio"] >= 0.1), None)
        first_fifteen = next((item["train_episodes"] for item in loose_points if item["weighted_decision_reduction_ratio"] >= 0.15), None)
        recommendations[cohort_name] = {
            "episodes_to_reach_10pct_weighted_reduction": first_ten,
            "episodes_to_reach_15pct_weighted_reduction": first_fifteen,
            **cohort_entry["curves"]["loose"]["summary"],
        }
    return recommendations


def main() -> None:
    args = parse_args()
    support_policies = args.support_policy or ["loose", "strict", "adaptive"]
    representative = args.representative_group or list(DEFAULT_REPRESENTATIVE_GROUPS)

    site_groups = load_grouped_sequences(args.input, "website")
    site_family_groups = load_grouped_sequences(args.input, "website_task_family")

    representative_curves = {}
    missing_representatives = []
    for group_key in representative:
        item = choose_group_sequences(group_key, site_groups, site_family_groups)
        if item is None:
            missing_representatives.append(group_key)
            continue
        _, sequences = item
        representative_curves[group_key] = representative_group_curve(group_key, sequences, args, support_policies)

    categories = category_curves(site_family_groups, args, support_policies)
    recommendations = recommendation_summary(categories)

    payload = {
        "input": args.input,
        "canonicalization_mode": args.canonicalization_mode,
        "support_policies": support_policies,
        "min_total_episodes": args.min_total_episodes,
        "eval_ratio": args.eval_ratio,
        "min_eval_episodes": args.min_eval_episodes,
        "promotion_thresholds": {
            "top_k": args.top_k,
            "max_chunk_len": args.max_chunk_len,
            "trigger_prefix_len": args.trigger_prefix_len,
            "min_length": args.min_length,
            "max_length": args.max_length,
            "min_replay_precision": args.min_replay_precision,
            "min_exact_replays": args.min_exact_replays,
            "min_steps_saved": args.min_steps_saved,
        },
        "representative_curves": representative_curves,
        "missing_representatives": missing_representatives,
        "category_curves": categories,
        "recommendations": recommendations,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
