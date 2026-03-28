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
  --trigger-prefix-len 2

python3 scripts/promote_macros.py \
  --input outputs/mind2web_full_train.jsonl \
  --output outputs/mind2web_site_task_family_macro_registry.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website_task_family \
  --min-group-episodes 3 \
  --min-promoted-support 3

python3 scripts/export_action_space.py \
  --registry outputs/mind2web_site_task_family_macro_registry.json \
  --output outputs/mind2web_site_task_family_action_space.json

python3 scripts/simulate_macro_agent.py \
  --input outputs/mind2web_full_train.jsonl \
  --registry outputs/mind2web_site_task_family_macro_registry.json \
  --output outputs/mind2web_site_task_family_macro_agent_sim.json \
  --canonicalization-mode dataflow_coarse \
  --group-by website_task_family \
  --min-group-episodes 3

./.venv/bin/python scripts/run_playwright_action.py \
  --action-space outputs/mind2web_site_task_family_action_space.json \
  --action newegg_search_m003 \
  --start-file data/demo/search_form.html \
  --arg arg1=laptop \
  --trace outputs/demo_playwright_trace.zip \
  --headless
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
- use `promote_macros.py` to turn held-out-approved macros into a registry
- use `export_action_space.py` to combine primitives plus promoted macros into one action vocabulary
- use `simulate_macro_agent.py` to estimate what a macro-aware agent would save once failed macro attempts and primitive fallback are included
- use `run_playwright_action.py` to execute one primitive or macro action in a real browser with Playwright tracing

The current savings numbers are still **decision-side estimates**, not real browser wall-clock timings. Real wall-clock measurements will need a controlled online benchmark.

Current best public-data finding:

- `website_task_family` grouping makes `dataflow_coarse` materially more function-like on Mind2Web
- held-out replay precision rises from `0.159` with site-only grouping to `0.2122`
- parameterized replay precision rises from `0.129` to `0.1916`
- moving from a `1`-step to a `2`-step trigger prefix raises held-out replay precision from `0.2122` to `0.3212`
- parameterized replay precision rises from `0.1916` to `0.3482`
- the current promoted registry contains `15` candidate macros, `14` of them parameterized
- the exported pilot action space contains `24` total actions: `9` primitives + `15` macros
- with the stronger 2-step trigger policy, the macro-agent simulation saves `27` decisions over `1333` held-out primitive steps, about `2.03%`
- under that policy, macro success rate improves from `0.6429` to `0.8571` and failed attempts drop from `10` to `3`
- the main remaining bottleneck is coverage: promoted macros only cover about `13.9%` of held-out primitive steps, although within covered groups they save about `14.6%` of decisions
- the first live browser smoke test now works: the promoted `newegg_search_m003` macro runs on [search_form.html](/Users/mark/Desktop/projects/toolcalltokenization/data/demo/search_form.html) and produces [demo_playwright_trace.zip](/Users/mark/Desktop/projects/toolcalltokenization/outputs/demo_playwright_trace.zip)
- the same macro also ran successfully on `wikipedia.org` and `duckduckgo.com` after tightening the input locator logic

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
