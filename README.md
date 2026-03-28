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
- measure how much those chunks compress trajectories

## Quickstart

```bash
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
```

## Why this starts offline

- it keeps the repo simple
- it lets us test trace compressibility before building a full browser runtime
- it gives us a stable format that later BrowserGym or Playwright adapters can target
