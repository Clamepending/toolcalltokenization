#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.trace_utils import dump_json


DOCS_DATA = ROOT / "docs" / "data"
DOCS_FIGURES = ROOT / "docs" / "figures"


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def percent(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 2)


def build_summary() -> dict:
    mind2web = load_json(ROOT / "outputs" / "mind2web_site_task_family_macro_agent_sim.json")
    mind2web_hierarchy = load_json(ROOT / "outputs" / "mind2web_registry_hierarchy_eval.json")
    miniwob_replay = load_json(ROOT / "outputs" / "miniwob_live_v3_stable_benchmark.json")
    workarena_service_catalog = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_benchmark.json")
    workarena_service_catalog_sweep = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_split_sweep.json")
    workarena_selector_oracle = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_oracle_selector_v2.json")
    workarena_selector_semantic_guard = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_semantic_guard_selector_v2.json")
    workarena_selector_semantic_noguard = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_semantic_noguard_selector_v2.json")
    workarena_selector_learned = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_learned_noguard_selector_v2_e20.json")
    mind2web_selector_oracle = load_json(ROOT / "outputs" / "mind2web_site_task_family_oracle_selector.json")
    mind2web_selector_learned = load_json(ROOT / "outputs" / "mind2web_site_task_family_learned_noguard_selector.json")
    miniwob_local_oracle = load_json(ROOT / "outputs" / "miniwob_live_v3_policy_oracle_v2_macro_policy_benchmark.json")
    miniwob_global_exact = load_json(ROOT / "outputs" / "miniwob_live_v3_global_oracle_macro_policy_benchmark.json")
    miniwob_global_trigger2 = load_json(ROOT / "outputs" / "miniwob_live_v3_global_trigger_macro_policy_benchmark.json")
    miniwob_global_trigger1 = load_json(ROOT / "outputs" / "miniwob_live_v3_global_trigger_p1_v3_macro_policy_benchmark.json")
    miniwob_global_trigger1_r06 = load_json(ROOT / "outputs" / "miniwob_live_v3_global_trigger_p1_r06_macro_policy_benchmark.json")
    miniwob_global_trigger1_r10 = load_json(ROOT / "outputs" / "miniwob_live_v3_global_trigger_p1_r10_macro_policy_benchmark.json")
    miniwob_global_taskregistry_oracle = load_json(ROOT / "outputs" / "miniwob_live_v3_global_taskregistry_oracle_stable_macro_policy_benchmark.json")
    miniwob_global_taskregistry_trigger = load_json(ROOT / "outputs" / "miniwob_live_v3_global_taskregistry_trigger_stable_macro_policy_benchmark.json")
    miniwob_semantic_global_noguard = load_json(ROOT / "outputs" / "miniwob_live_v3_semantic_global_noguard_stable_m0_semantic_policy_benchmark.json")
    miniwob_semantic_global_guard = load_json(ROOT / "outputs" / "miniwob_live_v3_semantic_global_guard_v3_stable_m0_semantic_policy_benchmark.json")
    miniwob_semantic_global_guard_bias = load_json(ROOT / "outputs" / "miniwob_live_v3_semantic_global_guard_v4_stable_mneg1_semantic_policy_benchmark.json")
    miniwob_learned_global_guard = load_json(ROOT / "outputs" / "miniwob_live_v3_learned_global_guard_stable_learned_policy_benchmark.json")
    miniwob_learned_global_noguard = load_json(ROOT / "outputs" / "miniwob_live_v3_learned_global_noguard_stable_learned_policy_benchmark.json")
    miniwob_llm_global_guard = load_json(ROOT / "outputs" / "miniwob_live_v3_llm_global_guard_stable_v2_llm_policy_benchmark.json")
    miniwob_llm_global_noguard = load_json(ROOT / "outputs" / "miniwob_live_v3_llm_global_noguard_stable_v2_llm_policy_benchmark.json")
    trigger1_registry = load_json(ROOT / "outputs" / "miniwob_live_v3_global_trigger_p1_v3_macro_registry.json")
    workarena_selector_llm_guard = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_llm_guard_selector.json")
    workarena_selector_llm_guard_v2 = load_json(ROOT / "outputs" / "workarena_service_catalog_v1_llm_guard_selector_v2.json")

    mind2web_covered_steps = sum(
        group["summary"]["primitive_steps"]
        for group in mind2web["groups"]
        if group["summary"]["attempted_macro_calls"] > 0
    )
    mind2web_all_steps = sum(group["summary"]["primitive_steps"] for group in mind2web["groups"])

    failed_by_macro = {}
    failed_by_task = {}
    attempted_by_macro = {}
    for group in miniwob_global_trigger1["groups"]:
        for episode in group["episodes"]:
            task_name = str(episode["episode_id"]).split("::")[0]
            for macro_id in episode.get("attempted_macro_ids", []):
                attempted_by_macro[macro_id] = attempted_by_macro.get(macro_id, 0) + 1
            for macro_id in episode.get("failed_macro_ids", []):
                failed_by_macro[macro_id] = failed_by_macro.get(macro_id, 0) + 1
                task_counts = failed_by_task.setdefault(task_name, {})
                task_counts[macro_id] = task_counts.get(macro_id, 0) + 1

    macro_sequences = {
        entry["macro_id"]: " -> ".join(entry["sequence"])
        for entry in trigger1_registry["registry"]
    }

    return {
        "overall": {
            "mind2web_site_task_family": {
                "decision_reduction_ratio": mind2web["summary"]["decision_reduction_ratio"],
                "macro_success_rate": mind2web["summary"]["macro_success_rate"],
                "primitive_steps": mind2web["summary"]["primitive_steps"],
                "steps_saved": mind2web["summary"]["steps_saved"],
                "coverage_ratio": round(mind2web_covered_steps / mind2web_all_steps, 4) if mind2web_all_steps else 0.0,
                "groups_with_macros_available": mind2web["summary"]["groups_with_macros_available"],
                "groups_evaluated": mind2web["summary"]["groups_evaluated"],
            },
            "mind2web_best_hierarchy": next(
                item["summary"] for item in mind2web_hierarchy["variants"] if item["name"] == "exact_then_site_r07"
            ),
            "mind2web_selector_oracle": mind2web_selector_oracle["summary"],
            "mind2web_selector_learned": mind2web_selector_learned["summary"],
            "workarena_service_catalog": workarena_service_catalog["summary"],
            "workarena_service_catalog_sweep": workarena_service_catalog_sweep,
            "workarena_selector_oracle": workarena_selector_oracle["summary"],
            "workarena_selector_semantic_guard": workarena_selector_semantic_guard["summary"],
            "workarena_selector_semantic_noguard": workarena_selector_semantic_noguard["summary"],
            "workarena_selector_learned": workarena_selector_learned["summary"],
            "workarena_selector_llm_guard": workarena_selector_llm_guard["summary"],
            "workarena_selector_llm_guard_v2": workarena_selector_llm_guard_v2["summary"],
            "miniwob_stable_replay_upper_bound": miniwob_replay["summary"],
            "miniwob_local_oracle": miniwob_local_oracle["summary"],
            "miniwob_global_exact": miniwob_global_exact["summary"],
            "miniwob_global_trigger2": miniwob_global_trigger2["summary"],
            "miniwob_global_trigger1": miniwob_global_trigger1["summary"],
            "miniwob_global_taskregistry_oracle": miniwob_global_taskregistry_oracle["summary"],
            "miniwob_global_taskregistry_trigger": miniwob_global_taskregistry_trigger["summary"],
            "miniwob_semantic_global_noguard": miniwob_semantic_global_noguard["summary"],
            "miniwob_semantic_global_guard": miniwob_semantic_global_guard["summary"],
            "miniwob_semantic_global_guard_bias": miniwob_semantic_global_guard_bias["summary"],
            "miniwob_learned_global_guard": miniwob_learned_global_guard["summary"],
            "miniwob_learned_global_noguard": miniwob_learned_global_noguard["summary"],
            "miniwob_llm_global_guard": miniwob_llm_global_guard["summary"],
            "miniwob_llm_global_noguard": miniwob_llm_global_noguard["summary"],
        },
        "mind2web_hierarchy_sweep": mind2web_hierarchy["variants"],
        "workarena_service_catalog_sweep": workarena_service_catalog_sweep["runs"],
        "workarena_selector_sweep": [
            {"label": "Replay upper bound", **workarena_service_catalog["summary"]},
            {"label": "Oracle selector", **workarena_selector_oracle["summary"]},
            {"label": "Learned selector", **workarena_selector_learned["summary"]},
            {"label": "LLM + guard", **workarena_selector_llm_guard["summary"]},
            {"label": "Semantic + guard", **workarena_selector_semantic_guard["summary"]},
            {"label": "Semantic no guard", **workarena_selector_semantic_noguard["summary"]},
        ],
        "global_trigger_sweep": [
            {"label": "Global exact", **miniwob_global_exact["summary"]},
            {"label": "Global 2-step", **miniwob_global_trigger2["summary"]},
            {"label": "Global 1-step r>=0.5", **miniwob_global_trigger1["summary"]},
            {"label": "Global 1-step r>=0.6", **miniwob_global_trigger1_r06["summary"]},
            {"label": "Global 1-step r=1.0", **miniwob_global_trigger1_r10["summary"]},
        ],
        "semantic_policy_sweep": [
            {"label": "Semantic no guard", **miniwob_semantic_global_noguard["summary"]},
            {"label": "Semantic + guard", **miniwob_semantic_global_guard["summary"]},
            {"label": "Semantic + guard + macro bias", **miniwob_semantic_global_guard_bias["summary"]},
            {"label": "Learned no guard", **miniwob_learned_global_noguard["summary"]},
            {"label": "Learned + guard", **miniwob_learned_global_guard["summary"]},
            {"label": "Prefix 2-step", **miniwob_global_taskregistry_trigger["summary"]},
            {"label": "Exact upper bound", **miniwob_global_taskregistry_oracle["summary"]},
        ],
        "llm_policy_sweep": {
            "miniwob": [
                {"label": "LLM no guard", **miniwob_llm_global_noguard["summary"]},
                {"label": "LLM + 1-step guard", **miniwob_llm_global_guard["summary"]},
                {"label": "Learned selector", **miniwob_learned_global_noguard["summary"]},
                {"label": "Exact upper bound", **miniwob_global_taskregistry_oracle["summary"]},
            ],
            "workarena": [
                {"label": "LLM + guard", **workarena_selector_llm_guard["summary"]},
                {"label": "LLM + guard + detailed steps", **workarena_selector_llm_guard_v2["summary"]},
                {"label": "Learned selector", **workarena_selector_learned["summary"]},
                {"label": "Oracle selector", **workarena_selector_oracle["summary"]},
                {"label": "Replay upper bound", **workarena_service_catalog["summary"]},
            ],
        },
        "global_trigger_failures": {
            "failed_by_macro": failed_by_macro,
            "failed_by_task": failed_by_task,
            "attempted_by_macro": attempted_by_macro,
            "macro_sequences": macro_sequences,
        },
    }


