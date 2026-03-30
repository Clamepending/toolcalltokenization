#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the Amazon OttoAuth learning-curve SVG from a study JSON.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "outputs" / "ottoauth_amazon_study.json"),
        help="Path to the Amazon study JSON.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs" / "figures" / "ottoauth_amazon_learning_curves.svg"),
        help="Where to write the SVG figure.",
    )
    return parser.parse_args()


def save_amazon_curves(study: dict, output: Path) -> None:
    plt.style.use("default")
    plt.rcParams.update({"figure.dpi": 160, "savefig.dpi": 160, "font.size": 10})

    fig, axes = plt.subplots(2, 1, figsize=(10.5, 7.4), sharex=True, gridspec_kw={"height_ratios": [1.6, 1.3]})
    colors = {
        "amazon.com": "#1f77b4",
        "amazon.com::search": "#2a9d8f",
        "amazon.com::cart": "#c46b32",
        "amazon.com::checkout": "#bc4749",
    }
    for group_key, group in study["curves"].items():
        if group.get("status") != "ok" or not group.get("points"):
            continue
        points = group["points"]
        xs = [point["total_episodes"] for point in points]
        compression = [(1.0 - float(point["compression_ratio"])) * 100.0 for point in points]
        precision = [float(point["trigger_precision_prefix2"]) * 100.0 for point in points]
        label = group_key.replace("amazon.com", "amazon")
        color = colors.get(group_key, "#6c757d")
        axes[0].plot(xs, compression, marker="o", linewidth=2.2, label=label, color=color)
        axes[1].plot(xs, precision, marker="o", linewidth=2.0, label=label, color=color)

    axes[0].set_ylabel("Decision Reduction (%)")
    axes[0].set_title("Amazon OttoAuth Learning Curves")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].set_ylabel("Trigger Precision (%)")
    axes[1].set_xlabel("Total Episodes (includes held-out episodes)")
    axes[1].set_ylim(0, 105)
    axes[1].grid(alpha=0.25)

    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    study = load_json(Path(args.input))
    save_amazon_curves(study, Path(args.output))


if __name__ == "__main__":
    main()
