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
    apply_bpe_tokens,
    apply_macros,
    bpe_summary,
    canonicalize_event,
    dump_json,
    dump_jsonl,
    evaluate_next_token_cache,
    group_sequences,
    load_jsonl,
    mine_frequent_chunks,
    compression_summary,
    split_sequences,
    train_bpe_tokens,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare frequent-chunk mining and BPE-style action tokenization.")
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--output-dir", required=True, help="Directory for canonical traces and comparison outputs.")
    parser.add_argument("--top-k", type=int, default=25, help="Maximum number of frequent chunks to keep.")
    parser.add_argument("--max-chunk-len", type=int, default=4, help="Longest frequent chunk length to consider.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum episode support for a chunk.")
    parser.add_argument("--num-merges", type=int, default=25, help="Number of BPE merges to attempt.")
    parser.add_argument("--min-occurrences", type=int, default=2, help="Minimum pair occurrences for a BPE merge.")
    parser.add_argument("--bpe-min-support", type=int, default=2, help="Minimum episode support for a BPE merge.")
    parser.add_argument("--train-ratio", type=float, default=1.0, help="Fraction of episodes to use for training tokenizers.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the train/test split.")
    parser.add_argument("--context-len", type=int, default=1, help="Prefix length for next-token cache evaluation.")
    parser.add_argument(
        "--canonicalization-mode",
        choices=CANONICALIZATION_MODES,
        default="signature",
        help="How much structure to keep in each canonical action string.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(args.input)
    canonical_rows = [canonicalize_event(row, mode=args.canonicalization_mode) for row in rows]
    canonical_path = output_dir / "canonical_trace.jsonl"
    dump_jsonl(str(canonical_path), canonical_rows)

    sequences = group_sequences(canonical_rows)
    macros = mine_frequent_chunks(
        sequences,
        min_support=args.min_support,
        max_chunk_len=args.max_chunk_len,
        top_k=args.top_k,
    )
    macro_eval = compression_summary(sequences, macros)

    merges = train_bpe_tokens(
        sequences,
        num_merges=args.num_merges,
        min_occurrences=args.min_occurrences,
        min_support=args.bpe_min_support,
    )
    bpe_eval = bpe_summary(sequences, merges)

    dump_json(str(output_dir / "macros.json"), macros)
    dump_json(str(output_dir / "macro_eval.json"), macro_eval)
    dump_json(str(output_dir / "bpe_merges.json"), merges)
    dump_json(str(output_dir / "bpe_eval.json"), bpe_eval)

    primitive_steps = macro_eval["summary"]["primitive_steps"]
    comparison = {
        "input_rows": len(rows),
        "episodes": len(sequences),
        "primitive_steps": primitive_steps,
        "canonicalization_mode": args.canonicalization_mode,
        "train_ratio": args.train_ratio,
        "frequent_chunks": {
            "num_macros": len(macros),
            "compressed_steps": macro_eval["summary"]["compressed_steps"],
            "compression_ratio": macro_eval["summary"]["compression_ratio"],
            "episodes_with_macro_use": macro_eval["summary"]["episodes_with_macro_use"],
        },
        "bpe": {
            "num_merges": len(merges),
            "compressed_steps": bpe_eval["summary"]["compressed_steps"],
            "compression_ratio": bpe_eval["summary"]["compression_ratio"],
            "episodes_with_token_use": bpe_eval["summary"]["episodes_with_token_use"],
        },
    }
    dump_json(str(output_dir / "comparison.json"), comparison)

    train_sequences, test_sequences = split_sequences(
        sequences,
        train_ratio=args.train_ratio,
        seed=args.seed,
    )
    if test_sequences:
        holdout_macros = mine_frequent_chunks(
            train_sequences,
            min_support=args.min_support,
            max_chunk_len=args.max_chunk_len,
            top_k=args.top_k,
        )
        holdout_merges = train_bpe_tokens(
            train_sequences,
            num_merges=args.num_merges,
            min_occurrences=args.min_occurrences,
            min_support=args.bpe_min_support,
        )
        primitive_cache = evaluate_next_token_cache(
            train_sequences,
            test_sequences,
            context_len=args.context_len,
        )
        macro_cache = evaluate_next_token_cache(
            apply_macros(train_sequences, holdout_macros),
            apply_macros(test_sequences, holdout_macros),
            context_len=args.context_len,
        )
        bpe_cache = evaluate_next_token_cache(
            apply_bpe_tokens(train_sequences, holdout_merges),
            apply_bpe_tokens(test_sequences, holdout_merges),
            context_len=args.context_len,
        )
        holdout = {
            "train_episodes": len(train_sequences),
            "test_episodes": len(test_sequences),
            "canonicalization_mode": args.canonicalization_mode,
            "frequent_chunk_compression": compression_summary(test_sequences, holdout_macros)["summary"],
            "bpe_compression": bpe_summary(test_sequences, holdout_merges)["summary"],
            "primitive_cache": primitive_cache,
            "frequent_chunk_cache": macro_cache,
            "bpe_cache": bpe_cache,
            "train_macros": len(holdout_macros),
            "train_merges": len(holdout_merges),
        }
        dump_json(str(output_dir / "holdout_cache_eval.json"), holdout)


if __name__ == "__main__":
    main()
