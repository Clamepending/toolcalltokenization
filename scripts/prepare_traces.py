#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import canonicalize_event, dump_jsonl, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canonicalize raw browser-action traces.")
    parser.add_argument("--input", required=True, help="Path to raw JSONL trace events.")
    parser.add_argument("--output", required=True, help="Path to canonicalized JSONL trace events.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    canonical_rows = [canonicalize_event(row) for row in rows]
    dump_jsonl(args.output, canonical_rows)


if __name__ == "__main__":
    main()
