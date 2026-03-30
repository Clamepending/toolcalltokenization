#!/usr/bin/env python3

from __future__ import annotations

import argparse
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bucketed macro registry store from accumulated traces.")
    parser.add_argument("--input", required=True, help="Canonical JSONL trace file.")
    parser.add_argument("--output", required=True, help="Path to JSON macro-store output.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Recorded canonicalization mode.")
    parser.add_argument("--bucket-scope", default="website_task_family", choices=("website_task_family", "website"), help="Primary bucket scope for promoted macros.")
    parser.add_argument("--fallback-scope", default="website", choices=("website", "none"), help="Optional fallback scope to build alongside exact buckets.")
    parser.add_argument("--support-policy", default="loose", choices=("loose", "strict", "adaptive"), help="Support threshold policy.")
    parser.add_argument("--shadow-min-episodes", type=int, default=4, help="Minimum bucket size for shadow evaluation.")
    parser.add_argument("--live-min-episodes", type=int, default=6, help="Minimum bucket size before enabling live macro exposure.")
    parser.add_argument("--rebuild-every-new-episodes", type=int, default=2, help="Recommended number of fresh successful episodes before rebuilding a bucket.")
    parser.add_argument("--min-live-reduction", type=float, default=0.1, help="Minimum shadow decision reduction ratio before a bucket is marked live-ready.")
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
    return parser.parse_args()


def build_scope(
    grouped_sequences: dict[str, dict[str, list[str]]],
    *,
    scope: str,
    args: argparse.Namespace,
) -> list[dict]:
    buckets = []
    for group_key, sequences in sorted(grouped_sequences.items()):
        total_episodes = len(sequences)
        if total_episodes < args.shadow_min_episodes:
            continue
        train_pool, eval_sequences = fixed_holdout_split(
            sequences,
            eval_ratio=args.eval_ratio,
            min_eval_episodes=args.min_eval_episodes,
        )
        support = support_threshold(len(train_pool), args.support_policy)
        study = promote_macros_for_group(
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
        )
        summary = study["savings"]["summary"]
        registry = study["registry"]
        live_ready = (
            total_episodes >= args.live_min_episodes
            and bool(registry)
            and float(summary["decision_reduction_ratio"]) >= args.min_live_reduction
        )
        buckets.append(
            {
                "bucket_key": group_key,
                "scope": scope,
                "site": split_group_key(group_key)[0],
                "task_family": split_group_key(group_key)[1],
                "cohort": cohort_for_group_key(group_key),
                "episodes_total": total_episodes,
                "shadow_train_episodes": len(train_pool),
                "shadow_eval_episodes": len(eval_sequences),
                "support_policy": args.support_policy,
                "support_threshold": support,
                "shadow_ready": True,
                "live_ready": live_ready,
                "recommended_rebuild_every_new_episodes": args.rebuild_every_new_episodes,
                "shadow_summary": summary,
                "registry": registry,
            }
        )
    return buckets


def main() -> None:
    args = parse_args()
    primary_groups = load_grouped_sequences(args.input, args.bucket_scope)
    payload = {
        "version": 1,
        "input": args.input,
        "canonicalization_mode": args.canonicalization_mode,
        "build_policy": {
            "bucket_scope": args.bucket_scope,
            "fallback_scope": args.fallback_scope,
            "support_policy": args.support_policy,
            "shadow_min_episodes": args.shadow_min_episodes,
            "live_min_episodes": args.live_min_episodes,
            "rebuild_every_new_episodes": args.rebuild_every_new_episodes,
            "min_live_reduction": args.min_live_reduction,
            "eval_ratio": args.eval_ratio,
            "min_eval_episodes": args.min_eval_episodes,
            "top_k": args.top_k,
            "max_chunk_len": args.max_chunk_len,
            "trigger_prefix_len": args.trigger_prefix_len,
            "min_length": args.min_length,
            "max_length": args.max_length,
            "min_replay_precision": args.min_replay_precision,
            "min_exact_replays": args.min_exact_replays,
            "min_steps_saved": args.min_steps_saved,
        },
        "primary_buckets": build_scope(primary_groups, scope=args.bucket_scope, args=args),
    }
    if args.fallback_scope != "none":
        fallback_groups = load_grouped_sequences(args.input, args.fallback_scope)
        payload["fallback_buckets"] = build_scope(fallback_groups, scope=args.fallback_scope, args=args)
    else:
        payload["fallback_buckets"] = []

    payload["summary"] = {
        "primary_buckets": len(payload["primary_buckets"]),
        "primary_live_ready": sum(1 for item in payload["primary_buckets"] if item["live_ready"]),
        "primary_promoted_macros": sum(len(item["registry"]) for item in payload["primary_buckets"]),
        "fallback_buckets": len(payload["fallback_buckets"]),
        "fallback_live_ready": sum(1 for item in payload["fallback_buckets"] if item["live_ready"]),
        "fallback_promoted_macros": sum(len(item["registry"]) for item in payload["fallback_buckets"]),
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
