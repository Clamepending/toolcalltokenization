#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.datasets import (
    convert_mind2web,
    convert_weblinx_replay,
    convert_wonderbread_trace,
    dump_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert external browser-trace datasets into the repo JSONL trace format.")
    parser.add_argument("--source", choices=("mind2web", "weblinx", "wonderbread"), required=True)
    parser.add_argument("--input", required=True, help="Path to dataset file or root directory.")
    parser.add_argument("--output", required=True, help="Path to JSONL output file.")
    parser.add_argument("--include-chat", action="store_true", help="Include WebLINX chat turns as SAY actions.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.source == "mind2web":
        rows = convert_mind2web(args.input)
    elif args.source == "weblinx":
        rows = convert_weblinx_replay(args.input, include_chat=args.include_chat)
    else:
        rows = convert_wonderbread_trace(args.input)
    dump_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
