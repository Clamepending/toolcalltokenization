# toolcalltokenization

Small experiments for learning reusable browser-agent or tool-call action chunks from traces.

## Contents

- [Project plan](./report.md)
- [Literature review](./browser-agent-tool-tokenization-report.md)

## Fastest Reproduction

If you only want to reproduce the Amazon OttoAuth graph, this is the shortest path:

```bash
git clone https://github.com/Clamepending/toolcalltokenization.git
cd toolcalltokenization
git checkout c8d3a93

python3 -m pip install -U huggingface_hub
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="clamepending/ottoauth-local-agent-snapshot",
    repo_type="dataset",
    local_dir="hf_datasets/ottoauth_local_agent_snapshot",
    local_dir_use_symlinks=False,
)
PY

python3 scripts/run_ottoauth_amazon_study.py \
  --input hf_datasets/ottoauth_local_agent_snapshot/processed/canonical_trace.jsonl \
  --output /tmp/ottoauth_amazon_study.json

python3 scripts/generate_ottoauth_amazon_figures.py \
  --input /tmp/ottoauth_amazon_study.json \
  --output /tmp/ottoauth_amazon_learning_curves.svg
```

That reproduces the current Amazon learning-curve figure from the public HF dataset snapshot.

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

MINIWOB_URL="file:///Users/mark/Desktop/projects/toolcalltokenization/data/local/miniwob-plusplus/miniwob/html/miniwob/" \
  ./.venvbg/bin/python scripts/run_miniwob_live_benchmark.py \
  --output-prefix outputs/miniwob_live_v3 \
  --episodes-per-task 20 \
  --headless

./.venvbg/bin/python scripts/run_miniwob_macro_policy_benchmark.py \
  --input-prefix outputs/miniwob_live_v3 \
  --output-prefix outputs/miniwob_live_v3_global_trigger_p1_v2 \
  --exclude-task-name click_button_sequence \
  --group-by website \
  --headless \
  --policy-mode trigger_prefix \
  --trigger-prefix-len 1

python3 scripts/run_macro_data_scaling_study.py \
  --input outputs/mind2web_full_train_dataflow_coarse/canonical_trace.jsonl \
  --output outputs/mind2web_data_scaling_study.json

python3 scripts/export_trace_case_study.py \
  --input outputs/mind2web_full_train_dataflow_coarse/canonical_trace.jsonl \
  --output outputs/mind2web_trace_case_studies.json \
  --group amazon \
  --group amazon::cart \
  --group united::flight

python3 scripts/build_macro_store.py \
  --input outputs/mind2web_full_train_dataflow_coarse/canonical_trace.jsonl \
  --output outputs/mind2web_bucketed_macro_store.json

