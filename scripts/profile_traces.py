#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import (
    CANONICALIZATION_MODES,
    canonicalize_event,
    dump_json,
    group_sequences,
    load_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize trace characteristics before tokenization.")
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--output", required=True, help="Path to JSON summary.")
    parser.add_argument("--top-k", type=int, default=20, help="Number of top actions to report.")
    parser.add_argument(
        "--canonicalization-mode",
        choices=CANONICALIZATION_MODES,
        default="signature",
        help="How much structure to keep in each canonical action string.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = [canonicalize_event(row, mode=args.canonicalization_mode) for row in load_jsonl(args.input)]
    sequences = group_sequences(rows)
    lengths = [len(sequence) for sequence in sequences.values()]
    actions = Counter(row["canonical_action"] for row in rows if row.get("canonical_action"))
    action_types = Counter(str(row.get("action_type", "unknown")).lower() for row in rows)
    slot_actions = sum(1 for row in rows if "value=<" in str(row.get("canonical_action", "")))
    summary = {
        "episodes": len(sequences),
        "events": len(rows),
        "canonicalization_mode": args.canonicalization_mode,
        "avg_episode_length": round(sum(lengths) / len(lengths), 4) if lengths else 0.0,
        "max_episode_length": max(lengths) if lengths else 0,
        "min_episode_length": min(lengths) if lengths else 0,
        "slot_value_rate": round(slot_actions / len(rows), 4) if rows else 0.0,
        "action_types": dict(action_types.most_common()),
        "top_canonical_actions": [
            {"action": action, "count": count}
            for action, count in actions.most_common(args.top_k)
        ],
    }
    dump_json(args.output, summary)


if __name__ == "__main__":
    main()
