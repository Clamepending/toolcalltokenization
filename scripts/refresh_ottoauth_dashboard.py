#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the OttoAuth collection dashboard and health reports.")
    parser.add_argument(
        "--traces-root",
        default=str(ROOT / "data" / "ottoauth"),
        help="Root folder containing OttoAuth task/trace folders.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "outputs" / "ottoauth_live_collection"),
        help="Directory for ingested OttoAuth collection outputs.",
    )
    parser.add_argument(
        "--website",
        default="amazon.com",
        help="Website bucket to use for the focused study.",
    )
    return parser.parse_args()


def find_node() -> str:
    for candidate in ("node", "/opt/homebrew/bin/node"):
        resolved = shutil.which(candidate) if candidate == "node" else candidate
        if resolved and Path(resolved).exists():
            return resolved
    raise FileNotFoundError("Could not find a Node.js binary for audit_ottoauth_collection.mjs")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    args = parse_args()
    traces_root = Path(args.traces_root)
    output_dir = Path(args.output_dir)
    canonical_jsonl = output_dir / "canonical_trace.jsonl"
    amazon_study = ROOT / "outputs" / "ottoauth_amazon_study.json"
    amazon_curve = ROOT / "docs" / "figures" / "ottoauth_amazon_learning_curves.svg"
    node = find_node()

    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ingest_ottoauth_collection.py"),
            "--input",
            str(traces_root),
            "--output-dir",
            str(output_dir),
        ]
    )
    run([node, str(ROOT / "scripts" / "audit_ottoauth_collection.mjs")])
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_ottoauth_amazon_study.py"),
            "--input",
            str(canonical_jsonl),
            "--output",
            str(amazon_study),
            "--website",
            args.website,
        ]
    )
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "generate_ottoauth_amazon_figures.py"),
            "--input",
            str(amazon_study),
            "--output",
            str(amazon_curve),
        ]
    )
    run([sys.executable, str(ROOT / "scripts" / "ottoauth_collection_health.py")])


if __name__ == "__main__":
    main()