python3 scripts/run_major_site_curves.py \
  --input outputs/mind2web_full_train_dataflow_coarse/canonical_trace.jsonl \
  --output outputs/mind2web_major_site_curves.json
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
- use `run_miniwob_macro_policy_benchmark.py` to replay held-out MiniWoB episodes live with macro selection, primitive fallback, and decision-side timing estimates
- use `run_macro_data_scaling_study.py` to measure how many completed runs per bucket are needed before macros become useful
- use `export_trace_case_study.py` to export before/after compressed traces for concrete buckets like `amazon` or `united::flight`
- use `build_macro_store.py` to emit a deployable bucketed JSON registry with shadow-eval statistics and live-ready flags
- use `run_major_site_curves.py` to generate fixed-heldout major-site learning curves for compression and trigger-safety

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
- the first public BrowserGym benchmark now works in a separate Python `3.11` env via [run_miniwob_live_benchmark.py](/Users/mark/Desktop/projects/toolcalltokenization/scripts/run_miniwob_live_benchmark.py)
- on the stable held-out subset of the 20-seed MiniWoB live run, macros reduce decisions from `80` to `32`, a `0.60` decision reduction ratio, while keeping success at `1.0`, in [miniwob_live_v3_stable_benchmark.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/miniwob_live_v3_stable_benchmark.json)
- the learned MiniWoB live registry contains `17` promoted macros, `15` of them parameterized, in [miniwob_live_v3_macro_registry.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/miniwob_live_v3_macro_registry.json)
- the new live macro-policy runner is [run_miniwob_macro_policy_benchmark.py](/Users/mark/Desktop/projects/toolcalltokenization/scripts/run_miniwob_macro_policy_benchmark.py), and it can execute promoted macros online with primitive fallback
- under a per-task action space, the live `oracle_exact` and `2`-step `trigger_prefix` policies both match the upper bound on the stable subset: `80 -> 32` decisions, `0.60` reduction ratio, `1.0` success, in [miniwob_live_v3_policy_oracle_v2_macro_policy_benchmark.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/miniwob_live_v3_policy_oracle_v2_macro_policy_benchmark.json) and [miniwob_live_v3_policy_trigger_v2_macro_policy_benchmark.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/miniwob_live_v3_policy_trigger_v2_macro_policy_benchmark.json)
- under a single global MiniWoB action space, the exact / clean `2`-step policy drops to `83 -> 48` decisions, a `0.4217` reduction ratio, still with `1.0` success, in [miniwob_live_v3_global_oracle_macro_policy_benchmark.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/miniwob_live_v3_global_oracle_macro_policy_benchmark.json)
- loosening the global trigger to `1` step keeps success at `1.0` but drops savings to `83 -> 63` decisions, a `0.241` reduction ratio, with `12` false macro triggers and `0.6571` macro success, in [miniwob_live_v3_global_trigger_p1_v2_macro_policy_benchmark.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/miniwob_live_v3_global_trigger_p1_v2_macro_policy_benchmark.json)
- the key new lesson is that macro utility is real, but loose global triggering burns a noticeable fraction of the upside even on simple MiniWoB tasks

## Why this starts offline

- it keeps the repo simple
- it lets us test trace compressibility before building a full browser runtime
- it gives us a stable format that later BrowserGym or Playwright adapters can target

## Dataset converters

Current converters target:

- Mind2Web task JSON files
- OttoAuth local-agent `task.json` / `trace.json` recording folders
- WebLINX `replay.json` demonstrations
- WebLINX processed chat/action JSONL or JSONL.GZ files
- WONDERBREAD-style `trace.json` files

## Local public data

See [data/README.md](./data/README.md) for the small public dataset slices currently used by the repo.

## OttoAuth Collection

The repo now includes a direct ingest path for real browser-agent traces recorded by the OttoAuth Chrome extension.

### Collect data with the OttoAuth extension

The OttoAuth app and extension live in the sibling repo:

- app/server: `/Users/mark/Desktop/projects/oneclickstack/autoauth`
- Chrome extension: `/Users/mark/Desktop/projects/oneclickstack/autoauth/chrome-extension`

Minimal collection flow:

1. Start the OttoAuth app server:

```bash
cd /Users/mark/Desktop/projects/oneclickstack/autoauth
npm run dev
```

2. Build the extension:

```bash
cd /Users/mark/Desktop/projects/oneclickstack/autoauth/chrome-extension
npm run build
```

3. In Chrome, load or refresh the unpacked extension from:

```text
/Users/mark/Desktop/projects/oneclickstack/autoauth/chrome-extension/dist
```

4. Open the extension sidepanel and configure OttoAuth:
   - server URL: `http://localhost:3000`
   - device name: usually `browser-agent-1`
   - click `Connect & Pair`

5. Turn on trace recording in the OttoAuth section:
   - click `Select Folder`
   - choose:

```text
/Users/mark/Desktop/projects/toolcalltokenization/data/ottoauth
```

   - click `Start Recording` if needed
   - then click `Start Polling`

6. Queue a small campaign from this repo:

```bash
/opt/homebrew/bin/node scripts/queue_ottoauth_campaign.mjs \
  --campaign amazon_search \
  --count 6
```

Current built-in campaigns are:

- `amazon_search`
- `amazon_cart`
- `amazon_checkout_preview`
- `newegg_search`
- `wikipedia_search`
- `mixed_search`

