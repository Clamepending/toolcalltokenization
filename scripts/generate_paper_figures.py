#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DOCS = ROOT / "docs" / "figures"


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def short_mode_name(mode: str) -> str:
    mapping = {
        "signature": "Signature",
        "coarse_signature": "Coarse",
        "value_slots": "Value Slots",
        "name_only": "Name Only",
        "dataflow": "Dataflow",
        "dataflow_coarse": "Dataflow+Target",
    }
    return mapping.get(mode, mode.replace("_", " ").title())


def plot_headline_figure(output_path: Path) -> None:
    workarena = {
        "Primitive": load_json(OUTPUTS / "workarena_service_catalog_v1_primitive_live_v1_live_policy_benchmark.json")["summary"],
        "Learned": load_json(OUTPUTS / "workarena_service_catalog_v1_learned_live_v1_live_policy_benchmark.json")["summary"],
        "LLM": load_json(OUTPUTS / "workarena_service_catalog_v1_llm_live_v1_live_policy_benchmark.json")["summary"],
        "Oracle": load_json(OUTPUTS / "workarena_service_catalog_v1_oracle_live_v3_live_policy_benchmark.json")["summary"],
    }
    miniwob = {
        "Primitive": load_json(OUTPUTS / "miniwob_live_v3_benchmark.json")["summary"],
        "Task+Guard": load_json(OUTPUTS / "miniwob_live_v3_semantic_task_guard_m0_semantic_policy_benchmark.json")["summary"],
        "Global-NoGuard": load_json(OUTPUTS / "miniwob_live_v3_semantic_global_m0_semantic_policy_benchmark.json")["summary"],
    }

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.6), sharey=False)
    for ax, title, payload in [
        (axes[0], "WorkArena (realistic, saturated success)", workarena),
        (axes[1], "MiniWoB full slice (non-saturated success)", miniwob),
    ]:
        labels = list(payload.keys())
        xs = list(range(len(labels)))
        saved = [float(payload[label]["decision_reduction_ratio"]) * 100.0 for label in labels]
        success = [float(payload[label]["success_rate"]) * 100.0 for label in labels]

        bars = ax.bar(xs, saved, color=["#4c566a", "#5e81ac", "#d08770", "#2e3440"][: len(labels)], alpha=0.9)
        ax.set_title(title, fontsize=12, pad=10)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, rotation=14, ha="right")
        ax.set_ylabel("Model calls saved (%)")
        ax.grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
        line_ax = ax.twinx()
        line_ax.plot(xs, success, color="#bf616a", marker="o", linewidth=2.0)
        line_ax.set_ylabel("Task success (%)")
        if "MiniWoB" in title:
            line_ax.set_ylim(92, 96)
        else:
            line_ax.set_ylim(95, 101)
        for bar, reduction in zip(bars, saved):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.2, f"{reduction:.1f}", ha="center", va="bottom", fontsize=9)
        for idx, score in enumerate(success):
            line_ax.annotate(f"{score:.1f}", (xs[idx], score), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=9, color="#bf616a")

    fig.suptitle("Guarded macros save controller calls while preserving observed task success", fontsize=14, y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_amazon_scaling(output_path: Path) -> None:
    payload = load_json(OUTPUTS / "ottoauth_amazon_study.json")
    curves = payload["curves"]
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    color_map = {
        "amazon.com": "#2e3440",
        "amazon.com::search": "#5e81ac",
        "amazon.com::cart": "#a3be8c",
        "amazon.com::checkout": "#d08770",
    }
    for key in ["amazon.com", "amazon.com::search", "amazon.com::cart", "amazon.com::checkout"]:
        if key not in curves:
            continue
        points = curves[key]["points"]
        xs = [int(point["total_episodes"]) for point in points]
        ys = [float(point["decision_reduction_ratio"]) * 100.0 for point in points]
        ax.plot(xs, ys, marker="o", linewidth=2.0, label=key.replace("amazon.com::", ""), color=color_map.get(key))
    ax.set_title("Amazon trace scaling by workflow family", fontsize=12, pad=10)
    ax.set_xlabel("Total traces in bucket")
    ax.set_ylabel("Held-out decision reduction (%)")
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.35)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_pair_merge_clean(output_path: Path) -> None:
    amazon = load_json(OUTPUTS / "pair_merge_vs_bruteforce_ottoauth_amazon_families.json")["results"]
    mind2web = load_json(OUTPUTS / "pair_merge_vs_bruteforce_mind2web_selected.json")["results"]
    rows = []
    for item in amazon + mind2web:
        rows.append(
            (
                item["group_key"],
                float(item["bruteforce"]["decision_reduction_ratio"]) * 100.0,
                float(item["pair_merge"]["decision_reduction_ratio"]) * 100.0,
            )
        )
    rows.sort(key=lambda row: row[0])
    labels = [row[0] for row in rows]
    brute = [row[1] for row in rows]
    pair = [row[2] for row in rows]
    x = list(range(len(labels)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    ax.bar([v - width / 2 for v in x], brute, width=width, color="#5e81ac", label="Brute-force")
    ax.bar([v + width / 2 for v in x], pair, width=width, color="#88c0d0", label="Pair-merge")
    ax.set_title("Brute-force chunk mining is stronger on overlapping buckets", fontsize=12, pad=10)
    ax.set_ylabel("Held-out decision reduction (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_model_family_sweep(output_path: Path) -> None:
    runs = [
        ("Llama 3.2 3B (local)", load_json(OUTPUTS / "workarena_service_catalog_v1_ollama_llama32_3b_taskfamily_selector.json")["summary"], "#88c0d0"),
        ("GPT-4.1-mini", load_json(OUTPUTS / "workarena_service_catalog_v1_llm_guard_selector_v2.json")["summary"], "#5e81ac"),
        ("Claude Sonnet 4.5", load_json(OUTPUTS / "workarena_service_catalog_v1_openrouter_claude_sonnet45_taskfamily_selector.json")["summary"], "#8fbcbb"),
        ("Claude Opus 4.1", load_json(OUTPUTS / "workarena_service_catalog_v1_openrouter_claude_opus41_taskfamily_selector.json")["summary"], "#5e81ac"),
        ("Gemini 2.5 Flash", load_json(OUTPUTS / "workarena_service_catalog_v1_openrouter_gemini25flash_taskfamily_selector.json")["summary"], "#a3be8c"),
        ("Llama 3.3 70B", load_json(OUTPUTS / "workarena_service_catalog_v1_openrouter_llama33_70b_taskfamily_selector.json")["summary"], "#4c566a"),
        ("Qwen 2.5 72B", load_json(OUTPUTS / "workarena_service_catalog_v1_openrouter_qwen25_72b_taskfamily_selector.json")["summary"], "#d08770"),
    ]
    runs.sort(key=lambda row: float(row[1]["decision_reduction_ratio"]), reverse=True)
    labels = [row[0] for row in runs]
    reductions = [float(row[1]["decision_reduction_ratio"]) * 100.0 for row in runs]
    macro_success = [float(row[1]["macro_success_rate"]) * 100.0 for row in runs]
    colors = [row[2] for row in runs]
    y = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=(9.8, 5.8))
    bars = ax.barh(y, reductions, color=colors, alpha=0.92)
    ax.set_title("Macro benefits vary sharply across model families on the same replay benchmark", fontsize=12, pad=10)
    ax.set_xlabel("Decision reduction on WorkArena replay (%)")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.grid(True, axis="x", linestyle="--", linewidth=0.5, alpha=0.35)
    right = ax.twiny()
    right.plot(macro_success, y, color="#bf616a", marker="o", linewidth=2.0)
    right.set_xlabel("Macro success rate (%)")
    right.set_xlim(0, 105)
    ax.invert_yaxis()
    for bar, reduction in zip(bars, reductions):
        x = bar.get_width()
        anchor = x + 1.2 if x >= 0 else x - 1.2
        align = "left" if x >= 0 else "right"
        ax.text(anchor, bar.get_y() + bar.get_height() / 2, f"{reduction:.1f}", ha=align, va="center", fontsize=9)
    for idx, value in enumerate(macro_success):
        right.annotate(f"{value:.0f}", (value, y[idx]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color="#bf616a")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_tokenization_ablation(
    *,
    raw_datasets: dict[str, dict[str, dict[str, float]]],
    utility_payloads: dict[str, dict],
    output_path: Path,
) -> None:
    modes = ["signature", "coarse_signature", "value_slots", "name_only", "dataflow", "dataflow_coarse"]
    labels = [short_mode_name(mode) for mode in modes]
    x = list(range(len(modes)))
    width = 0.34

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    raw_values = raw_datasets["mind2web"]
    chunk = [(1.0 - raw_values[mode]["frequent"]) * 100.0 for mode in modes]
    bpe = [(1.0 - raw_values[mode]["bpe"]) * 100.0 for mode in modes]
    axes[0].bar([value - width / 2 for value in x], chunk, width=width, color="#5e81ac", label="Brute-force chunks")
    axes[0].bar([value + width / 2 for value in x], bpe, width=width, color="#88c0d0", label="BPE/Re-Pair style")
    axes[0].set_title("Mind2Web: raw held-out compression", fontsize=12, pad=10)
    axes[0].set_ylabel("Held-out compression reduction (%)")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=25, ha="right")
    axes[0].grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
    axes[0].legend(frameon=False, loc="upper right")

    mind2web_utility = {
        item["canonicalization_mode"]: item["summary"]["decision_reduction_ratio"] * 100.0
        for item in utility_payloads["mind2web"]["variants"]
    }
    mind2web_precision = {
        item["canonicalization_mode"]: item["summary"]["weighted_macro_replay_precision"] * 100.0
        for item in utility_payloads["mind2web"]["variants"]
    }
    axes[1].bar(
        x,
        [mind2web_utility.get(mode, 0.0) for mode in modes],
        width=0.58,
        color="#a3be8c",
        label="Held-out decision reduction",
    )
    precision_ax = axes[1].twinx()
    precision_ax.plot(
        x,
        [mind2web_precision.get(mode, 0.0) for mode in modes],
        color="#bf616a",
        marker="o",
        linewidth=2.0,
        label="Weighted replay precision",
    )
    axes[1].set_title("Mind2Web: usable macro utility", fontsize=12, pad=10)
    axes[1].set_ylabel("Decision reduction after promotion (%)")
    precision_ax.set_ylabel("Weighted replay precision (%)")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=25, ha="right")
    axes[1].grid(True, axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
    handles1, labels1 = axes[1].get_legend_handles_labels()
    handles2, labels2 = precision_ax.get_legend_handles_labels()
    axes[1].legend(handles1 + handles2, labels1 + labels2, frameon=False, loc="upper right")

    fig.suptitle("Lossy tokenization helps raw compression, but dataflow+target works best for callable macros", fontsize=14, y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render paper-specific summary figures.")
    parser.add_argument(
        "--tokenization-mind2web",
        default=str(OUTPUTS / "tokenization_macro_utility_mind2web.json"),
        help="Mind2Web tokenization utility ablation JSON.",
    )
    parser.add_argument(
        "--tokenization-weblinx",
        default=str(OUTPUTS / "tokenization_macro_utility_weblinx.json"),
        help="WebLINX tokenization utility ablation JSON.",
    )
    parser.add_argument(
        "--headline-output",
        default=str(DOCS / "paper_accuracy_vs_calls_saved.svg"),
        help="Headline figure output path.",
    )
    parser.add_argument(
        "--tokenization-output",
        default=str(DOCS / "paper_tokenization_ablation.svg"),
        help="Tokenization ablation figure output path.",
    )
    parser.add_argument(
        "--amazon-output",
        default=str(DOCS / "paper_amazon_scaling.svg"),
        help="Amazon scaling figure output path.",
    )
    parser.add_argument(
        "--pair-output",
        default=str(DOCS / "paper_pair_merge_vs_bruteforce.svg"),
        help="Pair-merge comparison figure output path.",
    )
    parser.add_argument(
        "--model-output",
        default=str(DOCS / "paper_model_family_sweep.svg"),
        help="Model-family selector comparison figure output path.",
    )
    args = parser.parse_args()

    raw_datasets = {
        "mind2web": {
            "signature": {"frequent": 0.9836, "bpe": 0.9849},
            "coarse_signature": {"frequent": 0.6041, "bpe": 0.6159},
            "value_slots": {"frequent": 0.3145, "bpe": 0.2712},
            "name_only": {"frequent": 0.2974, "bpe": 0.2278},
            "dataflow": {"frequent": 0.3139, "bpe": 0.2475},
            "dataflow_coarse": {"frequent": 0.6080, "bpe": 0.6297},
        },
        "weblinx": {
            "signature": {"frequent": 0.8540, "bpe": 0.8905},
            "coarse_signature": {"frequent": 0.7080, "bpe": 0.7737},
            "value_slots": {"frequent": 0.3869, "bpe": 0.4599},
            "name_only": {"frequent": 0.3650, "bpe": 0.4380},
            "dataflow": {"frequent": 0.4672, "bpe": 0.5182},
            "dataflow_coarse": {"frequent": 0.7664, "bpe": 0.8248},
        },
    }
    utility_payloads = {
        "mind2web": load_json(Path(args.tokenization_mind2web)),
        "weblinx": load_json(Path(args.tokenization_weblinx)),
    }

    plot_headline_figure(Path(args.headline_output))
    plot_tokenization_ablation(
        raw_datasets=raw_datasets,
        utility_payloads=utility_payloads,
        output_path=Path(args.tokenization_output),
    )
    plot_amazon_scaling(Path(args.amazon_output))
    plot_pair_merge_clean(Path(args.pair_output))
    plot_model_family_sweep(Path(args.model_output))


if __name__ == "__main__":
    main()
