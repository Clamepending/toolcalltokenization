from __future__ import annotations

from collections import Counter
from typing import Dict, List, Sequence


def macro_sort_key(macro: dict) -> tuple:
    return (
        -float(macro.get("replay_precision", 0.0)),
        -int(macro.get("num_inputs", 0)),
        -len(macro.get("sequence", [])),
        -int(macro.get("support", 0)),
        str(macro.get("suggested_name", macro.get("macro_id", ""))),
    )


def candidate_macros(sequence: Sequence[str], index: int, macros: Sequence[dict]) -> List[dict]:
    candidates = []
    for macro in macros:
        steps = list(macro.get("sequence", []))
        if len(steps) < 2:
            continue
        prefix_len = min(int(macro.get("trigger_prefix_len", 1)), len(steps) - 1)
        if list(sequence[index : index + prefix_len]) == steps[:prefix_len]:
            candidates.append(macro)
    candidates.sort(key=macro_sort_key)
    return candidates


def simulate_macro_agent_on_sequence(sequence: Sequence[str], macros: Sequence[dict]) -> dict:
    index = 0
    attempted_macro_calls = 0
    successful_macro_calls = 0
    failed_macro_calls = 0
    primitive_actions = 0
    macro_action_counts: Counter = Counter()
    failed_macro_counts: Counter = Counter()

    while index < len(sequence):
        candidates = candidate_macros(sequence, index, macros)
        if not candidates:
            primitive_actions += 1
            index += 1
            continue

        macro = candidates[0]
        steps = list(macro.get("sequence", []))
        attempted_macro_calls += 1
        if list(sequence[index : index + len(steps)]) == steps:
            successful_macro_calls += 1
            macro_action_counts[str(macro.get("suggested_name", macro.get("macro_id", "macro")))] += 1
            index += len(steps)
            continue

        failed_macro_calls += 1
        failed_macro_counts[str(macro.get("suggested_name", macro.get("macro_id", "macro")))] += 1
        primitive_actions += 1
        index += 1

    total_agent_decisions = attempted_macro_calls + primitive_actions
    baseline_decisions = len(sequence)
    steps_saved = baseline_decisions - total_agent_decisions
    return {
        "primitive_steps": baseline_decisions,
        "agent_decisions": total_agent_decisions,
        "steps_saved": steps_saved,
        "decision_reduction_ratio": round(steps_saved / baseline_decisions, 4) if baseline_decisions else 0.0,
        "attempted_macro_calls": attempted_macro_calls,
        "successful_macro_calls": successful_macro_calls,
        "failed_macro_calls": failed_macro_calls,
        "macro_success_rate": round(successful_macro_calls / attempted_macro_calls, 4) if attempted_macro_calls else 0.0,
        "macro_hits": dict(macro_action_counts),
        "failed_macro_hits": dict(failed_macro_counts),
    }


def simulate_macro_agent(
    grouped_sequences: Dict[str, Dict[str, List[str]]],
    registry_by_group: Dict[str, List[dict]],
) -> dict:
    group_reports = []
    total_primitive = 0
    total_decisions = 0
    total_attempted = 0
    total_successful = 0
    total_failed = 0
    groups_with_macros_available = 0
    groups_with_attempts = 0
    groups_with_successes = 0

    for group_key, sequences in sorted(grouped_sequences.items()):
        macros = registry_by_group.get(group_key, [])
        if macros:
            groups_with_macros_available += 1
        episodes = []
        for episode_id, sequence in sorted(sequences.items()):
            summary = simulate_macro_agent_on_sequence(sequence, macros)
            total_primitive += summary["primitive_steps"]
            total_decisions += summary["agent_decisions"]
            total_attempted += summary["attempted_macro_calls"]
            total_successful += summary["successful_macro_calls"]
            total_failed += summary["failed_macro_calls"]
            episodes.append({"episode_id": episode_id, **summary})

        if not episodes:
            continue

        group_attempts = sum(item["attempted_macro_calls"] for item in episodes)
        group_successes = sum(item["successful_macro_calls"] for item in episodes)
        if group_attempts:
            groups_with_attempts += 1
        if group_successes:
            groups_with_successes += 1

        group_reports.append(
            {
                "group_key": group_key,
                "macros_available": len(macros),
                "episodes": episodes,
                "summary": {
                    "primitive_steps": sum(item["primitive_steps"] for item in episodes),
                    "agent_decisions": sum(item["agent_decisions"] for item in episodes),
                    "steps_saved": sum(item["steps_saved"] for item in episodes),
                    "attempted_macro_calls": sum(item["attempted_macro_calls"] for item in episodes),
                    "successful_macro_calls": sum(item["successful_macro_calls"] for item in episodes),
                    "failed_macro_calls": sum(item["failed_macro_calls"] for item in episodes),
                    "macro_success_rate": round(
                        sum(item["successful_macro_calls"] for item in episodes)
                        / sum(item["attempted_macro_calls"] for item in episodes),
                        4,
                    )
                    if sum(item["attempted_macro_calls"] for item in episodes)
                    else 0.0,
                    "decision_reduction_ratio": round(
                        sum(item["steps_saved"] for item in episodes)
                        / sum(item["primitive_steps"] for item in episodes),
                        4,
                    )
                    if sum(item["primitive_steps"] for item in episodes)
                    else 0.0,
                },
            }
        )

    return {
        "summary": {
            "groups_evaluated": len(group_reports),
            "groups_with_macros_available": groups_with_macros_available,
            "groups_with_attempted_macro_calls": groups_with_attempts,
            "groups_with_successful_macro_calls": groups_with_successes,
            "primitive_steps": total_primitive,
            "agent_decisions": total_decisions,
            "steps_saved": total_primitive - total_decisions,
            "decision_reduction_ratio": round((total_primitive - total_decisions) / total_primitive, 4)
            if total_primitive
            else 0.0,
            "attempted_macro_calls": total_attempted,
            "successful_macro_calls": total_successful,
            "failed_macro_calls": total_failed,
            "macro_success_rate": round(total_successful / total_attempted, 4) if total_attempted else 0.0,
        },
        "groups": group_reports,
    }