def style_matplotlib() -> None:
    plt.style.use("default")
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 160,
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
        }
    )


def plot_overall(summary: dict) -> Path:
    scenarios = [
        ("Mind2Web\nsite+task\noffline", summary["overall"]["mind2web_site_task_family"]["decision_reduction_ratio"], "#c46b32"),
        ("Mind2Web\nhierarchy\nbest", summary["overall"]["mind2web_best_hierarchy"]["decision_reduction_ratio"], "#bc4749"),
        ("WorkArena\nservice catalog\nreal-browser", summary["overall"]["workarena_service_catalog_sweep"]["mean_decision_reduction_ratio"], "#8a5cf6"),
        ("MiniWoB\nreplay\nupper bound", summary["overall"]["miniwob_stable_replay_upper_bound"]["decision_reduction_ratio"], "#1f77b4"),
        ("MiniWoB\nlocal live\n2-step", summary["overall"]["miniwob_local_oracle"]["decision_reduction_ratio"], "#2a9d8f"),
        ("MiniWoB\nglobal live\n2-step", summary["overall"]["miniwob_global_trigger2"]["decision_reduction_ratio"], "#457b9d"),
        ("MiniWoB\nglobal live\n1-step", summary["overall"]["miniwob_global_trigger1"]["decision_reduction_ratio"], "#d62828"),
    ]
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    labels = [item[0] for item in scenarios]
    values = [percent(item[1]) for item in scenarios]
    colors = [item[2] for item in scenarios]
    bars = ax.bar(labels, values, color=colors, width=0.72)
    ax.set_ylabel("Decision Reduction (%)")
    ax.set_title("Action Chunking Works in Dense Local Settings, Then Degrades with Shared Vocabularies")
    ax.set_ylim(0, max(values) * 1.25)
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 1.0, f"{value:.1f}%", ha="center", va="bottom")

    ax.text(
        0,
        values[0] + 4.5,
        "Coverage only 13.9%\nof held-out steps",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#7a3e15",
    )
    ax.text(
        1,
        values[1] + 4.5,
        "Site fallback doubles\ncovered steps",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#7f1d1d",
    )
    ax.text(
        2,
        values[2] + 4.5,
        "18 real ServiceNow\nepisodes, mean over\n5 split seeds",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#5b3c99",
    )
    ax.text(
        5,
        values[5] + 4.5,
        "Shared action space",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#1d3557",
    )
    ax.text(
        6,
        values[6] + 4.5,
        "Loose trigger adds\nfalse macro calls",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#8d1f1f",
    )
    fig.tight_layout()
    output = DOCS_FIGURES / "action_chunking_overview.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_mind2web_hierarchy(summary: dict) -> Path:
    variants = summary["mind2web_hierarchy_sweep"]
    labels = {
        "exact_only": "Site+task only",
        "site_only": "Site only",
        "family_only": "Family only",
        "exact_then_site_r05": "Site+task -> site (r>=0.5)",
        "exact_then_site_r07": "Site+task -> site (r>=0.7)",
        "exact_then_site_then_family_r05": "Site+task -> site -> family",
    }
    ordered = [item for item in variants if item["name"] in labels]
    names = [labels[item["name"]] for item in ordered]
    reductions = [percent(item["summary"]["decision_reduction_ratio"]) for item in ordered]
    coverage = [percent(item["summary"]["coverage_ratio"]) for item in ordered]
    macro_success = [percent(item["summary"]["macro_success_rate"]) for item in ordered]

    fig, axes = plt.subplots(2, 1, figsize=(10.5, 7.4), sharex=True, gridspec_kw={"height_ratios": [2, 1.6]})
    bars = axes[0].bar(names, reductions, color=["#bc6c25", "#dda15e", "#e9c46a", "#c1121f", "#9a031e", "#6d597a"])
    axes[0].set_ylabel("Decision Reduction (%)")
    axes[0].set_title("Mind2Web Coverage Improves with Site Fallback, but Family Fallback Mostly Adds Noise")
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].set_ylim(0, max(reductions) * 1.35 if reductions else 1)
    for bar, value in zip(bars, reductions):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.12, f"{value:.2f}%", ha="center", va="bottom", fontsize=9)

    axes[1].bar(names, coverage, color="#8ecae6", alpha=0.85, label="Covered held-out steps")
    axes[1].set_ylabel("Coverage (%)")
    axes[1].grid(axis="y", alpha=0.25)
    twin = axes[1].twinx()
    twin.plot(names, macro_success, color="#264653", marker="o", linewidth=2, label="Macro success rate")
    twin.set_ylabel("Macro Success (%)")
    twin.set_ylim(0, 110)
    for idx, value in enumerate(macro_success):
        twin.text(idx, value + 3, f"{value:.1f}%", ha="center", va="bottom", color="#264653", fontsize=8)

    axes[1].tick_params(axis="x", rotation=18)
    fig.tight_layout()
    output = DOCS_FIGURES / "mind2web_hierarchy_sweep.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_workarena_service_catalog(summary: dict) -> Path:
    runs = summary["workarena_service_catalog_sweep"]
    labels = [f"Seed {item['split_seed']}" for item in runs]
    reductions = [percent(item["decision_reduction_ratio"]) for item in runs]
    registry_counts = [int(item["registry_count"]) for item in runs]
    mean_reduction = percent(summary["overall"]["workarena_service_catalog_sweep"]["mean_decision_reduction_ratio"])

    fig, axes = plt.subplots(2, 1, figsize=(9.8, 6.8), sharex=True, gridspec_kw={"height_ratios": [2, 1.4]})
    bars = axes[0].bar(labels, reductions, color="#8a5cf6")
    axes[0].axhline(mean_reduction, color="#3c096c", linestyle="--", linewidth=1.8)
    axes[0].set_ylabel("Decision Reduction (%)")
    axes[0].set_title("WorkArena Service-Catalog Cheat Traces Produce Long, Reusable Real-Browser Macros")
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].set_ylim(0, max(reductions) * 1.25 if reductions else 1)
    for bar, value in zip(bars, reductions):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.7, f"{value:.1f}%", ha="center", va="bottom")
    axes[0].text(len(labels) - 0.35, mean_reduction + 1.0, f"mean {mean_reduction:.1f}%", color="#3c096c", ha="right")

    axes[1].bar(labels, registry_counts, color="#c77dff", alpha=0.9)
    axes[1].set_ylabel("Promoted Macros")
    axes[1].set_xlabel("Train/Eval Split Seed")
    axes[1].grid(axis="y", alpha=0.25)
    for idx, value in enumerate(registry_counts):
        axes[1].text(idx, value + 0.2, str(value), ha="center", va="bottom")

    fig.tight_layout()
    output = DOCS_FIGURES / "workarena_service_catalog_split_sweep.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_workarena_selector_sweep(summary: dict) -> Path:
    sweep = summary["workarena_selector_sweep"]
    labels = [item["label"] for item in sweep]
    reductions = [percent(item["decision_reduction_ratio"]) for item in sweep]
    failed_calls = [int(item.get("failed_macro_calls", 0)) for item in sweep]
    macro_success = [percent(item.get("macro_success_rate", 1.0 if item["label"] == "Replay upper bound" else 0.0)) for item in sweep]

    fig, axes = plt.subplots(2, 1, figsize=(10.2, 7.0), sharex=True, gridspec_kw={"height_ratios": [2, 1.5]})
    colors = ["#6a994e", "#457b9d", "#5a189a", "#2a9d8f", "#b23a48"]

    bars = axes[0].bar(labels, reductions, color=colors)
    axes[0].set_ylabel("Decision Reduction (%)")
    axes[0].set_title("On WorkArena, Selection Quality Accounts for Most of the Gap Between Replay Compression and Real Macro Use")
    ymin = min(0, min(reductions) * 1.2)
    ymax = max(reductions) * 1.25
    axes[0].set_ylim(ymin, ymax)
    axes[0].grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, reductions):
        offset = 1.0 if value >= 0 else -2.0
        va = "bottom" if value >= 0 else "top"
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + offset, f"{value:.1f}%", ha="center", va=va)

    axes[1].bar(labels, failed_calls, color="#e76f51", alpha=0.85, label="Failed macro calls")
    axes[1].set_ylabel("Failed Macro Calls")
    axes[1].grid(axis="y", alpha=0.25)
    twin = axes[1].twinx()
    twin.plot(labels, macro_success, color="#264653", marker="o", linewidth=2, label="Macro success rate")
    twin.set_ylabel("Macro Success (%)")
    twin.set_ylim(0, 110)
    for idx, value in enumerate(macro_success):
        twin.text(idx, value + 3, f"{value:.1f}%", ha="center", va="bottom", color="#264653", fontsize=9)

    axes[1].tick_params(axis="x", rotation=14)
    fig.tight_layout()
    output = DOCS_FIGURES / "workarena_selector_sweep.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_global_sweep(summary: dict) -> Path:
    sweep = summary["global_trigger_sweep"]
    labels = [item["label"] for item in sweep]
    reductions = [percent(item["decision_reduction_ratio"]) for item in sweep]
    macro_success = [percent(item.get("macro_success_rate", 0.0)) for item in sweep]
    failed_calls = [int(item.get("failed_macro_calls", 0)) for item in sweep]

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1.5]})

    bars = axes[0].bar(labels, reductions, color=["#457b9d", "#2a9d8f", "#d62828", "#f4a261", "#6a994e"])
    axes[0].set_ylabel("Decision Reduction (%)")
    axes[0].set_title("2-Step Triggers Beat Stricter Replay Thresholds in a Shared Macro Vocabulary")
    axes[0].grid(axis="y", alpha=0.25)
    axes[0].set_ylim(0, max(reductions) * 1.25)
    for bar, value in zip(bars, reductions):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 0.8, f"{value:.1f}%", ha="center", va="bottom")

    axes[1].bar(labels, failed_calls, color="#e76f51", alpha=0.85, label="Failed macro calls")
    axes[1].set_ylabel("Failed Macro Calls")
    axes[1].grid(axis="y", alpha=0.25)
    twin = axes[1].twinx()
    twin.plot(labels, macro_success, color="#264653", marker="o", linewidth=2, label="Macro success rate")
    twin.set_ylabel("Macro Success (%)")
    twin.set_ylim(0, 110)
    for idx, value in enumerate(macro_success):
        twin.text(idx, value + 3, f"{value:.1f}%", ha="center", va="bottom", color="#264653", fontsize=9)

    fig.tight_layout()
    output = DOCS_FIGURES / "miniwob_global_trigger_sweep.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_failure_attribution(summary: dict) -> Path:
    failures = summary["global_trigger_failures"]
    failed_by_macro = failures["failed_by_macro"]
    failed_by_task = failures["failed_by_task"]
    macro_sequences = failures["macro_sequences"]

    macro_ids = sorted(failed_by_macro, key=lambda macro_id: (-failed_by_macro[macro_id], macro_id))
    task_names = sorted(failed_by_task)
    colors = {
        "choose_list": "#457b9d",
        "login_user": "#d62828",
        "use_autocomplete": "#2a9d8f",
    }

    fig, ax = plt.subplots(figsize=(10, 4.8))
    y_positions = list(range(len(macro_ids)))
    left = [0] * len(macro_ids)
    for task_name in task_names:
        values = [failed_by_task.get(task_name, {}).get(macro_id, 0) for macro_id in macro_ids]
        ax.barh(y_positions, values, left=left, color=colors.get(task_name, "#999999"), label=task_name)
        left = [l + v for l, v in zip(left, values)]

    labels = []
    for macro_id in macro_ids:
        sequence = macro_sequences.get(macro_id, "")
        short_sequence = sequence.replace("|role=", "|").replace("|label=", "|")
        labels.append(f"{macro_id}: {short_sequence}")
    ax.set_yticks(y_positions, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Failed Macro Calls")
    ax.set_title("False Triggers Are Concentrated in a Few Over-Generic Global Macros")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(title="Task", loc="lower right")
    for y, total in zip(y_positions, [failed_by_macro[macro_id] for macro_id in macro_ids]):
        ax.text(total + 0.15, y, str(total), va="center")
    fig.tight_layout()
    output = DOCS_FIGURES / "miniwob_false_trigger_attribution.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_semantic_policy_sweep(summary: dict) -> Path:
    sweep = summary["semantic_policy_sweep"]
    labels = [item["label"] for item in sweep]
    reductions = [percent(item["decision_reduction_ratio"]) for item in sweep]
    macro_success = [percent(item.get("macro_success_rate", 0.0)) for item in sweep]
    failed_calls = [int(item.get("failed_macro_calls", 0)) for item in sweep]

    fig, axes = plt.subplots(2, 1, figsize=(10.4, 7.2), sharex=True, gridspec_kw={"height_ratios": [2, 1.5]})
    colors = ["#b23a48", "#457b9d", "#2a9d8f", "#7b2cbf", "#5a189a", "#4d908e", "#6a994e"]

    bars = axes[0].bar(labels, reductions, color=colors)
    axes[0].set_ylabel("Decision Reduction (%)")
    axes[0].set_title("Untrained Semantic Selection Needs Guarding; a Tiny Learned Chooser Recovers the Full Macro Benefit")
    ymin = min(0, min(reductions) * 1.2)
    ymax = max(reductions) * 1.2
    axes[0].set_ylim(ymin, ymax)
    axes[0].grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, reductions):
        offset = 1.0 if value >= 0 else -2.0
        va = "bottom" if value >= 0 else "top"
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + offset, f"{value:.1f}%", ha="center", va=va)

    axes[1].bar(labels, failed_calls, color="#e76f51", alpha=0.85, label="Failed macro calls")
    axes[1].set_ylabel("Failed Macro Calls")
    axes[1].grid(axis="y", alpha=0.25)
    twin = axes[1].twinx()
    twin.plot(labels, macro_success, color="#264653", marker="o", linewidth=2, label="Macro success rate")
    twin.set_ylabel("Macro Success (%)")
    twin.set_ylim(0, 110)
    for idx, value in enumerate(macro_success):
        twin.text(idx, value + 3, f"{value:.1f}%", ha="center", va="bottom", color="#264653", fontsize=9)

    axes[1].tick_params(axis="x", rotation=16)
    fig.tight_layout()
    output = DOCS_FIGURES / "miniwob_semantic_policy_sweep.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def plot_llm_policy_sweep(summary: dict) -> Path:
    sweep = summary["llm_policy_sweep"]
    miniwob = sweep["miniwob"]
    workarena = sweep["workarena"]

    fig, axes = plt.subplots(2, 1, figsize=(10.6, 7.8), gridspec_kw={"height_ratios": [1, 1]})

    for ax, title, items, colors in [
        (
            axes[0],
            "MiniWoB live: a no-training LLM uses named macros only when a lightweight guard narrows the action space",
            miniwob,
            ["#b23a48", "#2a9d8f", "#5a189a", "#6a994e"],
        ),
        (
            axes[1],
            "WorkArena replay: generic crowded macros remain hard for a no-training LLM, even with prompt polish",
            workarena,
            ["#457b9d", "#bc6c25", "#5a189a", "#1d3557", "#6a994e"],
        ),
    ]:
        labels = [item["label"] for item in items]
        reductions = [percent(item["decision_reduction_ratio"]) for item in items]
        bars = ax.bar(labels, reductions, color=colors)
        ax.set_ylabel("Decision Reduction (%)")
        ax.set_title(title)
        ymin = min(0, min(reductions) * 1.2)
        ymax = max(reductions) * 1.2
        ax.set_ylim(ymin, ymax)
        ax.grid(axis="y", alpha=0.25)
        for bar, value in zip(bars, reductions):
            offset = 0.8 if value >= 0 else -1.5
            va = "bottom" if value >= 0 else "top"
            ax.text(bar.get_x() + bar.get_width() / 2, value + offset, f"{value:.1f}%", ha="center", va=va)

    axes[0].text(
        0,
        percent(miniwob[0]["decision_reduction_ratio"]) + 3.0,
        f"{miniwob[0]['failed_macro_calls']} failed calls\n{miniwob[0]['llm_total_tokens']:,} tokens",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#7f1d1d",
    )
    axes[0].text(
        1,
        percent(miniwob[1]["decision_reduction_ratio"]) + 3.0,
        f"{miniwob[1]['failed_macro_calls']} failed calls\n{miniwob[1]['llm_total_tokens']:,} tokens",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#0b6e4f",
    )
    axes[1].text(
        0,
        percent(workarena[0]["decision_reduction_ratio"]) + 3.0,
        f"{workarena[0]['failed_macro_calls']} failed calls",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#1d3557",
    )
    axes[1].text(
        1,
        percent(workarena[1]["decision_reduction_ratio"]) + 3.0,
        "More detailed step text\nhurt generalization",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#8c510a",
    )

    axes[0].tick_params(axis="x", rotation=12)
    axes[1].tick_params(axis="x", rotation=12)
    fig.tight_layout()
    output = DOCS_FIGURES / "llm_policy_sweep.svg"
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def main() -> None:
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    DOCS_FIGURES.mkdir(parents=True, exist_ok=True)
    style_matplotlib()
    summary = build_summary()
    dump_json(str(DOCS_DATA / "action_chunking_summary.json"), summary)
    outputs = {
        "overview": str(plot_overall(summary)),
        "mind2web_hierarchy": str(plot_mind2web_hierarchy(summary)),
        "workarena_service_catalog": str(plot_workarena_service_catalog(summary)),
        "workarena_selector_sweep": str(plot_workarena_selector_sweep(summary)),
        "global_sweep": str(plot_global_sweep(summary)),
        "failure_attribution": str(plot_failure_attribution(summary)),
        "semantic_policy_sweep": str(plot_semantic_policy_sweep(summary)),
        "llm_policy_sweep": str(plot_llm_policy_sweep(summary)),
    }
    dump_json(str(DOCS_DATA / "action_chunking_figures.json"), outputs)


if __name__ == "__main__":
    main()
