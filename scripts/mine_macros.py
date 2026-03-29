#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import dump_json, group_sequences, load_jsonl, mine_frequent_chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine repeated action chunks from canonical traces.")
    parser.add_argument("--input", required=True, help="Path to canonicalized JSONL trace events.")
    parser.add_argument("--output", required=True, help="Path to mined macro JSON.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum episode support for a macro.")
    parser.add_argument("--max-chunk-len", type=int, default=6, help="Longest macro length to consider.")
    parser.add_argument("--top-k", type=int, default=25, help="Maximum number of macros to keep.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    sequences = group_sequences(rows)
    macros = mine_frequent_chunks(
        sequences,
        min_support=args.min_support,
        max_chunk_len=args.max_chunk_len,
        top_k=args.top_k,
    )
    dump_json(args.output, macros)


if __name__ == "__main__":
    main()