7. Let the browser agent finish the queued tasks.

Each completed task writes a folder like:

```text
data/ottoauth/YYYY-MM-DD/<site>/<timestamp>_<site>_<task-type>_<task-id>/
```

with:

- `task.json`
- `trace.json`

8. Ingest the saved traces into the macro-mining format:

```bash
python3 scripts/ingest_ottoauth_collection.py \
  --input data/ottoauth \
  --output-dir outputs/ottoauth_live_collection
```

This writes:

- `outputs/ottoauth_live_collection/raw_trace.jsonl`
- `outputs/ottoauth_live_collection/canonical_trace.jsonl`
- `outputs/ottoauth_live_collection/summary.json`

9. Run the Amazon study:

```bash
python3 scripts/run_ottoauth_amazon_study.py \
  --input outputs/ottoauth_live_collection/canonical_trace.jsonl \
  --output outputs/ottoauth_amazon_study.json

python3 scripts/generate_ottoauth_amazon_figures.py \
  --input outputs/ottoauth_amazon_study.json \
  --output docs/figures/ottoauth_amazon_learning_curves.svg
```

Useful checks while collecting:

- compare server-side task completions to local trace folders:

```bash
/opt/homebrew/bin/node scripts/audit_ottoauth_collection.mjs
```

- refresh the local ingest + Amazon study + health dashboard:

```bash
python3 scripts/refresh_ottoauth_dashboard.py
```

Convert the saved recordings into raw + canonical JSONL plus a summary:

```bash
python3 scripts/ingest_ottoauth_collection.py \
  --input data/ottoauth \
  --output-dir outputs/ottoauth_live_collection
```

To enqueue reproducible site-family batches for the polling OttoAuth browser agent:

```bash
/opt/homebrew/bin/node scripts/queue_ottoauth_campaign.mjs \
  --campaign amazon_search \
  --count 6
```

Current built-in campaigns are:

- `amazon_search`
- `amazon_cart`
- `amazon_checkout_preview`
- `newegg_search`
- `wikipedia_search`
- `mixed_search`

Each queued batch also writes a manifest under `outputs/ottoauth_campaign_manifests/` so the exact prompts used for collection are preserved.

To compare what reached the OttoAuth server versus what actually landed in `data/ottoauth/`:

```bash
/opt/homebrew/bin/node scripts/audit_ottoauth_collection.mjs
```

Current real-agent collection status:

- the ingest path works on the traces already saved under `data/ottoauth`
- the current on-disk sample is still tiny and dominated by Amazon traces
- with only three local episodes, no nontrivial macro survives mining yet
- the current bottleneck for this path is collection density and recorder consistency, not the ingest or mining code

## Shareable OttoAuth Snapshot

To export a sanitized Hugging Face-ready OttoAuth snapshot for colleagues:

```bash
python3 scripts/export_ottoauth_hf_dataset.py \
  --output-dir hf_datasets/ottoauth_local_agent_snapshot
```

Published dataset:

- [clamepending/ottoauth-local-agent-snapshot](https://huggingface.co/datasets/clamepending/ottoauth-local-agent-snapshot)

The current published snapshot is intentionally small. It includes:

- sanitized raw `task.json` / `trace.json` folders
- `processed/canonical_trace.jsonl`
- queued campaign manifests
- the current Amazon study JSON and figure
- export metadata

To re-run the Amazon study from the snapshot:

```bash
python3 -m pip install -U huggingface_hub
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="clamepending/ottoauth-local-agent-snapshot",
    repo_type="dataset",
    local_dir="hf_datasets/ottoauth_local_agent_snapshot",
    local_dir_use_symlinks=False,
)
PY

python3 scripts/run_ottoauth_amazon_study.py \
  --input hf_datasets/ottoauth_local_agent_snapshot/processed/canonical_trace.jsonl \
  --output /tmp/ottoauth_amazon_study.json

python3 scripts/generate_ottoauth_amazon_figures.py \
  --input /tmp/ottoauth_amazon_study.json \
  --output /tmp/ottoauth_amazon_learning_curves.svg
```
