#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.speculative_decoding import (
    build_trace_episodes,
    export_text_dataset,
    load_jsonl,
    split_train_valid_test,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare MLX-LoRA text datasets from canonical traces.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "outputs" / "ottoauth_live_collection" / "canonical_trace.jsonl"),
        help="Canonical trace JSONL.",
    )
    parser.add_argument("--website", default="amazon.com", help="Website bucket.")
    parser.add_argument("--min-steps", type=int, default=6, help="Minimum steps to keep.")
    parser.add_argument("--heldout-ratio", type=float, default=0.2, help="Test split ratio.")
    parser.add_argument("--valid-ratio-within-train", type=float, default=0.2, help="Validation ratio within train pool.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "speculative_decoding" / "datasets" / "amazon_trace_lm"),
        help="Directory for train/valid/test.jsonl files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    episodes = build_trace_episodes(rows, website=args.website, min_steps=args.min_steps)
    train, valid, test = split_train_valid_test(
        episodes,
        heldout_ratio=args.heldout_ratio,
        valid_ratio_within_train=args.valid_ratio_within_train,
        min_valid=1,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    export_text_dataset(output_dir / "train.jsonl", train)
    export_text_dataset(output_dir / "valid.jsonl", valid)
    export_text_dataset(output_dir / "test.jsonl", test)

    summary = {
        "input": args.input,
        "website": args.website,
        "min_steps": args.min_steps,
        "heldout_ratio": args.heldout_ratio,
        "valid_ratio_within_train": args.valid_ratio_within_train,
        "total_episodes": len(episodes),
        "train_episodes": len(train),
        "valid_episodes": len(valid),
        "test_episodes": len(test),
        "train_ids": [episode.episode_id for episode in train],
        "valid_ids": [episode.episode_id for episode in valid],
        "test_ids": [episode.episode_id for episode in test],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
