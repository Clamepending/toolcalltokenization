#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import (
    CANONICALIZATION_MODES,
    dump_json,
    evaluate_macro_replay,
    group_rows,
    group_sequences,
    load_jsonl,
    macro_has_binding,
    mine_frequent_chunks,
    represent_rows,
    split_sequences,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate held-out replay precision for mined macros."
    )
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--output", required=True, help="Path to JSON output report.")
    parser.add_argument(
        "--canonicalization-mode",
        choices=CANONICALIZATION_MODES,
        default="dataflow_coarse",
        help="Representation to use before macro mining.",
    )
    parser.add_argument(
        "--group-by",
        default="",
        help="Optional field or synthetic key to group by before mining, e.g. website, task_family, or website_task_family.",
    )
    parser.add_argument("--min-group-episodes", type=int, default=5, help="Minimum episode count for a grouped report entry.")
    parser.add_argument("--top-k", type=int, default=25, help="Maximum macros to keep.")
    parser.add_argument("--max-chunk-len", type=int, default=4, help="Longest chunk length to consider.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum episode support for a macro.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes to use for macro discovery.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the train/test split.")
    parser.add_argument("--trigger-prefix-len", type=int, default=1, help="Number of leading steps used as a macro trigger prefix.")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    grouped_rows = group_rows(rows, args.group_by or "<all>")

    groups = []
    for group_key, group in grouped_rows.items():
        represented_rows = represent_rows(group, mode=args.canonicalization_mode)
        sequences = group_sequences(represented_rows)
        if len(sequences) < args.min_group_episodes and args.group_by:
            continue

        train_sequences, eval_sequences = split_sequences(
            sequences,
            train_ratio=args.train_ratio,
            seed=args.seed,
        )
        if not eval_sequences:
            train_sequences = sequences
            eval_sequences = sequences

        macros = mine_frequent_chunks(
            train_sequences,
            min_support=args.min_support,
            max_chunk_len=args.max_chunk_len,
            top_k=args.top_k,
        )
        if not macros:
            continue

        replay = evaluate_macro_replay(
            macros,
            eval_sequences,
            trigger_prefix_len=args.trigger_prefix_len,
        )
        groups.append(
            {
                "group_key": group_key,
                "episodes": len(sequences),
                "train_episodes": len(train_sequences),
                "eval_episodes": len(eval_sequences),
                "canonicalization_mode": args.canonicalization_mode,
                "num_macros": len(macros),
                "num_parameterized_macros": sum(1 for macro in macros if macro_has_binding(macro)),
                "replay": replay,
                "top_macros": replay["macros"][:10],
                "top_parameterized_macros": [macro for macro in replay["macros"] if macro["has_binding"]][:10],
            }
        )

    groups.sort(
        key=lambda item: (
            -item["replay"]["summary"]["exact_replays"],
            -item["episodes"],
            item["group_key"],
        )
    )

    total_candidates = sum(item["replay"]["summary"]["candidate_triggers"] for item in groups)
    total_exact = sum(item["replay"]["summary"]["exact_replays"] for item in groups)
    total_param_candidates = sum(item["replay"]["summary"]["parameterized_candidate_triggers"] for item in groups)
    total_param_exact = sum(item["replay"]["summary"]["parameterized_exact_replays"] for item in groups)
    total_macros = sum(item["replay"]["summary"]["macros_evaluated"] for item in groups)
    total_param_macros = sum(item["replay"]["summary"]["parameterized_macros_evaluated"] for item in groups)

    payload = {
        "input_rows": len(rows),
        "group_by": args.group_by or "<all>",
        "canonicalization_mode": args.canonicalization_mode,
        "train_ratio": args.train_ratio,
        "trigger_prefix_len": args.trigger_prefix_len,
        "summary": {
            "groups_reported": len(groups),
            "macros_evaluated": total_macros,
            "candidate_triggers": total_candidates,
            "exact_replays": total_exact,
            "replay_precision": round(total_exact / total_candidates, 4) if total_candidates else 0.0,
            "parameterized_macros_evaluated": total_param_macros,
            "parameterized_candidate_triggers": total_param_candidates,
            "parameterized_exact_replays": total_param_exact,
            "parameterized_replay_precision": round(total_param_exact / total_param_candidates, 4)
            if total_param_candidates
            else 0.0,
        },
        "groups": groups,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
