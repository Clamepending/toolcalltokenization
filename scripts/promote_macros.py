#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import (
    CANONICALIZATION_MODES,
    dump_json,
    evaluate_macro_replay,
    group_rows,
    group_sequences,
    load_jsonl,
    macro_has_binding,
    macro_interface,
    macro_usage_summary,
    mine_frequent_chunks,
    represent_rows,
    split_sequences,
)


FAMILY_NAME_HINTS = {
    "auth": "login",
    "cart": "add_to_cart",
    "checkout": "checkout",
    "flight": "flight_search",
    "lodging": "lodging_search",
    "rental": "rental_search",
    "reservation": "reservation_flow",
    "filter_sort": "filter_or_sort",
    "profile": "account_update",
    "search": "search",
}
FUNCTION_LABEL_HINTS = {
    "search",
    "login",
    "checkout",
    "add_to_cart",
    "city",
    "zip",
    "destination",
    "origin",
    "depart",
    "return",
    "date",
    "email",
    "password",
    "location",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote held-out-approved macros into a registry of candidate browser-agent tools."
    )
    parser.add_argument("--input", required=True, help="Path to raw or converted JSONL trace events.")
    parser.add_argument("--output", required=True, help="Path to JSON output registry.")
    parser.add_argument(
        "--canonicalization-mode",
        choices=CANONICALIZATION_MODES,
        default="dataflow_coarse",
        help="Representation to use before macro mining.",
    )
    parser.add_argument(
        "--group-by",
        default="website_task_family",
        help="Field or synthetic key to group traces by before promotion, e.g. website, task_family, or website_task_family.",
    )
    parser.add_argument("--min-group-episodes", type=int, default=3, help="Minimum episode count for a group to be evaluated.")
    parser.add_argument("--top-k", type=int, default=25, help="Maximum mined macros per group.")
    parser.add_argument("--max-chunk-len", type=int, default=4, help="Longest chunk length to consider.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum train-episode support for discovery.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes to use for discovery.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for the train/test split.")
    parser.add_argument("--trigger-prefix-len", type=int, default=2, help="Number of leading steps used as a macro trigger prefix.")
    parser.add_argument("--min-promoted-support", type=int, default=3, help="Minimum train support required for promotion.")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum macro length required for promotion.")
    parser.add_argument("--max-length", type=int, default=5, help="Maximum macro length required for promotion.")
    parser.add_argument("--min-replay-precision", type=float, default=0.5, help="Minimum held-out replay precision required for promotion.")
    parser.add_argument("--min-exact-replays", type=int, default=1, help="Minimum held-out exact replays required for promotion.")
    parser.add_argument("--min-steps-saved", type=int, default=1, help="Minimum held-out steps saved required for promotion.")
    parser.add_argument("--require-binding", action="store_true", help="Only promote macros with free input bindings.")
    parser.add_argument(
        "--allow-generic-click-loops",
        action="store_true",
        help="Allow promotion of generic click-only loops with no clear function-like signal.",
    )
    parser.add_argument("--max-promoted", type=int, default=250, help="Maximum registry entries to keep.")
    return parser.parse_args()


