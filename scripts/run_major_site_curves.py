#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.macro_study import promote_macros_for_group, support_threshold
from toolcalltokenization.trace_utils import dump_json, evaluate_macro_replay, group_sequences, load_jsonl


DEFAULT_SITES = [
    "amazon",
    "ebay",
    "apple",
    "target",
    "newegg",
    "united",
    "yelp",
    "booking",
    "kayak",
    "google",
    "ubereats",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate held-out learning curves for major websites.")
    parser.add_argument("--input", required=True, help="Canonical JSONL trace file.")
    parser.add_argument("--output", required=True, help="Path to JSON output.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Recorded canonicalization mode.")
    parser.add_argument("--site", action="append", help="Website to include. May be repeated.")
    parser.add_argument("--heldout-episodes", type=int, default=2, help="Fixed held-out episode count per site.")
    parser.add_argument("--support-policy", choices=("loose", "strict", "adaptive"), default="loose", help="Support threshold policy.")
    parser.add_argument("--top-k", type=int, default=25, help="Maximum mined macros per site.")
    parser.add_argument("--max-chunk-len", type=int, default=6, help="Longest chunk length to consider.")
    parser.add_argument("--trigger-prefix-len", type=int, default=2, help="Primary trigger length used for promotion.")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum macro length required for promotion.")
    parser.add_argument("--max-length", type=int, default=6, help="Maximum macro length required for promotion.")
    parser.add_argument("--min-replay-precision", type=float, default=0.5, help="Minimum held-out replay precision required for promotion.")
    parser.add_argument("--min-exact-replays", type=int, default=1, help="Minimum exact replays required for promotion.")
    parser.add_argument("--min-steps-saved", type=int, default=1, help="Minimum held-out steps saved required for promotion.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requested_sites = args.site or list(DEFAULT_SITES)
    rows = load_jsonl(args.input)
    site_rows: dict[str, list[dict]] = {}
    for row in rows:
        site = str(row.get("website") or "")
        if site in requested_sites:
            site_rows.setdefault(site, []).append(row)

    payload = {
        "input": args.input,
        "canonicalization_mode": args.canonicalization_mode,
        "heldout_episodes": args.heldout_episodes,
        "support_policy": args.support_policy,
        "sites_requested": requested_sites,
        "sites_found": [],
        "sites_missing": [],
        "curves": {},
    }

    for site in requested_sites:
        rows_for_site = site_rows.get(site)
        if not rows_for_site:
            payload["sites_missing"].append(site)
            continue
        sequences = group_sequences(rows_for_site)
        total_site_episodes = len(sequences)
        if total_site_episodes < args.heldout_episodes:
            payload["sites_missing"].append(site)
            continue

        episode_ids = sorted(sequences)
        heldout = min(args.heldout_episodes, max(1, total_site_episodes - 1))
        eval_ids = episode_ids[-heldout:]
        train_ids = episode_ids[:-heldout]
        eval_sequences = {episode_id: list(sequences[episode_id]) for episode_id in eval_ids}

        points = [
            {
                "total_episodes": heldout,
                "train_episodes": 0,
                "heldout_episodes": heldout,
                "compression_ratio": 1.0,
                "decision_reduction_ratio": 0.0,
                "promoted_macros": 0,
                "avg_macro_length": 0.0,
                "max_macro_length": 0,
                "trigger_precision_prefix1": 1.0,
                "trigger_precision_prefix2": 1.0,
            }
        ]

        for train_episodes in range(1, len(train_ids) + 1):
            train_sequences = {episode_id: list(sequences[episode_id]) for episode_id in train_ids[:train_episodes]}
            support = support_threshold(train_episodes, args.support_policy)
            study = promote_macros_for_group(
                site,
                train_sequences,
                eval_sequences,
                canonicalization_mode=args.canonicalization_mode,
                top_k=args.top_k,
                max_chunk_len=args.max_chunk_len,
                min_support=support,
                min_promoted_support=support,
                trigger_prefix_len=args.trigger_prefix_len,
                min_length=args.min_length,
                max_length=args.max_length,
                min_replay_precision=args.min_replay_precision,
                min_exact_replays=args.min_exact_replays,
                min_steps_saved=args.min_steps_saved,
            )
            registry = study["registry"]
            p1 = evaluate_macro_replay(registry, eval_sequences, trigger_prefix_len=1)["summary"] if registry else {"replay_precision": 1.0}
            p2 = evaluate_macro_replay(registry, eval_sequences, trigger_prefix_len=2)["summary"] if registry else {"replay_precision": 1.0}
            summary = study["savings"]["summary"]
            points.append(
                {
                    "total_episodes": train_episodes + heldout,
                    "train_episodes": train_episodes,
                    "heldout_episodes": heldout,
                    "compression_ratio": summary["compression_ratio"],
                    "decision_reduction_ratio": summary["decision_reduction_ratio"],
                    "promoted_macros": len(registry),
                    "avg_macro_length": round(sum(item["length"] for item in registry) / len(registry), 4) if registry else 0.0,
                    "max_macro_length": max((int(item["length"]) for item in registry), default=0),
                    "trigger_precision_prefix1": p1["replay_precision"],
                    "trigger_precision_prefix2": p2["replay_precision"],
                }
            )

        payload["sites_found"].append(site)
        payload["curves"][site] = {
            "total_episodes": total_site_episodes,
            "heldout_episodes": heldout,
            "points": points,
        }

    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
