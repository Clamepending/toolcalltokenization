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
    dump_json,
    group_rows,
    group_sequences,
    load_jsonl,
    macro_has_binding,
    mine_frequent_chunks,
    represent_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine macros within sites or other groups to surface workflow-local redundancy."
    )
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--output", required=True, help="Path to JSON output report.")
    parser.add_argument(
        "--canonicalization-mode",
        choices=CANONICALIZATION_MODES,
        default="dataflow_coarse",
        help="Representation to use before macro mining.",
    )
    parser.add_argument(
        "--group-by",
        default="website",
        help="Field or synthetic key to group traces by before mining, e.g. website, domain, task_family, or website_task_family.",
    )
    parser.add_argument("--min-episodes", type=int, default=5, help="Minimum episode count for a group to be reported.")
    parser.add_argument("--top-groups", type=int, default=20, help="Maximum number of groups to keep in the report.")
    parser.add_argument("--top-k", type=int, default=20, help="Maximum macros to keep per group.")
    parser.add_argument("--max-chunk-len", type=int, default=4, help="Longest chunk length to mine.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum episode support for a macro.")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    grouped = group_rows(rows, args.group_by)

    report_groups = []
    for group_key, rows_in_group in grouped.items():
        represented_rows = represent_rows(rows_in_group, mode=args.canonicalization_mode)
        sequences = group_sequences(represented_rows)
        if len(sequences) < args.min_episodes:
            continue
        macros = mine_frequent_chunks(
            sequences,
            min_support=args.min_support,
            max_chunk_len=args.max_chunk_len,
            top_k=args.top_k,
        )
        if not macros:
            continue
        vocab = len({row["canonical_action"] for row in represented_rows if row.get("canonical_action")})
        parameterized_macros = [macro for macro in macros if macro_has_binding(macro)]
        report_groups.append(
            {
                "group_key": group_key,
                "episodes": len(sequences),
                "events": len(represented_rows),
                "vocab": vocab,
                "canonicalization_mode": args.canonicalization_mode,
                "num_macros": len(macros),
                "num_parameterized_macros": len(parameterized_macros),
                "top_macros": macros,
                "top_parameterized_macros": parameterized_macros[:10],
            }
        )

    report_groups.sort(key=lambda item: (-item["episodes"], -item["events"], item["group_key"]))
    payload = {
        "input_rows": len(rows),
        "group_by": args.group_by,
        "canonicalization_mode": args.canonicalization_mode,
        "min_episodes": args.min_episodes,
        "groups_reported": len(report_groups[: args.top_groups]),
        "groups": report_groups[: args.top_groups],
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
