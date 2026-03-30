---
pretty_name: OttoAuth Local Agent Snapshot
language:
- en
license: other
annotations_creators:
- machine-generated
language_creators:
- machine-generated
multilinguality:
- monolingual
size_categories:
- n<1K
source_datasets:
- original
tags:
- browser-agents
- web-automation
- tool-use
- traces
- macro-mining
---

# OttoAuth Local Agent Snapshot

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
python3 scripts/run_ottoauth_amazon_study.py \
  --input hf_datasets/ottoauth_local_agent_snapshot/processed/canonical_trace.jsonl \
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

- raw trace folders: 21
- processed JSON files: 4
- processed JSONL files: 2
- manifest files: 18
- analysis files: 3
- figure files: 2
