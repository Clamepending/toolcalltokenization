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
        "Learned": load_json(OUTPUTS / "miniwob_live_v3_learned_global_noguard_stable_learned_policy_benchmark.json")["summary"],
        "LLM": load_json(OUTPUTS / "miniwob_live_v3_llm_global_guard_stable_v2_llm_policy_benchmark.json")["summary"],
        "Oracle": load_json(OUTPUTS / "miniwob_live_v3_global_taskregistry_oracle_stable_macro_policy_benchmark.json")["summary"],
        "Primitive": {
            "decision_reduction_ratio": 0.0,
            "success_rate": 1.0,
            "steps_saved": 0,
            "primitive_steps": 80,
        },
    }

    colors = {
        "Primitive": "#4c566a",
        "LLM": "#d08770",
        "Learned": "#5e81ac",
        "Oracle": "#2e3440",
    }

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.2), sharey=True)
    for ax, title, payload in [
        (axes[0], "WorkArena Service Catalog", workarena),
        (axes[1], "MiniWoB Stable Tasks", miniwob),
    ]:
        for label, summary in payload.items():
            x = float(summary["decision_reduction_ratio"]) * 100.0
            y = float(summary["success_rate"]) * 100.0
            saved = float(summary.get("steps_saved", 0))
            ax.scatter(
                [x],
                [y],
                s=110 + 16 * saved,
                color=colors[label],
                alpha=0.92,
                edgecolors="white",
                linewidths=1.2,
                zorder=3,
            )
            ax.annotate(
                f"{label}\n{x:.1f}% saved",
                (x, y),
                xytext=(6, 6 if label != "Primitive" else -18),
                textcoords="offset points",
                fontsize=9,
            )
        ax.set_title(title, fontsize=12, pad=10)
        ax.set_xlim(-2, 70)
        ax.set_ylim(90, 101.5)
        ax.grid(True, axis="both", linestyle="--", linewidth=0.5, alpha=0.35)
        ax.set_xlabel("Model calls saved per task (%)")
    axes[0].set_ylabel("Task success rate (%)")
    fig.suptitle("Macros preserve success while saving many controller decisions", fontsize=14, y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
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


if __name__ == "__main__":
    main()
