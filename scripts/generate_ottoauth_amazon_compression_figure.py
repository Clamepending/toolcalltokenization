#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a simple traces-vs-compression figure for the OttoAuth Amazon study."
    )
    parser.add_argument(
        "--input",
        default=str(ROOT / "outputs" / "ottoauth_amazon_study.json"),
        help="Path to the Amazon study JSON.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs" / "figures" / "ottoauth_amazon_compression_vs_traces.svg"),
        help="Where to write the SVG figure.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_figure(study: dict, output: Path) -> None:
    plt.style.use("default")
    plt.rcParams.update({"figure.dpi": 160, "savefig.dpi": 160, "font.size": 10})

    fig, ax = plt.subplots(figsize=(10.2, 5.7))
    colors = {
        "amazon.com": "#1f77b4",
        "amazon.com::search": "#2a9d8f",
        "amazon.com::cart": "#c46b32",
        "amazon.com::checkout": "#bc4749",
    }
    labels = {
        "amazon.com": "amazon (site-wide)",
        "amazon.com::search": "amazon::search",
        "amazon.com::cart": "amazon::cart",
        "amazon.com::checkout": "amazon::checkout",
    }

    plotted = 0
    for group_key in ["amazon.com", "amazon.com::search", "amazon.com::cart", "amazon.com::checkout"]:
        group = study["curves"].get(group_key)
        if not group or group.get("status") != "ok" or not group.get("points"):
            continue
        points = group["points"]
        xs = [int(point["total_episodes"]) for point in points]
        ys = [float(point["decision_reduction_ratio"]) * 100.0 for point in points]
        ax.plot(
            xs,
            ys,
            marker="o",
            linewidth=2.2,
            markersize=5.5,
            color=colors.get(group_key, "#6c757d"),
            label=labels.get(group_key, group_key),
        )
        plotted += 1

    ax.set_title("Amazon OttoAuth: Number of Traces vs Decision Reduction")
    ax.set_xlabel("Total Amazon traces in bucket (includes held-out traces)")
    ax.set_ylabel("Decision Reduction (%)")
    ax.grid(alpha=0.25)
    if plotted:
        ax.legend(loc="best")

    ax.text(
        0.99,
        0.01,
        "Held-out episodes per point: 2\nDecision reduction = 1 - compression ratio",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.9, "edgecolor": "#cccccc"},
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    save_figure(load_json(Path(args.input)), Path(args.output))


if __name__ == "__main__":
    main()
