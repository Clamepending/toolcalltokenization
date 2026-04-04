#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.macro_study import fixed_holdout_split, promote_macros_for_group, support_threshold
from toolcalltokenization.trace_utils import dump_json, group_rows, group_sequences, load_jsonl, represent_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure held-out macro utility across canonicalization modes.")
    parser.add_argument("--input", required=True, help="Raw or canonical trace JSONL.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--dataset-name", default="", help="Optional dataset label for reporting.")
    parser.add_argument("--group-by", default="website_task_family", help="Grouping key for macro mining.")
    parser.add_argument(
        "--modes",
        default="signature,coarse_signature,value_slots,name_only,dataflow,dataflow_coarse",
        help="Comma-separated canonicalization modes to evaluate.",
    )
    parser.add_argument("--eval-ratio", type=float, default=0.2, help="Held-out ratio per group.")
    parser.add_argument("--min-eval-episodes", type=int, default=2, help="Minimum held-out episodes per group.")
    parser.add_argument("--min-total-episodes", type=int, default=4, help="Minimum total episodes required for a group.")
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


def evaluate_mode(rows: list[dict], mode: str, args: argparse.Namespace) -> dict:
    canonical_rows = represent_rows(rows, mode=mode)
    grouped_rows = group_rows(canonical_rows, args.group_by)

    totals = {
        "groups_seen": len(grouped_rows),
        "groups_evaluated": 0,
        "groups_with_promoted_macros": 0,
        "primitive_steps": 0,
        "compressed_steps": 0,
        "steps_saved": 0,
        "macro_calls": 0,
        "promoted_macros": 0,
        "parameterized_promoted_macros": 0,
        "covered_heldout_steps": 0,
        "weighted_replay_precision_numer": 0.0,
        "weighted_replay_precision_denom": 0,
    }
    per_group: list[dict] = []

    for group_key, group in sorted(grouped_rows.items()):
        sequences = group_sequences(group)
        if len(sequences) < args.min_total_episodes:
            continue

        train_sequences, eval_sequences = fixed_holdout_split(
            sequences,
            eval_ratio=args.eval_ratio,
            min_eval_episodes=args.min_eval_episodes,
        )
        if not train_sequences or not eval_sequences or len(train_sequences) >= len(sequences):
            continue

        support = support_threshold(len(train_sequences), args.support_policy)
        study = promote_macros_for_group(
            group_key,
            train_sequences,
            eval_sequences,
            canonicalization_mode=mode,
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

        totals["groups_evaluated"] += 1
        totals["primitive_steps"] += int(summary["primitive_steps"])
        totals["compressed_steps"] += int(summary["compressed_steps"])
        totals["steps_saved"] += int(summary["steps_saved"])
        totals["macro_calls"] += int(summary["macro_calls"])
        totals["promoted_macros"] += len(registry)
        totals["parameterized_promoted_macros"] += sum(1 for macro in registry if int(macro["num_inputs"]) > 0)
        if registry:
            totals["groups_with_promoted_macros"] += 1
            totals["covered_heldout_steps"] += int(summary["primitive_steps"])
            totals["weighted_replay_precision_numer"] += sum(
                float(macro["replay_precision"]) * int(macro["length"]) for macro in registry
            )
            totals["weighted_replay_precision_denom"] += sum(int(macro["length"]) for macro in registry)

        per_group.append(
            {
                "group_key": group_key,
                "episodes": len(sequences),
                "train_episodes": len(train_sequences),
                "eval_episodes": len(eval_sequences),
                "support_threshold": support,
                "promoted_macros": len(registry),
                "parameterized_promoted_macros": sum(1 for macro in registry if int(macro["num_inputs"]) > 0),
                "decision_reduction_ratio": summary["decision_reduction_ratio"],
                "steps_saved": summary["steps_saved"],
                "primitive_steps": summary["primitive_steps"],
            }
        )

    primitive_steps = totals["primitive_steps"]
    steps_saved = totals["steps_saved"]
    compressed_steps = totals["compressed_steps"]
    return {
        "canonicalization_mode": mode,
        "summary": {
            **totals,
            "decision_reduction_ratio": round(steps_saved / primitive_steps, 4) if primitive_steps else 0.0,
            "compression_ratio": round(compressed_steps / primitive_steps, 4) if primitive_steps else 0.0,
            "coverage_ratio": round(totals["covered_heldout_steps"] / primitive_steps, 4) if primitive_steps else 0.0,
            "weighted_macro_replay_precision": round(
                totals["weighted_replay_precision_numer"] / totals["weighted_replay_precision_denom"], 4
            )
            if totals["weighted_replay_precision_denom"]
            else 0.0,
        },
        "groups": per_group,
    }


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    modes = [part.strip() for part in str(args.modes).split(",") if part.strip()]
    results = [evaluate_mode(rows, mode, args) for mode in modes]
    payload = {
        "input": args.input,
        "dataset_name": args.dataset_name or Path(args.input).stem,
        "group_by": args.group_by,
        "modes": modes,
        "eval_ratio": args.eval_ratio,
        "min_eval_episodes": args.min_eval_episodes,
        "min_total_episodes": args.min_total_episodes,
        "support_policy": args.support_policy,
        "variants": results,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
