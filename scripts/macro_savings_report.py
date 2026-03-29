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
    group_rows,
    group_sequences,
    load_jsonl,
    macro_has_binding,
    mine_frequent_chunks,
    represent_rows,
    split_sequences,
    summarize_macro_savings,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate step, token, and decision savings from replacing primitive traces with mined macros."
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
    parser.add_argument("--max-chunk-len", type=int, default=6, help="Longest chunk length to consider.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum episode support for a macro.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes to use for macro discovery.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the train/test split.")
    parser.add_argument("--decision-tokens-per-step", type=int, default=50, help="Estimated model output tokens per primitive decision.")
    parser.add_argument("--decision-latency-ms", type=int, default=1000, help="Estimated model decision latency per primitive step.")
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

        savings = summarize_macro_savings(
            eval_sequences,
            macros,
            decision_tokens_per_step=args.decision_tokens_per_step,
            decision_latency_ms=args.decision_latency_ms,
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
                "savings": savings,
                "top_macros": macros[:10],
                "top_parameterized_macros": [macro for macro in macros if macro_has_binding(macro)][:10],
            }
        )

    groups.sort(
        key=lambda item: (
            -item["savings"]["summary"]["estimated_model_decisions_saved"],
            -item["episodes"],
            item["group_key"],
        )
    )

    total_primitive = sum(item["savings"]["summary"]["primitive_steps"] for item in groups)
    total_compressed = sum(item["savings"]["summary"]["compressed_steps"] for item in groups)
    total_macro_calls = sum(item["savings"]["summary"]["macro_calls"] for item in groups)
    weighted_span_sum = sum(
        item["savings"]["summary"]["avg_macro_span"] * item["savings"]["summary"]["macro_calls"]
        for item in groups
    )
    total_parameterized_calls = sum(item["savings"]["summary"]["parameterized_macro_calls"] for item in groups)
    total_parameterized_steps_saved = sum(item["savings"]["summary"]["parameterized_steps_saved"] for item in groups)
    total_decisions_saved = sum(item["savings"]["summary"]["estimated_model_decisions_saved"] for item in groups)
    total_tokens_saved = sum(item["savings"]["summary"]["estimated_output_tokens_saved"] for item in groups)
    total_latency_saved_ms = sum(item["savings"]["summary"]["estimated_decision_latency_saved_ms"] for item in groups)

    payload = {
        "input_rows": len(rows),
        "group_by": args.group_by or "<all>",
        "canonicalization_mode": args.canonicalization_mode,
        "train_ratio": args.train_ratio,
        "decision_tokens_per_step": args.decision_tokens_per_step,
        "decision_latency_ms": args.decision_latency_ms,
        "summary": {
            "groups_reported": len(groups),
            "primitive_steps": total_primitive,
            "compressed_steps": total_compressed,
            "compression_ratio": round(total_compressed / total_primitive, 4) if total_primitive else 0.0,
            "macro_calls": total_macro_calls,
            "avg_macro_span": round(weighted_span_sum / total_macro_calls, 4) if total_macro_calls else 0.0,
            "steps_saved": total_primitive - total_compressed,
            "decision_reduction_ratio": round((total_primitive - total_compressed) / total_primitive, 4)
            if total_primitive
            else 0.0,
            "parameterized_macro_calls": total_parameterized_calls,
            "parameterized_steps_saved": total_parameterized_steps_saved,
            "estimated_model_decisions_saved": total_decisions_saved,
            "estimated_output_tokens_saved": total_tokens_saved,
            "estimated_decision_latency_saved_ms": total_latency_saved_ms,
        },
        "groups": groups,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
