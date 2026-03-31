#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render small-model-only speculative proxy figures.")
    parser.add_argument(
        "--baseline-input",
        default=str(ROOT / "outputs" / "speculative_decoding" / "amazon_proxy_baseline.json"),
    )
    parser.add_argument(
        "--lora-input",
        default=str(ROOT / "outputs" / "speculative_decoding" / "amazon_proxy_lora.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs" / "figures" / "speculative_proxy_amazon_sweep.svg"),
    )
    return parser.parse_args()


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    baseline = load_json(args.baseline_input)
    lora = load_json(args.lora_input)

    horizons = [int(k) for k in baseline["speedup_upper_bounds"].keys()]
    base_speed = [baseline["speedup_upper_bounds"][str(h)] for h in horizons]
    lora_speed = [lora["speedup_upper_bounds"][str(h)] for h in horizons]

    plt.style.use("default")
    plt.rcParams.update({"figure.dpi": 160, "savefig.dpi": 160, "font.size": 10})

    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.8))

    axes[0].bar(
        ["Base draft", "LoRA draft"],
        [
            baseline["acceptance_probability_proxy"] * 100.0,
            lora["acceptance_probability_proxy"] * 100.0,
        ],
        color=["#1f77b4", "#bc4749"],
    )
    axes[0].set_ylim(0, 100)
    axes[0].set_ylabel("Held-out next-token agreement (%)")
    axes[0].set_title("Small-Model Trace Agreement")
    axes[0].grid(alpha=0.25, axis="y")

    axes[1].plot(horizons, base_speed, marker="o", linewidth=2.2, color="#1f77b4", label="Base draft")
    axes[1].plot(horizons, lora_speed, marker="^", linewidth=2.2, color="#bc4749", label="LoRA draft")
    axes[1].set_title("Analytical Speculative Speedup Upper Bound")
    axes[1].set_xlabel("Draft horizon")
    axes[1].set_ylabel("Upper-bound speedup")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best")

    fig.text(
        0.99,
        0.01,
        "Acceptance proxy = held-out next-token agreement under the gold trace prefix.\nSpeedup uses only acceptance probability and horizon; draft compute cost is ignored.",
        ha="right",
        va="bottom",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.9, "edgecolor": "#cccccc"},
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
