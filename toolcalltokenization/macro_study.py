from __future__ import annotations

import math
import re
from typing import Dict, Sequence, Tuple

from .trace_utils import (
    evaluate_macro_replay,
    group_sequences,
    load_jsonl,
    macro_has_binding,
    macro_interface,
    macro_usage_summary,
    mine_pair_merge_macros,
    mine_frequent_chunks,
    represent_rows,
    summarize_macro_savings,
)


ECOMMERCE_SITES = {
    "amazon",
    "ebay",
    "gamestop",
    "ikea",
    "instacart",
    "kohls",
    "newegg",
    "rei",
    "target",
    "underarmour",
    "uniqlo",
}

TRAVEL_SITES = {
    "aa",
    "agoda",
    "amtrak",
    "booking",
    "budget",
    "carnival",
    "enterprise",
    "expedia",
    "exploretock",
    "jetblue",
    "kayak",
    "marriott",
    "qatarairways",
    "resy",
    "ryanair",
    "thetrainline",
    "travelzoo",
    "united",
}

TRAVEL_FAMILIES = {"flight", "lodging", "rental", "reservation"}

FUNCTION_LABEL_HINTS = {
    "add_to_cart",
    "checkout",
    "city",
    "date",
    "depart",
    "destination",
    "email",
    "location",
    "login",
    "origin",
    "password",
    "return",
    "search",
    "zip",
}

FAMILY_NAME_HINTS = {
    "auth": "login",
    "cart": "add_to_cart",
    "checkout": "checkout",
    "filter_sort": "filter_or_sort",
    "flight": "flight_search",
    "lodging": "lodging_search",
    "profile": "account_update",
    "rental": "rental_search",
    "reservation": "reservation_flow",
    "search": "search",
}


def split_group_key(group_key: str) -> Tuple[str, str]:
    text = str(group_key or "")
    if "::" in text:
        site, family = text.split("::", 1)
        return site or "site", family or "workflow"
    return text or "site", "workflow"


def cohort_for_group_key(group_key: str) -> str:
    site, family = split_group_key(group_key)
    if site in ECOMMERCE_SITES:
        return "ecommerce"
    if site in TRAVEL_SITES or family in TRAVEL_FAMILIES:
        return "booking_travel"
    if family == "search":
        return "search_local"
    return "other"


def support_threshold(train_episodes: int, policy: str = "loose") -> int:
    normalized = str(policy or "loose").strip().lower()
    count = max(1, int(train_episodes))
    if normalized == "loose":
        return min(2, count)
    if normalized == "strict":
        return min(3, count)
    if normalized == "adaptive":
        return min(max(2, int(math.ceil(count * 0.25))), count)
    raise ValueError(f"Unsupported support policy: {policy!r}")


def fixed_holdout_split(
    sequences: Dict[str, Sequence[str]],
    eval_ratio: float = 0.2,
    min_eval_episodes: int = 2,
) -> Tuple[Dict[str, Sequence[str]], Dict[str, Sequence[str]]]:
    episode_ids = sorted(sequences)
    if not episode_ids:
        return {}, {}
    if len(episode_ids) <= min_eval_episodes:
        return dict(sequences), dict(sequences)
    eval_count = max(min_eval_episodes, int(math.ceil(len(episode_ids) * eval_ratio)))
    eval_count = min(eval_count, len(episode_ids) - 1)
    eval_ids = set(episode_ids[-eval_count:])
    train = {episode_id: list(sequences[episode_id]) for episode_id in episode_ids if episode_id not in eval_ids}
    eval_sequences = {episode_id: list(sequences[episode_id]) for episode_id in episode_ids if episode_id in eval_ids}
    return train, eval_sequences


def token_field(token: str, field: str) -> str:
    prefix = f"{field}="
    for part in str(token).split("|"):
        if part.startswith(prefix):
            return part[len(prefix) :]
    return ""


def summarize_actions(sequence: Sequence[str]) -> str:
    names = [str(step).split("|", 1)[0].lower() for step in sequence]
    return " -> ".join(names[:6])


def slugify(value: str) -> str:
    lowered = str(value or "").strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return lowered or "macro"


def macro_is_function_like(group_key: str, macro: dict, interface: dict) -> bool:
    _, family = split_group_key(group_key)
    actions = [str(step).split("|", 1)[0] for step in macro.get("sequence", [])]
    labels = [token_field(str(step), "label") for step in macro.get("sequence", [])]
    intentful_label = any(label in FUNCTION_LABEL_HINTS for label in labels)
    non_click_action = any(
        action in {"COPY", "GOTO", "OPEN_TAB", "PASTE", "SELECT", "SWITCH_TAB", "TYPE"}
        for action in actions
    )
    if interface["num_inputs"] > 0:
        return True
    if "COPY" in actions and "PASTE" in actions:
        return True
    if family in {"auth", "cart", "checkout", "flight", "lodging", "rental", "reservation", "search"}:
        return intentful_label or non_click_action
    return non_click_action and intentful_label


