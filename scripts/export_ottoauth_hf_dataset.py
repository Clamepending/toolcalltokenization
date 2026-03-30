#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ADDRESS_PATTERNS = [
    re.compile(
        r"\b\d{1,6}\s+[A-Za-z0-9.'#-]+(?:\s+[A-Za-z0-9.'#-]+){0,5},\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\b"
    ),
]
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?:\+?1[-.\s])?(?:\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a sanitized OttoAuth snapshot in a Hugging Face-ready layout.")
    parser.add_argument(
        "--raw-root",
        default=str(ROOT / "data" / "ottoauth"),
        help="Root directory containing raw OttoAuth task/trace folders.",
    )
    parser.add_argument(
        "--processed-root",
        default=str(ROOT / "outputs" / "ottoauth_live_collection"),
        help="Processed OttoAuth collection outputs from ingest_ottoauth_collection.py.",
    )
    parser.add_argument(
        "--manifests-root",
        default=str(ROOT / "outputs" / "ottoauth_campaign_manifests"),
        help="Directory containing queued OttoAuth campaign manifests.",
    )
    parser.add_argument(
        "--analysis-files",
        nargs="*",
        default=[
            str(ROOT / "outputs" / "ottoauth_amazon_study.json"),
            str(ROOT / "outputs" / "ottoauth_collection_health.json"),
            str(ROOT / "outputs" / "ottoauth_collection_audit.json"),
        ],
        help="Analysis JSON files to include under analysis/.",
    )
    parser.add_argument(
        "--figure-files",
        nargs="*",
        default=[
            str(ROOT / "docs" / "figures" / "ottoauth_amazon_learning_curves.svg"),
            str(ROOT / "docs" / "figures" / "ottoauth_collection_health.svg"),
        ],
        help="Figure files to include under figures/.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "hf_datasets" / "ottoauth_local_agent_snapshot"),
        help="Destination for the sanitized snapshot.",
    )
    return parser.parse_args()


def sanitize_string(value: str) -> str:
    text = value
    text = text.replace(str(ROOT), "<LOCAL_ROOT>")
    text = EMAIL_PATTERN.sub("<EMAIL>", text)
    text = PHONE_PATTERN.sub("<PHONE>", text)
    for pattern in ADDRESS_PATTERNS:
        text = pattern.sub("<ADDRESS>", text)
    return text


def sanitize_object(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_object(item) for item in value]
    if isinstance(value, str):
        return sanitize_string(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def export_json_file(src: Path, dst: Path) -> None:
    payload = json.loads(src.read_text(encoding="utf-8"))
    write_json(dst, sanitize_object(payload))


def export_jsonl_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open("r", encoding="utf-8") as in_handle, dst.open("w", encoding="utf-8") as out_handle:
        for line in in_handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = sanitize_object(json.loads(stripped))
            out_handle.write(json.dumps(payload, sort_keys=True) + "\n")


def export_tree(src_root: Path, dst_root: Path) -> dict[str, int]:
    counts = {"json": 0, "jsonl": 0}
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if src.suffix == ".json":
            export_json_file(src, dst)
            counts["json"] += 1
        elif src.suffix == ".jsonl":
            export_jsonl_file(src, dst)
            counts["jsonl"] += 1
    return counts


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build_dataset_card(export_summary: dict[str, Any]) -> str:
    processed = export_summary["processed"]
    analysis = export_summary["analysis"]
    return f"""# OttoAuth Local Agent Snapshot

This folder is a Hugging Face-ready snapshot of the OttoAuth browser-agent traces used in the macro-mining experiments.

## What is included

- `raw_traces/`: sanitized `task.json` / `trace.json` folders copied from the Chrome extension recorder
- `processed/`: sanitized JSONL and summary outputs from the OttoAuth ingest pipeline
- `manifests/`: the queued campaign specs that produced these traces
- `analysis/`: small derived JSON artifacts used in the Amazon and collection-health writeups
- `figures/`: the corresponding SVG plots
- `metadata/export_summary.json`: snapshot counts and export metadata

## Folder meanings

- `processed/canonical_trace.jsonl`
  - the normalized action sequence used by macro mining
- `processed/raw_trace.jsonl`
  - the flattened primitive tool-call rows before canonicalization
- `manifests/`
  - reproducibility metadata showing exactly which task batches were queued
- `analysis/ottoauth_amazon_study.json`
  - the derived Amazon learning-curve study used for the current report

## Privacy note

The export script sanitizes obvious addresses, phone numbers, and email-like strings in JSON and JSONL payloads. The goal is to make the snapshot shareable with collaborators without exposing prompt-specific address details.

## Reproducing the Amazon study

From the code repo root:

```bash
python3 scripts/run_ottoauth_amazon_study.py \\
  --input hf_datasets/ottoauth_local_agent_snapshot/processed/canonical_trace.jsonl \\
  --output /tmp/ottoauth_amazon_study.json

python3 - <<'PY'
from pathlib import Path
import json
from scripts.generate_ottoauth_amazon_figures import save_amazon_curves

study = json.loads(Path('/tmp/ottoauth_amazon_study.json').read_text())
save_amazon_curves(study, Path('/tmp/ottoauth_amazon_learning_curves.svg'))
print('/tmp/ottoauth_amazon_learning_curves.svg')
PY
```

## Snapshot summary

- raw trace folders: {export_summary["raw_trace_folders"]}
- processed JSON files: {processed["json_files"]}
- processed JSONL files: {processed["jsonl_files"]}
- manifest files: {export_summary["manifest_files"]}
- analysis files: {analysis["json_files"]}
- figure files: {export_summary["figure_files"]}
"""


def main() -> None:
    args = parse_args()
    raw_root = Path(args.raw_root)
    processed_root = Path(args.processed_root)
    manifests_root = Path(args.manifests_root)
    output_dir = Path(args.output_dir)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_counts = export_tree(raw_root, output_dir / "raw_traces")
    processed_counts = export_tree(processed_root, output_dir / "processed")
    manifest_counts = export_tree(manifests_root, output_dir / "manifests")

    analysis_count = 0
    for item in args.analysis_files:
        src = Path(item)
        if src.is_file():
            export_json_file(src, output_dir / "analysis" / src.name)
            analysis_count += 1

    figure_count = 0
    for item in args.figure_files:
        src = Path(item)
        if src.is_file():
            copy_file(src, output_dir / "figures" / src.name)
            figure_count += 1

    raw_trace_folders = sum(1 for path in (output_dir / "raw_traces").rglob("trace.json"))
    export_summary = {
        "raw_trace_folders": raw_trace_folders,
        "raw": {
            "json_files": raw_counts["json"],
            "jsonl_files": raw_counts["jsonl"],
        },
        "processed": {
            "json_files": processed_counts["json"],
            "jsonl_files": processed_counts["jsonl"],
        },
        "manifest_files": manifest_counts["json"],
        "analysis": {
            "json_files": analysis_count,
        },
        "figure_files": figure_count,
        "source_paths": {
            "raw_root": "raw OttoAuth trace collection",
            "processed_root": "processed OttoAuth live collection outputs",
            "manifests_root": "queued OttoAuth campaign manifests",
        },
        "redactions": {
            "addresses": "<ADDRESS>",
            "emails": "<EMAIL>",
            "phones": "<PHONE>",
        },
    }
    write_json(output_dir / "metadata" / "export_summary.json", export_summary)
    (output_dir / "README.md").write_text(build_dataset_card(export_summary), encoding="utf-8")


if __name__ == "__main__":
    main()
