#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
        description="Evaluate hierarchical promoted-macro registries on held-out replay traces."
    )
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--exact-registry", required=True, help="Path to the most specific registry, e.g. website_task_family.")
    parser.add_argument("--site-registry", required=True, help="Path to a website-level registry.")
    parser.add_argument("--family-registry", required=True, help="Path to a task-family-level registry.")
    parser.add_argument("--output", required=True, help="Path to JSON output report.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Representation mode to use for replay sequences.")
    parser.add_argument("--group-by", default="website_task_family", help="Target grouping key for evaluation.")
    parser.add_argument("--min-group-episodes", type=int, default=3, help="Minimum episode count for a group to be evaluated.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes used for discovery when recreating the eval split.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the train/test split.")
    return parser.parse_args()


def load_registry_by_group(path: str) -> dict[str, list[dict]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    by_group: dict[str, list[dict]] = {}
    for entry in payload.get("registry", []):
        by_group.setdefault(str(entry["group_key"]), []).append(entry)
    return by_group


def registry_sort_key(macro: dict) -> tuple:
    return (
        int(macro.get("_scope_rank", 99)),
        -float(macro.get("replay_precision", 0.0)),
        -int(macro.get("num_inputs", 0)),
        -len(macro.get("sequence", [])),
        -int(macro.get("support", 0)),
        str(macro.get("suggested_name", macro.get("macro_id", ""))),
    )


def candidate_macros(sequence: list[str], index: int, macros: list[dict]) -> list[dict]:
    candidates = []
    for macro in macros:
        steps = list(macro.get("sequence", []))
        if len(steps) < 2:
            continue
        prefix_len = min(int(macro.get("trigger_prefix_len", 1)), len(steps) - 1)
        if list(sequence[index : index + prefix_len]) == steps[:prefix_len]:
            candidates.append(macro)
    candidates.sort(key=registry_sort_key)
    return candidates


def simulate_sequence(sequence: list[str], macros: list[dict]) -> dict:
    index = 0
    attempted = successful = failed = primitive = 0

    while index < len(sequence):
        candidates = candidate_macros(sequence, index, macros)
        if not candidates:
            primitive += 1
            index += 1
            continue

        macro = candidates[0]
        steps = list(macro.get("sequence", []))
        attempted += 1
        if list(sequence[index : index + len(steps)]) == steps:
            successful += 1
            index += len(steps)
            continue

        failed += 1
        primitive += 1
        index += 1

    decisions = attempted + primitive
    primitive_steps = len(sequence)
    return {
        "primitive_steps": primitive_steps,
        "agent_decisions": decisions,
        "steps_saved": primitive_steps - decisions,
        "attempted_macro_calls": attempted,
        "successful_macro_calls": successful,
        "failed_macro_calls": failed,
    }


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

    exact_by_group = load_registry_by_group(args.exact_registry)
    site_by_group = load_registry_by_group(args.site_registry)
    family_by_group = load_registry_by_group(args.family_registry)

    variants = [
        {"name": "exact_only", "include_site": False, "include_family": False},
        {"name": "site_only", "site_threshold": 0.5, "include_exact": False, "include_family": False},
        {"name": "family_only", "family_threshold": 0.5, "include_exact": False, "include_site": False},
        {"name": "exact_then_site_r05", "site_threshold": 0.5, "include_family": False},
        {"name": "exact_then_site_r07", "site_threshold": 0.7, "include_family": False},
        {"name": "exact_then_site_then_family_r05", "site_threshold": 0.5, "family_threshold": 0.5, "include_family": True},
    ]

    reports = []
    for variant in variants:
        include_exact = variant.get("include_exact", True)
        include_site = variant.get("include_site", True)
        include_family = variant.get("include_family", False)
        site_threshold = float(variant.get("site_threshold", 0.0) or 0.0)
        family_threshold = float(variant.get("family_threshold", 0.0) or 0.0)

        total = {
            "primitive_steps": 0,
            "agent_decisions": 0,
            "steps_saved": 0,
            "attempted_macro_calls": 0,
            "successful_macro_calls": 0,
            "failed_macro_calls": 0,
        }
        covered_steps = 0
        groups_with_macros = 0

        for group_key, episodes in eval_sequences_by_group.items():
            site_key = str(group_key).split("::", 1)[0]
            family_key = str(group_key).split("::", 1)[1] if "::" in str(group_key) else "workflow"
            macros = []
            seen = set()

            if include_exact:
                for entry in exact_by_group.get(group_key, []):
                    item = deepcopy(entry)
                    item["_scope_rank"] = 0
                    macros.append(item)
                    seen.add(("exact", item["macro_id"]))

            if include_site:
                for entry in site_by_group.get(site_key, []):
                    if float(entry.get("replay_precision", 0.0)) < site_threshold:
                        continue
                    key = ("site", entry["macro_id"])
                    if key in seen:
                        continue
                    item = deepcopy(entry)
                    item["_scope_rank"] = 1
                    macros.append(item)
                    seen.add(key)

            if include_family:
                for entry in family_by_group.get(family_key, []):
                    if float(entry.get("replay_precision", 0.0)) < family_threshold:
                        continue
                    key = ("family", entry["macro_id"])
                    if key in seen:
                        continue
                    item = deepcopy(entry)
                    item["_scope_rank"] = 2
                    macros.append(item)
                    seen.add(key)

            if macros:
                groups_with_macros += 1

            group_attempts = 0
            group_steps = 0
            for sequence in episodes.values():
                summary = simulate_sequence(sequence, list(macros))
                group_attempts += summary["attempted_macro_calls"]
                group_steps += summary["primitive_steps"]
                for key, value in summary.items():
                    total[key] += value
            if group_attempts:
                covered_steps += group_steps

        reports.append(
            {
                "name": variant["name"],
                "summary": {
                    **total,
                    "decision_reduction_ratio": round(total["steps_saved"] / total["primitive_steps"], 4)
                    if total["primitive_steps"]
                    else 0.0,
                    "macro_success_rate": round(total["successful_macro_calls"] / total["attempted_macro_calls"], 4)
                    if total["attempted_macro_calls"]
                    else 0.0,
                    "coverage_ratio": round(covered_steps / total["primitive_steps"], 4)
                    if total["primitive_steps"]
                    else 0.0,
                    "groups_evaluated": len(eval_sequences_by_group),
                    "groups_with_macros_available": groups_with_macros,
                },
            }
        )

    dump_json(
        args.output,
        {
            "input": args.input,
            "group_by": args.group_by,
            "canonicalization_mode": args.canonicalization_mode,
            "variants": reports,
        },
    )


if __name__ == "__main__":
    main()
