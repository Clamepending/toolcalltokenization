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
    load_grouped_sequences,
    macro_is_function_like,
    promote_macros_for_group,
    support_threshold,
)
from toolcalltokenization.trace_utils import macro_interface
from toolcalltokenization.trace_utils import dump_json


DEFAULT_CASES = ["amazon", "amazon::cart", "newegg::search", "united::flight"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export before/after macro trace case studies.")
    parser.add_argument("--input", required=True, help="Canonical JSONL trace file.")
    parser.add_argument("--output", required=True, help="Path to JSON case-study output.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Recorded canonicalization mode.")
    parser.add_argument("--group", action="append", help="Site or site::family bucket to export.")
    parser.add_argument("--support-policy", choices=("loose", "strict", "adaptive"), default="loose", help="Support threshold policy.")
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


def choose_sequences(group_key: str, site_groups: dict, site_family_groups: dict) -> tuple[str, dict] | None:
    if "::" in group_key:
        sequences = site_family_groups.get(group_key)
        if sequences is None:
            return None
        return "website_task_family", sequences
    sequences = site_groups.get(group_key)
    if sequences is None:
        return None
    return "website", sequences


def candidate_reasons(
    group_key: str,
    discovered: list[dict],
    replay_by_id: dict,
    usage_by_id: dict,
    *,
    min_support: int,
    min_length: int,
    max_length: int,
    min_replay_precision: float,
    min_exact_replays: int,
    min_steps_saved: int,
) -> list[dict]:
    items = []
    for macro in discovered:
        macro_id = str(macro["macro_id"])
        replay_item = replay_by_id.get(macro_id, {})
        usage_item = usage_by_id.get(macro_id, {})
        interface = macro_interface(macro)
        reasons = []
        if macro["support"] < min_support:
            reasons.append(f"support<{min_support}")
        if len(macro["sequence"]) < min_length:
            reasons.append(f"length<{min_length}")
        if len(macro["sequence"]) > max_length:
            reasons.append(f"length>{max_length}")
        if replay_item.get("replay_precision", 0.0) < min_replay_precision:
            reasons.append(f"replay_precision<{min_replay_precision}")
        if replay_item.get("exact_replays", 0) < min_exact_replays:
            reasons.append(f"exact_replays<{min_exact_replays}")
        if usage_item.get("steps_saved", 0) < min_steps_saved:
            reasons.append(f"steps_saved<{min_steps_saved}")
        if not macro_is_function_like(group_key, macro, interface):
            reasons.append("not_function_like")
        items.append(
            {
                "macro_id": macro_id,
                "support": macro["support"],
                "length": len(macro["sequence"]),
                "replay_precision": replay_item.get("replay_precision", 0.0),
                "exact_replays": replay_item.get("exact_replays", 0),
                "steps_saved": usage_item.get("steps_saved", 0),
                "rejection_reasons": reasons,
                "sequence": list(macro["sequence"]),
            }
        )
    items.sort(key=lambda item: (-item["steps_saved"], -item["replay_precision"], -item["support"], item["macro_id"]))
    return items[:8]


def main() -> None:
    args = parse_args()
    groups = args.group or list(DEFAULT_CASES)
    site_groups = load_grouped_sequences(args.input, "website")
    site_family_groups = load_grouped_sequences(args.input, "website_task_family")

    cases = {}
    for group_key in groups:
        selection = choose_sequences(group_key, site_groups, site_family_groups)
        if selection is None:
            cases[group_key] = {"status": "missing"}
            continue

        _, sequences = selection
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
        registry = study["registry"]
        replay_by_id = {item["macro_id"]: item for item in study["replay"]["macros"]}
        usage_by_id = {item["macro_id"]: item for item in study["usage"]["macros"]}
        savings_episodes = list(study["savings"]["episodes"])
        savings_episodes.sort(key=lambda item: (-sum(item["macro_hits"].values()), -item["primitive_steps"], item["episode_id"]))

        case_payload = {
            "status": "promoted" if registry else "no_promoted_macros",
            "total_episodes": len(sequences),
            "train_episodes": len(train_pool),
            "eval_episodes": len(eval_sequences),
            "support_policy": args.support_policy,
            "support_threshold": support,
            "registry": registry[:5],
            "summary": study["savings"]["summary"],
        }

        if savings_episodes:
            top_episode = savings_episodes[0]
            case_payload["example_episode"] = {
                "episode_id": top_episode["episode_id"],
                "primitive_steps": top_episode["primitive_steps"],
                "compressed_steps": top_episode["compressed_steps"],
                "compression_ratio": top_episode["compression_ratio"],
                "macro_hits": top_episode["macro_hits"],
                "original_sequence": top_episode["sequence"],
                "compressed_sequence": top_episode["compressed_sequence"],
            }

        if not registry:
            case_payload["top_candidates"] = candidate_reasons(
                group_key,
                study["discovered_macros"],
                replay_by_id,
                usage_by_id,
                min_support=support,
                min_length=args.min_length,
                max_length=args.max_length,
                min_replay_precision=args.min_replay_precision,
                min_exact_replays=args.min_exact_replays,
                min_steps_saved=args.min_steps_saved,
            )

        cases[group_key] = case_payload

    payload = {
        "input": args.input,
        "canonicalization_mode": args.canonicalization_mode,
        "support_policy": args.support_policy,
        "cases": cases,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