def slugify(value: str) -> str:
    lowered = str(value or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return lowered or "macro"


def split_group_key(group_key: str) -> tuple[str, str]:
    if "::" in str(group_key):
        site, family = str(group_key).split("::", 1)
        return site or "site", family or "workflow"
    return str(group_key) or "site", "workflow"


def summarize_actions(sequence: list[str]) -> str:
    names = [step.split("|", 1)[0].lower() for step in sequence]
    return " -> ".join(names[:6])


def token_field(token: str, field: str) -> str:
    prefix = f"{field}="
    for part in str(token).split("|"):
        if part.startswith(prefix):
            return part[len(prefix) :]
    return ""


def macro_is_function_like(group_key: str, macro: dict, interface: dict) -> bool:
    site, family = split_group_key(group_key)
    del site
    actions = [step.split("|", 1)[0] for step in macro.get("sequence", [])]
    labels = [token_field(step, "label") for step in macro.get("sequence", [])]
    intentful_label = any(label in FUNCTION_LABEL_HINTS for label in labels)
    non_click_action = any(action in {"TYPE", "SELECT", "COPY", "PASTE", "GOTO", "OPEN_TAB", "SWITCH_TAB"} for action in actions)
    if interface["num_inputs"] > 0:
        return True
    if "COPY" in actions and "PASTE" in actions:
        return True
    if family in {"auth", "cart", "checkout", "flight", "lodging", "rental", "reservation", "search"}:
        return intentful_label or non_click_action
    return non_click_action and intentful_label


def infer_name_parts(group_key: str, macro: dict) -> tuple[str, str]:
    site, family = split_group_key(group_key)
    sequence_text = " ".join(macro.get("sequence", [])).lower()
    if "label=login" in sequence_text or "label=password" in sequence_text:
        intent = "login"
    elif "label=add_to_cart" in sequence_text:
        intent = "add_to_cart"
    elif "label=checkout" in sequence_text:
        intent = "checkout"
    elif "copy" in sequence_text and "paste" in sequence_text:
        intent = "copy_and_paste"
    elif "label=search" in sequence_text:
        intent = "search"
    else:
        intent = FAMILY_NAME_HINTS.get(family, "workflow")
    return slugify(site), slugify(intent)


def suggested_name(group_key: str, macro: dict) -> str:
    site_slug, intent_slug = infer_name_parts(group_key, macro)
    return f"{site_slug}_{intent_slug}_{macro['macro_id'].lower()}"


def suggested_description(group_key: str, macro: dict, interface: dict) -> str:
    site, family = split_group_key(group_key)
    noun = family if family != "workflow" else "workflow"
    param_text = f"{interface['num_inputs']} input(s)" if interface["num_inputs"] else "no external inputs"
    return (
        f"{noun} macro for {site} with {param_text}. "
        f"Primitive skeleton: {summarize_actions(list(macro.get('sequence', [])))}."
    )


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    grouped = group_rows(rows, args.group_by or "<all>")

    registry = []
    groups = []

    for group_key, rows_in_group in grouped.items():
        represented_rows = represent_rows(rows_in_group, mode=args.canonicalization_mode)
        sequences = group_sequences(represented_rows)
        if len(sequences) < args.min_group_episodes and args.group_by:
            continue

        train_sequences, eval_sequences = split_sequences(
            sequences,
            train_ratio=args.train_ratio,
            seed=args.seed,
        )
        if not eval_sequences:
            train_sequences = sequences
            eval_sequences = sequences

        macros = mine_frequent_chunks(
            train_sequences,
            min_support=args.min_support,
            max_chunk_len=args.max_chunk_len,
            top_k=args.top_k,
        )
        if not macros:
            continue

        replay = evaluate_macro_replay(
            macros,
            eval_sequences,
            trigger_prefix_len=args.trigger_prefix_len,
        )
        usage = macro_usage_summary(eval_sequences, macros)
        replay_by_id = {item["macro_id"]: item for item in replay["macros"]}
        usage_by_id = {item["macro_id"]: item for item in usage["macros"]}

        promoted = []
        for macro in macros:
            macro_id = macro["macro_id"]
            interface = macro_interface(macro)
            replay_item = replay_by_id.get(macro_id, {})
            usage_item = usage_by_id.get(macro_id, {})
            has_free_inputs = bool(interface["input_bindings"])

            if macro["support"] < args.min_promoted_support:
                continue
            if len(macro["sequence"]) < args.min_length or len(macro["sequence"]) > args.max_length:
                continue
            if replay_item.get("replay_precision", 0.0) < args.min_replay_precision:
                continue
            if replay_item.get("exact_replays", 0) < args.min_exact_replays:
                continue
            if usage_item.get("steps_saved", 0) < args.min_steps_saved:
                continue
            if args.require_binding and not has_free_inputs:
                continue
            if not args.allow_generic_click_loops and not macro_is_function_like(group_key, macro, interface):
                continue

            entry = {
                "group_key": group_key,
                "site": split_group_key(group_key)[0],
                "task_family": split_group_key(group_key)[1],
                "macro_id": macro_id,
                "canonicalization_mode": args.canonicalization_mode,
                "sequence": list(macro["sequence"]),
                "length": len(macro["sequence"]),
                "support": macro["support"],
                "occurrences": macro["occurrences"],
                "has_binding": macro_has_binding(macro),
                "input_bindings": interface["input_bindings"],
                "local_bindings": interface["local_bindings"],
                "num_inputs": interface["num_inputs"],
                "num_local_bindings": interface["num_local_bindings"],
                "trigger_prefix_len": replay_item.get("trigger_prefix_len", args.trigger_prefix_len),
                "candidate_triggers": replay_item.get("candidate_triggers", 0),
                "exact_replays": replay_item.get("exact_replays", 0),
                "replay_precision": replay_item.get("replay_precision", 0.0),
                "episodes_with_exact_replay": replay_item.get("episodes_with_exact_replay", 0),
                "eval_macro_calls": usage_item.get("macro_calls", 0),
                "eval_episodes_with_hits": usage_item.get("episodes_with_hits", 0),
                "eval_steps_saved": usage_item.get("steps_saved", 0),
                "suggested_name": suggested_name(group_key, macro),
                "suggested_description": suggested_description(group_key, macro, interface),
                "naming_status": "heuristic_pending_llm",
            }
            promoted.append(entry)
            registry.append(entry)

        groups.append(
            {
                "group_key": group_key,
                "episodes": len(sequences),
                "train_episodes": len(train_sequences),
                "eval_episodes": len(eval_sequences),
                "num_discovered_macros": len(macros),
                "num_promoted_macros": len(promoted),
                "top_promoted": sorted(
                    promoted,
                    key=lambda item: (-item["num_inputs"], -item["eval_steps_saved"], -item["replay_precision"], item["suggested_name"]),
                )[:10],
            }
        )

    registry.sort(
        key=lambda item: (
            -item["num_inputs"],
            -item["eval_steps_saved"],
            -item["replay_precision"],
            -item["support"],
            item["suggested_name"],
        )
    )
    registry = registry[: args.max_promoted]
    for index, entry in enumerate(registry, start=1):
        entry["registry_id"] = f"R{index:03d}"

    payload = {
        "input_rows": len(rows),
        "group_by": args.group_by or "<all>",
        "canonicalization_mode": args.canonicalization_mode,
        "promotion_criteria": {
            "min_group_episodes": args.min_group_episodes,
            "min_support": args.min_support,
            "min_promoted_support": args.min_promoted_support,
            "min_length": args.min_length,
            "max_length": args.max_length,
            "min_replay_precision": args.min_replay_precision,
            "min_exact_replays": args.min_exact_replays,
            "min_steps_saved": args.min_steps_saved,
            "require_binding": args.require_binding,
            "allow_generic_click_loops": args.allow_generic_click_loops,
        },
        "summary": {
            "groups_reported": len(groups),
            "promoted_macros": len(registry),
            "parameterized_promoted_macros": sum(1 for item in registry if item["num_inputs"] > 0),
            "promoted_steps_saved": sum(item["eval_steps_saved"] for item in registry),
            "promoted_exact_replays": sum(item["exact_replays"] for item in registry),
        },
        "groups": groups,
        "registry": registry,
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
