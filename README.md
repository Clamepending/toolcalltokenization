# toolcalltokenization

Small experiments for learning reusable browser-agent or tool-call action chunks from traces.

## Contents

- [Project plan](./report.md)
- [Literature review](./browser-agent-tool-tokenization-report.md)

## Focus

This repo now has:

- a short project plan in `report.md`
- a longer literature review in `browser-agent-tool-tokenization-report.md`
- a minimal offline harness for:
  - canonicalizing traces
  - mining repeated action chunks
  - measuring simple compression from those chunks

## Minimal harness

The first harness is intentionally small:

- input JSONL traces
- normalize them into canonical action strings
- mine frequent multi-step chunks
- train a BPE-style action tokenizer
- measure how much those chunks compress trajectories

## Quickstart

```bash
python3 scripts/convert_dataset.py \
  --source mind2web \
  --input /path/to/mind2web/data/train \
  --output data/local/mind2web_train.jsonl

python3 scripts/prepare_traces.py \
  --input data/demo/sample_trace.jsonl \
  --output outputs/demo/canonical_trace.jsonl

python3 scripts/mine_macros.py \
  --input outputs/demo/canonical_trace.jsonl \
  --output outputs/demo/macros.json

python3 scripts/evaluate_macros.py \
  --input outputs/demo/canonical_trace.jsonl \
  --macros outputs/demo/macros.json \
  --output outputs/demo/eval.json

python3 scripts/compare_tokenizers.py \
  --input data/demo/sample_trace.jsonl \
  --output-dir outputs/demo/compare \
  --train-ratio 0.8 \
  --context-len 1

python3 scripts/profile_traces.py \
  --input data/demo/sample_trace.jsonl \
  --output outputs/demo/profile.json
```

## Why this starts offline

- it keeps the repo simple
- it lets us test trace compressibility before building a full browser runtime
- it gives us a stable format that later BrowserGym or Playwright adapters can target

## Dataset converters

Current converters target:

- Mind2Web task JSON files
- WebLINX `replay.json` demonstrations
- WebLINX processed chat/action JSONL or JSONL.GZ files
- WONDERBREAD-style `trace.json` files
