#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import compression_summary, group_sequences, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate compression from mined browser macros.")
    parser.add_argument("--input", required=True, help="Path to canonicalized JSONL trace events.")
    parser.add_argument("--macros", required=True, help="Path to macro JSON.")
    parser.add_argument("--output", required=True, help="Path to evaluation summary JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    sequences = group_sequences(rows)
    with open(args.macros, "r", encoding="utf-8") as handle:
        macros = json.load(handle)
    summary = compression_summary(sequences, macros)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
