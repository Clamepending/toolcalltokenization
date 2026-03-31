#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render brute-force vs pair-merge macro comparison figure.")
    parser.add_argument(
        "--ottoauth-input",
        default=str(ROOT / "outputs" / "pair_merge_vs_bruteforce_ottoauth_amazon_families.json"),
    )
    parser.add_argument(
        "--mind2web-input",
        default=str(ROOT / "outputs" / "pair_merge_vs_bruteforce_mind2web_selected.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs" / "figures" / "pair_merge_vs_bruteforce.svg"),
    )
    return parser.parse_args()


def load_rows(path: str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload["results"]


def short_label(group_key: str) -> str:
    if group_key.startswith("amazon.com::"):
        return group_key.replace("amazon.com::", "amazon::")
    return group_key


def panel(ax, rows: list[dict], title: str) -> None:
    labels = [short_label(item["group_key"]) for item in rows]
    brute = [item["bruteforce"]["decision_reduction_ratio"] * 100.0 for item in rows]
    pair = [item["pair_merge"]["decision_reduction_ratio"] * 100.0 for item in rows]
    x = range(len(labels))
    width = 0.38

    ax.bar([i - width / 2 for i in x], brute, width=width, color="#1f77b4", label="Brute-force")
    ax.bar([i + width / 2 for i in x], pair, width=width, color="#bc4749", label="Pair-merge")
    ax.set_title(title)
    ax.set_ylabel("Held-out decision reduction (%)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(alpha=0.25, axis="y")


def main() -> None:
    args = parse_args()
    ottoauth_rows = load_rows(args.ottoauth_input)
    mind2web_rows = load_rows(args.mind2web_input)

    plt.style.use("default")
    plt.rcParams.update({"figure.dpi": 160, "savefig.dpi": 160, "font.size": 10})

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0))
    panel(axes[0], ottoauth_rows, "OttoAuth Amazon Families")
    panel(axes[1], mind2web_rows, "Mind2Web Selected Families")
    axes[0].legend(loc="best")

    fig.text(
        0.99,
        0.01,
        "Greedy pair-merge here means repeated best-pair replacement (Re-Pair style),\nnot full classic Sequitur's online digram-uniqueness procedure.",
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