def infer_name_parts(group_key: str, macro: dict) -> Tuple[str, str]:
    site, family = split_group_key(group_key)
    sequence_text = " ".join(str(step) for step in macro.get("sequence", [])).lower()
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


def heuristic_macro_name(group_key: str, macro: dict) -> str:
    site_slug, intent_slug = infer_name_parts(group_key, macro)
    return f"{site_slug}_{intent_slug}_{str(macro['macro_id']).lower()}"


def heuristic_macro_description(group_key: str, macro: dict, interface: dict) -> str:
    site, family = split_group_key(group_key)
    noun = family if family != "workflow" else "workflow"
    param_text = f"{interface['num_inputs']} input(s)" if interface["num_inputs"] else "no external inputs"
    return (
        f"{noun} macro for {site} with {param_text}. "
        f"Primitive skeleton: {summarize_actions(list(macro.get('sequence', [])))}."
    )


def promote_candidate_macros_for_group(
    group_key: str,
    macros: Sequence[dict],
    eval_sequences: Dict[str, Sequence[str]],
    *,
    canonicalization_mode: str = "dataflow_coarse",
    trigger_prefix_len: int = 2,
    min_length: int = 2,
    max_length: int = 6,
    min_replay_precision: float = 0.5,
    min_exact_replays: int = 1,
    min_steps_saved: int = 1,
    min_promoted_support: int = 2,
    require_binding: bool = False,
    allow_generic_click_loops: bool = False,
) -> dict:
    promoted_support = int(min_promoted_support)
    replay = evaluate_macro_replay(macros, {episode_id: list(sequence) for episode_id, sequence in eval_sequences.items()}, trigger_prefix_len=trigger_prefix_len)
    usage = macro_usage_summary({episode_id: list(sequence) for episode_id, sequence in eval_sequences.items()}, macros)
    replay_by_id = {item["macro_id"]: item for item in replay["macros"]}
    usage_by_id = {item["macro_id"]: item for item in usage["macros"]}

    registry = []
    for macro in macros:
        macro_id = str(macro["macro_id"])
        interface = macro_interface(macro)
        replay_item = replay_by_id.get(macro_id, {})
        usage_item = usage_by_id.get(macro_id, {})
        has_free_inputs = bool(interface["input_bindings"])

        if macro["support"] < promoted_support:
            continue
        if len(macro["sequence"]) < min_length or len(macro["sequence"]) > max_length:
            continue
        if replay_item.get("replay_precision", 0.0) < min_replay_precision:
            continue
        if replay_item.get("exact_replays", 0) < min_exact_replays:
            continue
        if usage_item.get("steps_saved", 0) < min_steps_saved:
            continue
        if require_binding and not has_free_inputs:
            continue
        if not allow_generic_click_loops and not macro_is_function_like(group_key, macro, interface):
            continue

        entry = {
            "group_key": group_key,
            "site": split_group_key(group_key)[0],
            "task_family": split_group_key(group_key)[1],
            "macro_id": macro_id,
            "canonicalization_mode": canonicalization_mode,
            "sequence": list(macro["sequence"]),
            "length": len(macro["sequence"]),
            "support": macro["support"],
            "occurrences": macro["occurrences"],
            "has_binding": macro_has_binding(macro),
            "input_bindings": interface["input_bindings"],
            "local_bindings": interface["local_bindings"],
            "num_inputs": interface["num_inputs"],
            "num_local_bindings": interface["num_local_bindings"],
            "trigger_prefix_len": replay_item.get("trigger_prefix_len", trigger_prefix_len),
            "candidate_triggers": replay_item.get("candidate_triggers", 0),
            "exact_replays": replay_item.get("exact_replays", 0),
            "replay_precision": replay_item.get("replay_precision", 0.0),
            "episodes_with_exact_replay": replay_item.get("episodes_with_exact_replay", 0),
            "eval_macro_calls": usage_item.get("macro_calls", 0),
            "eval_episodes_with_hits": usage_item.get("episodes_with_hits", 0),
            "eval_steps_saved": usage_item.get("steps_saved", 0),
            "suggested_name": heuristic_macro_name(group_key, macro),
            "suggested_description": heuristic_macro_description(group_key, macro, interface),
            "naming_status": "heuristic_pending_llm",
        }
        registry.append(entry)

    registry.sort(
        key=lambda item: (
            -item["num_inputs"],
            -item["eval_steps_saved"],
            -item["replay_precision"],
            -item["support"],
            item["suggested_name"],
        )
    )
    for index, entry in enumerate(registry, start=1):
        entry["registry_id"] = f"R{index:03d}"

    savings = summarize_macro_savings({episode_id: list(sequence) for episode_id, sequence in eval_sequences.items()}, registry)
    return {
        "group_key": group_key,
        "registry": registry,
        "discovered_macros": macros,
        "replay": replay,
        "usage": usage,
        "savings": savings,
    }


