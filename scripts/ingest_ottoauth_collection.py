#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.datasets import convert_ottoauth_traces, dump_jsonl
from toolcalltokenization.trace_utils import dump_json, represent_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert locally recorded OttoAuth traces into macro-mining JSONL plus a collection summary.",
    )
    parser.add_argument(
        "--input",
        default=str(ROOT / "data" / "ottoauth"),
        help="Root folder containing OttoAuth trace directories.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "outputs" / "ottoauth_live_collection"),
        help="Directory for raw/canonical JSONL outputs and summary JSON.",
    )
    parser.add_argument(
        "--canonicalization-mode",
        default="dataflow_coarse",
        help="Canonicalization mode passed to represent_rows().",
    )
    return parser.parse_args()


def summarize_collection(raw_rows: list[dict], canonical_rows: list[dict]) -> dict:
    rows_by_episode: dict[str, list[dict]] = defaultdict(list)
    canonical_by_episode: dict[str, list[dict]] = defaultdict(list)
    for row in raw_rows:
        rows_by_episode[str(row.get("episode_id"))].append(row)
    for row in canonical_rows:
        canonical_by_episode[str(row.get("episode_id"))].append(row)

    status_counts = Counter(str(row.get("task_status") or "<missing>") for row in raw_rows)
    site_counts = Counter(str(row.get("website") or "<missing>") for row in raw_rows)
    action_counts = Counter(str(row.get("action_type") or "<missing>") for row in raw_rows)
    tool_counts = Counter(str(row.get("tool_name") or "<missing>") for row in raw_rows)

    example_episodes = []
    for episode_id in sorted(rows_by_episode)[:5]:
        episode_rows = sorted(rows_by_episode[episode_id], key=lambda row: int(row.get("step_index", 0)))
        canonical_episode_rows = sorted(
            canonical_by_episode.get(episode_id, []),
            key=lambda row: int(row.get("step_index", 0)),
        )
        example_episodes.append(
            {
                "episode_id": episode_id,
                "website": episode_rows[0].get("website"),
                "task_status": episode_rows[0].get("task_status"),
                "task": episode_rows[0].get("task"),
                "raw_sequence": [str(row.get("action_type", "")) for row in episode_rows],
                "canonical_sequence": [
                    str(row.get("canonical_action", ""))
                    for row in canonical_episode_rows
                    if row.get("canonical_action")
                ],
            }
        )

    return {
        "episodes": len(rows_by_episode),
        "events": len(raw_rows),
        "canonical_events": len(canonical_rows),
        "sites": dict(site_counts.most_common()),
        "task_status_counts": dict(status_counts.most_common()),
        "top_action_types": action_counts.most_common(20),
        "top_tool_names": tool_counts.most_common(20),
        "episode_lengths": {
            episode_id: len(rows)
            for episode_id, rows in sorted(rows_by_episode.items())
        },
        "example_episodes": example_episodes,
    }


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_rows = convert_ottoauth_traces(args.input)
    canonical_rows = represent_rows(raw_rows, mode=args.canonicalization_mode)
    summary = summarize_collection(raw_rows, canonical_rows)

    dump_jsonl(str(output_dir / "raw_trace.jsonl"), raw_rows)
    dump_jsonl(str(output_dir / "canonical_trace.jsonl"), canonical_rows)
    dump_json(str(output_dir / "summary.json"), summary)


if __name__ == "__main__":
    main()
