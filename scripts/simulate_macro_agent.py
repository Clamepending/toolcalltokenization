#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.macro_runtime import simulate_macro_agent
from toolcalltokenization.trace_utils import (
    dump_json,
    group_rows,
    group_sequences,
    load_jsonl,
    represent_rows,
    split_sequences,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate a macro-aware browser agent with primitive fallback on held-out replay traces."
    )
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--registry", required=True, help="Path to a promoted macro registry JSON file.")
    parser.add_argument("--output", required=True, help="Path to JSON output report.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Representation mode to use for replay sequences.")
    parser.add_argument("--group-by", default="website_task_family", help="Grouping key that matches the registry.")
    parser.add_argument("--min-group-episodes", type=int, default=3, help="Minimum episode count for a group to be evaluated.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes used for discovery when recreating the eval split.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the train/test split.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    grouped_rows = group_rows(rows, args.group_by)

    eval_sequences_by_group = {}
    for group_key, rows_in_group in grouped_rows.items():
        represented = represent_rows(rows_in_group, mode=args.canonicalization_mode)
        sequences = group_sequences(represented)
        if len(sequences) < args.min_group_episodes:
            continue
        _, eval_sequences = split_sequences(sequences, train_ratio=args.train_ratio, seed=args.seed)
        if not eval_sequences:
            eval_sequences = sequences
        eval_sequences_by_group[group_key] = eval_sequences

    import json

    with open(args.registry, "r", encoding="utf-8") as handle:
        registry_payload = json.load(handle)
    registry_by_group = {}
    for entry in registry_payload.get("registry", []):
        registry_by_group.setdefault(entry["group_key"], []).append(entry)

    simulation = simulate_macro_agent(eval_sequences_by_group, registry_by_group)
    payload = {
        "input_rows": len(rows),
        "registry": args.registry,
        "group_by": args.group_by,
        "canonicalization_mode": args.canonicalization_mode,
        "train_ratio": args.train_ratio,
        "summary": simulation["summary"],
        "groups": simulation["groups"],
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