def promote_macros_for_group(
    group_key: str,
    train_sequences: Dict[str, Sequence[str]],
    eval_sequences: Dict[str, Sequence[str]],
    *,
    canonicalization_mode: str = "dataflow_coarse",
    top_k: int = 25,
    max_chunk_len: int = 6,
    min_support: int = 2,
    min_promoted_support: int | None = None,
    trigger_prefix_len: int = 2,
    min_length: int = 2,
    max_length: int = 6,
    min_replay_precision: float = 0.5,
    min_exact_replays: int = 1,
    min_steps_saved: int = 1,
    require_binding: bool = False,
    allow_generic_click_loops: bool = False,
) -> dict:
    macros = mine_frequent_chunks(
        {episode_id: list(sequence) for episode_id, sequence in train_sequences.items()},
        min_support=min_support,
        max_chunk_len=max_chunk_len,
        top_k=top_k,
    )
    promoted_support = min_support if min_promoted_support is None else min_promoted_support
    return promote_candidate_macros_for_group(
        group_key,
        macros,
        eval_sequences,
        canonicalization_mode=canonicalization_mode,
        trigger_prefix_len=trigger_prefix_len,
        min_length=min_length,
        max_length=max_length,
        min_replay_precision=min_replay_precision,
        min_exact_replays=min_exact_replays,
        min_steps_saved=min_steps_saved,
        min_promoted_support=promoted_support,
        require_binding=require_binding,
        allow_generic_click_loops=allow_generic_click_loops,
    )


def promote_pair_merge_macros_for_group(
    group_key: str,
    train_sequences: Dict[str, Sequence[str]],
    eval_sequences: Dict[str, Sequence[str]],
    *,
    canonicalization_mode: str = "dataflow_coarse",
    top_k: int = 25,
    num_merges: int = 50,
    min_occurrences: int = 2,
    min_support: int = 2,
    min_promoted_support: int | None = None,
    trigger_prefix_len: int = 2,
    min_length: int = 2,
    max_length: int = 6,
    min_replay_precision: float = 0.5,
    min_exact_replays: int = 1,
    min_steps_saved: int = 1,
    require_binding: bool = False,
    allow_generic_click_loops: bool = False,
) -> dict:
    macros = mine_pair_merge_macros(
        {episode_id: list(sequence) for episode_id, sequence in train_sequences.items()},
        num_merges=num_merges,
        min_occurrences=min_occurrences,
        min_support=min_support,
        top_k=top_k,
        min_length=min_length,
        max_length=max_length,
    )
    promoted_support = min_support if min_promoted_support is None else min_promoted_support
    return promote_candidate_macros_for_group(
        group_key,
        macros,
        eval_sequences,
        canonicalization_mode=canonicalization_mode,
        trigger_prefix_len=trigger_prefix_len,
        min_length=min_length,
        max_length=max_length,
        min_replay_precision=min_replay_precision,
        min_exact_replays=min_exact_replays,
        min_steps_saved=min_steps_saved,
        min_promoted_support=promoted_support,
        require_binding=require_binding,
        allow_generic_click_loops=allow_generic_click_loops,
    )


def load_grouped_sequences(
    input_path: str,
    group_by: str,
    canonicalization_mode: str = "dataflow_coarse",
) -> Dict[str, Dict[str, Sequence[str]]]:
    rows = load_jsonl(input_path)
    if rows and not rows[0].get("canonical_action"):
        rows = represent_rows(rows, mode=canonicalization_mode)
    grouped_rows: Dict[str, list[dict]] = {}
    if group_by == "website":
        grouped_rows = {}
        for row in rows:
            key = str(row.get("website") or "<missing>")
            grouped_rows.setdefault(key, []).append(row)
    else:
        from .trace_utils import group_rows

        grouped_rows = group_rows(rows, group_by)
    return {group_key: group_sequences(group_rows_items) for group_key, group_rows_items in grouped_rows.items()}
