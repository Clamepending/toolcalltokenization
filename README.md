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
python3 scripts/fetch_public_data.py --mind2web-all-train

python3 scripts/convert_dataset.py \
  --source mind2web \
  --input data/local/mind2web/data/train \
  --output outputs/mind2web_full_train.jsonl

python3 scripts/compare_tokenizers.py \
  --input outputs/mind2web_full_train.jsonl \
  --output-dir outputs/mind2web_full_train_coarse_signature \
  --canonicalization-mode coarse_signature \
  --top-k 100 \
  --min-support 5 \
  --num-merges 100 \
  --min-occurrences 5 \
  --bpe-min-support 5 \
  --train-ratio 0.8 \
  --context-len 1

python3 scripts/profile_traces.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_full_train_coarse_signature_profile.json \
  --canonicalization-mode coarse_signature

python3 scripts/site_macro_report.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_macros_dataflow_coarse.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website \
  --min-episodes 5

python3 scripts/site_macro_report.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_task_family_macros_dataflow_coarse.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website_task_family \
  --min-episodes 3

python3 scripts/macro_savings_report.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_dataflow_coarse_savings.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website \
  --min-group-episodes 5

python3 scripts/macro_savings_report.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_task_family_dataflow_coarse_savings.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website_task_family \
  --min-group-episodes 3

python3 scripts/macro_replay_eval.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_dataflow_coarse_replay.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website \
  --min-group-episodes 5 \
  --trigger-prefix-len 1

python3 scripts/macro_replay_eval.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_task_family_dataflow_coarse_replay.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website_task_family \
  --min-group-episodes 3 \
  --trigger-prefix-len 1
```

To sweep action representations instead of using just one canonical form, rerun
`compare_tokenizers.py` with:

- `--canonicalization-mode name_only`
- `--canonicalization-mode value_slots`
- `--canonicalization-mode coarse_signature`
- `--canonicalization-mode target_signature`
- `--canonicalization-mode signature`
- `--canonicalization-mode dataflow`
- `--canonicalization-mode dataflow_coarse`

Those seven modes are the current core experiment. Right now:

- `coarse_signature` is the best global browser-action baseline
- `dataflow_coarse` is the most useful mode for surfacing function-like, parameterized macros

If the goal is reusable workflow chunks rather than just compression, start with
`site_macro_report.py` in `dataflow_coarse` mode.

The most useful grouping keys right now are:

- `website` for site-local workflow discovery
- `task_family` for rough intent families inferred from task text
- `website_task_family` for site-plus-intent grouping such as `amazon::cart` or `united::flight`

To measure utility instead of just discovery:

- use `macro_savings_report.py` for step / token / decision-latency estimates
- use `macro_replay_eval.py` for held-out exact replay precision

The current savings numbers are still **decision-side estimates**, not real browser wall-clock timings. Real wall-clock measurements will need a controlled online benchmark.

Current best public-data finding:

- `website_task_family` grouping makes `dataflow_coarse` materially more function-like on Mind2Web
- held-out replay precision rises from `0.159` with site-only grouping to `0.2122`
- parameterized replay precision rises from `0.129` to `0.1916`

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

## Local public data

See [data/README.md](./data/README.md) for the small public dataset slices currently used by the repo.
