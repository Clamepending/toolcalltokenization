#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render speculative decoding benchmark figures.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "outputs" / "speculative_decoding" / "amazon_speculative_baseline.json"),
        help="Speculative benchmark JSON.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs" / "figures" / "speculative_decoding_amazon_sweep.svg"),
        help="Output SVG path.",
    )
    parser.add_argument(
        "--compare-input",
        default=str(ROOT / "outputs" / "speculative_decoding" / "amazon_speculative_lora.json"),
        help="Optional comparison benchmark JSON, e.g. post-LoRA.",
    )
    return parser.parse_args()


def load_series(payload: dict) -> tuple[list[int], list[float], list[float], list[float]]:
    variants = payload["speculative_variants"]
    draft_lengths = [int(key) for key in variants.keys()]
    acceptance = [variants[str(k)]["aggregate"]["acceptance_rate"] * 100.0 for k in draft_lengths]
    speedup = [variants[str(k)]["aggregate"]["speedup_vs_target"] for k in draft_lengths]
    gold_match = [variants[str(k)]["aggregate"]["gold_prefix_match_rate"] * 100.0 for k in draft_lengths]
    return draft_lengths, acceptance, speedup, gold_match


def main() -> None:
    args = parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    compare_payload = None
    if args.compare_input and Path(args.compare_input).exists():
        compare_payload = json.loads(Path(args.compare_input).read_text(encoding="utf-8"))
    draft_lengths, acceptance, speedup, gold_match = load_series(payload)

    plt.style.use("default")
    plt.rcParams.update({"figure.dpi": 160, "savefig.dpi": 160, "font.size": 10})

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.8))

    axes[0].plot(draft_lengths, acceptance, marker="o", linewidth=2.2, color="#1f77b4", label="Base draft acceptance")
    axes[0].plot(draft_lengths, gold_match, marker="s", linewidth=2.0, color="#2a9d8f", label="Gold prefix match")
    if compare_payload:
        draft_lengths_2, acceptance_2, speedup_2, gold_match_2 = load_series(compare_payload)
        axes[0].plot(draft_lengths_2, acceptance_2, marker="^", linewidth=2.0, color="#bc4749", label="LoRA draft acceptance")
    axes[0].set_title("Amazon Trace Continuations: Acceptance")
    axes[0].set_xlabel("Draft length")
    axes[0].set_ylabel("Rate (%)")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].plot(draft_lengths, speedup, marker="o", linewidth=2.2, color="#c46b32", label="Base draft")
    if compare_payload:
        axes[1].plot(draft_lengths_2, speedup_2, marker="^", linewidth=2.0, color="#6a4c93", label="LoRA draft")
    axes[1].axhline(1.0, color="#999999", linestyle="--", linewidth=1.0)
    axes[1].set_title("Amazon Trace Continuations: Observed Speedup")
    axes[1].set_xlabel("Draft length")
    axes[1].set_ylabel("Speedup vs target-only")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best")

    heldout = payload.get("heldout_episode_count", 0)
    baseline = payload["target_baseline"]["aggregate"]
    fig.text(
        0.99,
        0.01,
        (
            f"Held-out episodes: {heldout}\n"
            f"Baseline wall time: {baseline['wall_time_sec']:.2f}s\n"
            f"Target model: {payload['target_model'].split('/')[-1]}\n"
            f"Draft model: {payload['draft_model'].split('/')[-1]}"
        ),
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
