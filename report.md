# Project Plan

Date: 2026-03-28

## Goal

Build the smallest useful experiment for this question:

**Can we mine repeated browser-action chunks from traces, expose them as higher-level actions, and reduce cost / latency without hurting task success?**

This repo should stay simple. The first milestone is **offline and replay-oriented**, not a full agent platform.

## Current status

We can continue this study without Globus.

The raw Mind2Web dump is still useful for future replay work, but it is **not a blocker** for the current experiment. The public Hugging Face releases already let us test the two most important questions:

1. How sensitive are compression and caching to the action representation?
2. Do public browser-action traces already show reusable multi-step routines?

The answer to both is yes.

## What we are building first

We are starting with four concrete pieces:

1. A single **trace format** in JSONL.
2. A **canonicalizer** that normalizes brittle action details into stable action strings.
3. A simple **macro miner** that finds repeated action subsequences.
4. A simple **compression evaluator** that tells us whether the mined macros actually shorten trajectories.

That is enough to answer the first real question:

**Are browser traces compressible in a way that looks like reusable behavior rather than noise?**

## Benchmark and data decisions

### Stage 1: offline bootstrap

These are the first datasets we want to try.

1. **Mind2Web**
   Why:
   The public task data is enough for structured action-sequence studies, and the raw dump becomes a later upgrade rather than a blocker.

2. **WONDERBREAD**
   Why:
   It is explicitly workflow-oriented, which is where useful chunks are most likely to show up.

3. **WebLINX**
   Why:
   It is large and real-world, so it should tell us whether chunks survive outside curated benchmark workflows.

We are deliberately **not** starting with every dataset at once. These three are enough to test whether macro mining is even promising.

Two follow-on sources look especially useful once the initial loop is working:

1. **WebLINX 1.1 / WebLINX-BrowserGym**
   Why:
   It creates a cleaner bridge between offline demonstrations and BrowserGym-based agent evaluation.

2. **WebChain**
   Why:
   It is a very recent large-scale human trace dataset and looks like a strong future source for broader macro mining once the core pipeline is stable.

### Stage 2: controlled online evaluation

These are the benchmark environments we want for actual agent experiments.

1. **WorkArena-L1**
   Why:
   Stable, reproducible, high-volume, and cheap enough to iterate on. This should be the main benchmark for early speed/cost measurements.

2. **WebArena**
   Why:
   Good controlled transfer test for longer browser tasks.

3. **VisualWebArena**
   Why:
   Useful to see whether visually grounded tasks break text-only or DOM-only macros.

### Stage 3: realism check

1. **WebVoyager** or a small custom live-web suite
   Why:
   Good final sanity check, but not good enough for the main result because the open web changes too much.

## Why these choices are simple

We want to avoid two common failure modes:

1. Building a complex agent runtime before we know traces are compressible.
2. Chasing unstable live-web benchmarks before we have a stable measurement loop.

So the order is:

- mine offline traces first
- measure offline compressibility first
- then plug macros into a controlled browser agent
- only then test realism

## Action representation modes

The main new lesson from the public-data experiments is that we should treat **action representation** as a first-class variable.

The harness now supports seven representation modes:

1. `name_only`
   Keep only the action name such as `CLICK`, `TYPE`, `GOTO`.

2. `value_slots`
   Keep the action name and typed-value slots, but not target signatures.

3. `coarse_signature`
   Keep the action name plus coarse role classes and a small semantic label vocabulary.

4. `target_signature`
   Keep the action name plus role / label / selector signature, but not typed-value slots.

5. `signature`
   Keep the action name plus target signature plus typed-value slots.

6. `dataflow`
   Keep the action name plus anonymous variable uses and defs such as `use=B01` and `def=B02`.

7. `dataflow_coarse`
   Keep anonymous variable uses and defs, plus the `coarse_signature` target abstraction.

This is the current core experiment because it isolates the real tradeoff:

- coarse actions compress well but often collapse into generic junk
- rich actions are more meaningful but fragment badly

## What `coarse_signature` means in practice

The easiest way to think about `coarse_signature` is:

- keep the action name
- keep a **coarse target class**
- keep a **small semantic label vocabulary** when we can
- keep value slots for typed inputs
- drop brittle raw labels, selectors, and page-specific text

Examples:

| Raw-ish action | `signature` | `coarse_signature` | Why this is useful |
| --- | --- | --- | --- |
| click a button labeled "Search for flights to Seattle" | `CLICK|role=button|label=<TEXT>` or a longer page-specific label | `CLICK|role=button|label=search` | keeps the intent but removes page-specific wording |
| type `person@example.com` into Email | `TYPE|role=input|label=email|value=<EMAIL>` | `TYPE|role=input|label=email|value=<EMAIL>` | already stable, so we keep it |
| click a search-result title in an `h3` | `CLICK|role=h3|label=<TEXT>` | `CLICK|role=text|label=<TEXT>` | groups many content-title clicks together |
| click a product link | `CLICK|role=a|label=<TEXT>` | `CLICK|role=link|label=<TEXT>` | normalizes many link variants |
| click a paragraph then copy it | `CLICK|role=p|label=<TEXT>` then `COPY|role=p|label=<TEXT>` | `CLICK|role=text|label=<TEXT>` then `COPY|role=text|label=<TEXT>` | turns tag-specific noise into a reusable reading/copy routine |
| type "Seattle" into "City or Airport" | `TYPE|role=input|label=city or airport|value=<CITY>` | `TYPE|role=input|label=city|value=<CITY>` | keeps the semantic slot and simplifies the field label |
| go to `https://example.com/search?q=flights` | `GOTO|url=/search?<QUERY>` | `GOTO|url=/search?<QUERY>` | URL normalization is already coarse enough |

So `coarse_signature` is not meant to be the final abstraction. It is a cheap approximation to the thing we really want:

- `search_box`
- `primary_button`
- `result_card`
- `tab_switch`
- `copyable_text`

Right now it is the first representation that is coarse enough to reuse, but still structured enough to be more than `CLICK`.

## What `dataflow_coarse` adds

`coarse_signature` still hides whether the same value is reused across steps.

`dataflow_coarse` adds anonymous variable identity on top of that. The variable names are arbitrary and episode-local, but alpha-renamed so repeated templates line up across traces.

Examples:

| Raw-ish workflow | `coarse_signature` | `dataflow_coarse` |
| --- | --- | --- |
| type email, type password, click login | `TYPE email <EMAIL>`, `TYPE password <TEXT>`, `CLICK login` | `TYPE|role=input|label=email|use=B01`, `TYPE|role=input|label=password|use=B02`, `CLICK|role=button|label=login` |
| copy text, paste same text | `COPY|role=text|label=<TEXT>`, `PASTE|role=input|label=<TEXT>|value=<TEXT>` | `COPY|role=text|label=<TEXT>|def=B01`, `PASTE|role=input|label=<TEXT>|use=B01` |
| search with an input value | `TYPE|role=input|label=search|value=<SEARCH_TERM>`, `CLICK search` | `TYPE|role=input|label=search|use=B01`, `CLICK|role=button|label=search` |

This is closer to a function template:

- the exact literal values are gone
- reuse of the same argument is still visible
- copied or produced values can feed later actions

So `dataflow_coarse` is the first mode that can express templates like:

- `LOGIN(B01, B02)`
- `SEARCH(B01)`
- `COPY_THEN_PASTE(B01)`

## Clarifying the real objective

The real goal is **not** just to do BPE over browser traces.

The real goal is to discover units that can become:

1. **tokens**
   A shorter symbol sequence for modeling, caching, and planning.

2. **macros**
   A reusable chunk that expands to primitive actions.

3. **functions**
   A callable browser routine with parameters, preconditions, and expected effects.

That means a useful discovered unit should ideally have:

- repeated support across many episodes
- a clear parameterization pattern such as `<SEARCH_TERM>` or `<CITY>`
- a stable trigger condition
- a recognizable target state or page context
- a predictable outcome after expansion

Compression helps, but compression alone is not the finish line. A chunk like `CLICK -> CLICK -> CLICK` compresses well and is easy to cache, but it is not yet a good function.

## What we hope to see in the traces

If this project is viable, traces should show a few clear patterns.

### Expected positive patterns

1. **Repeated local routines**
   Examples:
   open page -> click search box -> type query -> click search
   open record -> edit field -> save
   open menu -> pick filter -> apply

2. **Shared structure with variable slots**
   Example:
   the same routine appears many times, but the typed values differ.

3. **Benchmark-specific routine families**
   We expect WorkArena and WebArena to have reusable routines that repeat across tasks.

4. **Human traces cleaner than agent traces**
   Human demos should produce more stable macro candidates.

### Expected negative patterns

1. **Selector noise**
   Raw selectors and DOM IDs will likely make naive trace mining useless.

2. **Spurious repeats**
   Some repeated chunks will look frequent but will not be semantically useful.

3. **State brittleness**
   Some chunks will only work on narrow page states.

4. **Long-tail actions**
   A lot of browser behavior will stay primitive and should not be forced into macros.

## What we hope to see in experiments

### Offline experiments

The first offline result we want is:

- a meaningful compression ratio from typed or slot-aware chunks
- better compression than literal raw-action mining
- macro candidates that are readable and workflow-like

If the macro list is dominated by junk like volatile selectors or URL fragments, that is a signal to improve canonicalization before we do anything else.

### Online agent experiments

The first online result we want is:

- fewer agent turns
- fewer output tokens
- lower wall-clock time per successful task
- similar or slightly better success rate on repetitive tasks

The most likely early win is **cost and turns**, not absolute success.

### Where gains should show up first

We expect the biggest gains on:

- repetitive form filling
- search-and-select workflows
- CRUD-style browser tasks
- benchmark tasks with stable page structure

We expect weaker gains on:

- novel exploratory tasks
- visually messy tasks
- tasks with heavy branching or frequent interruptions

## Initial experimental plan

### Experiment 1: offline compression

Input:

- human traces from Mind2Web and WONDERBREAD

Method:

- canonicalize actions
- mine repeated chunks
- greedily compress trajectories with those chunks

Metrics:

- compression ratio
- number of reusable macros
- support per macro
- share of episodes using at least one macro
- held-out compression on test episodes
- held-out next-token cache coverage and accuracy

Success condition:

- we find readable, repeated routines and get non-trivial compression
- held-out compression remains useful when macros are learned on train and applied to test
- tokenized traces are at least as cacheable as primitive traces on held-out episodes

## What we should measure for workflow-sized functions

If the end goal is executable workflow chunks, we should measure more than compression.

### 1. Discovery quality

These tell us whether a chunk is a serious macro candidate.

- support across episodes
- support across websites or tasks, not just one page
- average primitive span length
- number of distinct slot instantiations
- held-out reuse rate
- readability / semantic coherence of the top macros

Expected outcome:

- `name_only` should score high on support and reuse, but low on semantic quality
- `signature` should score higher on interpretability, but lower on support
- `coarse_signature` should be the best global middle ground
- `dataflow_coarse` should be the best mode for parameterized workflow templates

### 2. Parameterization quality

These tell us whether a chunk is really a function rather than a memorized trace.

- how often the same chunk appears with different values
- how often slot names are stable across episodes
- whether the same chunk works with `<CITY>`, `<DATE>`, `<EMAIL>`, and other slots
- whether a chunk can be represented as a template plus arguments

Expected outcome:

- the best function candidates will be routines like:
  - click input -> type slot value -> click search
  - click edit -> type field value -> click save
  - click text -> copy text

### 3. Trigger quality

These tell us whether an agent could safely choose the macro at runtime.

- precision of matching a macro trigger on held-out traces
- recall of macro opportunities on held-out traces
- false-trigger rate
- ambiguity rate when multiple macros could match

Expected outcome:

- pure previous-action matching will be too weak
- adding page state like URL pattern or page-type context should help a lot

### 4. Expansion / replay quality

These tell us whether the macro is actually executable.

- primitive expansion exact-match rate on held-out traces
- completion rate after expansion
- number of interruptions, retries, or branch mismatches during replay
- sensitivity to small DOM variation

Expected outcome:

- coarse semantic macros should replay better than raw selector-based macros
- fully generic chunks will replay often but may not accomplish meaningful work

### 5. Agent-level utility

These are the metrics that matter if the macros become actual agent functions.

- task success
- turns per successful task
- output tokens per successful task
- wall-clock latency
- API cost
- recovery overhead when a macro fails and the agent falls back to primitive actions

Expected outcome:

- the first gains should show up in turns, latency, and cost
- success should stay flat or slightly improve on repetitive tasks
- exploratory tasks may not benefit much

## The experiments that matter most next

### Experiment A: representation sweep

Compare:

- `name_only`
- `value_slots`
- `coarse_signature`
- `target_signature`
- `signature`
- `dataflow`
- `dataflow_coarse`

Measure:

- vocabulary size
- held-out compression
- cache coverage
- cache accuracy
- top macro readability

Expected outcome:

- already mostly confirmed
- `coarse_signature` should stay the best global browser baseline
- `dataflow_coarse` should do better once we mine within site or workflow families

### Experiment B: macro parameterization study

Take the top mined macros and ask:

- can they be written as templates with arguments?
- how many slots do they expose?
- how many distinct instantiations exist?

Measure:

- slot count per macro
- distinct argument values per macro
- support after slot abstraction

Expected outcome:

- many useful macros will collapse into a small number of templates with slots

### Experiment C: state-conditioned macro triggering

Instead of conditioning only on previous actions, condition on:

- previous actions
- URL pattern
- page type
- maybe a coarse DOM sketch

Measure:

- trigger precision
- trigger recall
- macro selection accuracy

Expected outcome:

- this should matter more than adding more BPE merges
- it is the likely path to turning macros into reliable callable functions

### Experiment D: replay-constrained macro execution

On replayable traces or controlled benchmarks, let the agent choose a macro and expand it.

Measure:

- expansion success
- fallback frequency
- task success
- turns saved
- latency saved

Expected outcome:

- short 2-5 step macros should work first
- long macros will likely need stronger state checks and interruption handling

### Experiment E: controlled online benchmark

Compare:

- primitive-only agent
- macro-aware agent with fallback

Benchmarks:

- WorkArena-L1 first
- then WebArena
- then VisualWebArena

Measure:

- success
- turns
- tokens
- cost
- latency

Expected outcome:

- early wins should appear on repetitive workflow tasks
- the main benefit should be efficiency before it is raw capability

## Public-only workflow

The simplest reproducible path now is:

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

Then rerun `compare_tokenizers.py` with the other six representation modes and compare the outputs.

## Results so far

### Dataset sizes used in the latest pass

- Public Mind2Web train shards from Hugging Face:
  - `1009` tasks
  - `7775` actions
- WebLINX BrowserGym replay sample:
  - `30` demos
  - `745` actions

### Public Mind2Web full-train sweep

| Mode | Action vocab | Held-out macro ratio | Held-out BPE ratio | Primitive cache acc | Macro cache acc | BPE cache acc |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `name_only` | 3 | 0.2974 | 0.2278 | 0.8312 | 0.3227 | 0.1241 |
| `value_slots` | 18 | 0.3145 | 0.2712 | 0.8312 | 0.2744 | 0.1185 |
| `coarse_signature` | 130 | 0.6041 | 0.6159 | 0.3210 | 0.1212 | 0.0856 |
| `dataflow` | 22 | 0.3139 | 0.2475 | 0.8335 | 0.3116 | 0.1714 |
| `dataflow_coarse` | 202 | 0.6080 | 0.6297 | 0.3179 | 0.1257 | 0.1123 |
| `target_signature` | 5864 | 0.9783 | 0.9790 | 0.0424 | 0.0202 | 0.0202 |
| `signature` | 5875 | 0.9836 | 0.9849 | 0.0416 | 0.0255 | 0.0239 |

Interpretation:

- `name_only` and `value_slots` compress very strongly and are highly cacheable.
- But the top macros are mostly generic routines like `CLICK -> CLICK -> CLICK`.
- `coarse_signature` is the first useful midpoint:
  - vocabulary drops from about `5.9k` to `130`
  - held-out compression improves a lot
  - the macros still preserve coarse target structure
- `dataflow` by itself mostly stays too generic:
  - it exposes anonymous argument reuse
  - but global mining is still dominated by generic click loops
- `dataflow_coarse` preserves the same global compression story as `coarse_signature`
  - and adds explicit variable reuse like `use=B01`
  - which matters more for site-local mining than for global mining
- `target_signature` and `signature` produce more interpretable routines such as:
  - `CLICK input -> TYPE text`
  - `TYPE first name -> TYPE last name`
- But they fragment almost completely because the action vocabulary explodes from `3-18` symbols to about `5.9k`.

This is the clearest evidence yet that our main bottleneck is **representation brittleness**, not lack of data or lack of BPE capacity. The current best global browser baseline is `coarse_signature`, while `dataflow_coarse` is the best starting point for parameterized macro discovery.

### WebLINX BrowserGym replay sweep

| Mode | Action vocab | Held-out macro ratio | Held-out BPE ratio | Primitive cache acc | Macro cache acc | BPE cache acc |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `name_only` | 12 | 0.3650 | 0.4380 | 0.6031 | 0.1591 | 0.1111 |
| `value_slots` | 36 | 0.3869 | 0.4599 | 0.6031 | 0.0638 | 0.0877 |
| `coarse_signature` | 144 | 0.7080 | 0.7737 | 0.1832 | 0.0330 | 0.0500 |
| `dataflow` | 50 | 0.4672 | 0.5182 | 0.5954 | 0.0862 | 0.0308 |
| `dataflow_coarse` | 175 | 0.7664 | 0.8248 | 0.1908 | 0.0505 | 0.0374 |
| `target_signature` | 288 | 0.8540 | 0.8905 | 0.1298 | 0.0270 | 0.0259 |
| `signature` | 289 | 0.8540 | 0.8905 | 0.1298 | 0.0270 | 0.0259 |

Interpretation:

- The same pattern shows up on more replay-like browser traces.
- Coarse actions compress best, but the resulting chunks are generic:
  - `CLICK -> CLICK`
  - `GOTO -> CLICK`
  - `CLICK -> COPY`
- `coarse_signature` is again the best middle ground:
  - it keeps useful routines like `CLICK(text) -> COPY(text)` and `OPEN_TAB -> SWITCH_TAB`
  - but it avoids most of the vocabulary explosion of raw signatures
- `dataflow_coarse` adds parameter identity:
  - `COPY ... def=B01`
  - `PASTE ... use=B01`
  - which is a better substrate for function templates than plain signatures
- Richer signatures surface better routines:
  - `OPEN_TAB -> SWITCH_TAB`
  - `SCROLL -> CLICK(div)`
  - `CLICK(textarea) -> PASTE`
- But those richer tokens still hurt simple cache accuracy.

### Site-local Mind2Web macro mining

Global mining is still too mixed to surface the most useful workflow redundancy. Grouping by site is much better.

Using `site_macro_report.py` on the top `20` Mind2Web websites:

- `dataflow_coarse` found parameterized macros in `17 / 20` sites
- total parameterized macros across those sites: `118`
- `coarse_signature` found `0` explicit parameterized macros because it does not track value identity

Examples:

- `budget`
  - `CLICK link -> TYPE zip use=B01`
  - `TYPE zip use=B01 -> CLICK text`
- `united`
  - `TYPE field use=B01 -> CLICK button`
  - `TYPE field use=B01 -> CLICK button -> TYPE field use=B02 -> CLICK button`
- `spothero`
  - `TYPE city use=B01 -> CLICK text`
- `yelp`
  - `TYPE zip use=B01 -> CLICK`
- `newegg`
  - `TYPE search use=B01 -> CLICK button`

This is much closer to the target object we actually want:

- a reusable template
- with explicit arguments
- still tied to a site or workflow family

So the current lesson is:

- global mining is good for testing representation stability
- site-local `dataflow_coarse` is better for surfacing real candidate functions

### Site-plus-workflow grouping

Grouping by site alone still mixes several intents together. The next useful synthetic key is:

- `website_task_family`

This groups episodes by:

- site or app
- a coarse workflow family inferred from the task text

Examples:

- `amazon::cart`
- `united::flight`
- `yelp::search`
- `aa::flight`
- `newegg::search`

This is still simple and fully programmable. It does not require semantic slot naming or an LLM. It just narrows mining to traces that are likely to share the same workflow skeleton.

Current Mind2Web results with `dataflow_coarse` and `website_task_family`:

- `133` reported groups with at least `3` episodes
- held-out replay precision: `0.2122`
- held-out parameterized replay precision: `0.1916`
- estimated decision reduction: `29.34%`

Compared with site-only grouping:

- replay precision improves from `0.159` to `0.2122`
- parameterized replay precision improves from `0.129` to `0.1916`

This is the clearest result so far that the redundancy we want is mostly:

- site-local
- workflow-local
- parameterized by a few anonymous values

Examples surfaced by `website_task_family`:

- `yelp::search`
  - `TYPE zip use=B01 -> CLICK`
- `united::flight`
  - `TYPE field use=B01 -> CLICK button -> TYPE field use=B02 -> CLICK button`
- `aa::flight`
  - `TYPE city use=B01 -> CLICK link -> TYPE city use=B02 -> CLICK link`
- `newegg::search`
  - `TYPE search use=B01 -> CLICK button`

### Savings and replay metrics

We now have two small evaluation scripts:

- `macro_savings_report.py`
  - estimates step reduction
  - estimates model-decision reduction
  - estimates output-token savings
  - estimates decision-latency savings
- `macro_replay_eval.py`
  - measures held-out exact replay precision from a trigger prefix
  - reports both overall and parameterized-macro replay precision

These are still offline or replay-style measurements. The latency numbers are **decision-side estimates**, not real browser wall-clock timings.

Current results for `dataflow_coarse`:

- Mind2Web global
  - decision reduction estimate: `39.2%`
  - replay precision: `5.28%`
  - parameterized replay precision: `3.98%`
- Mind2Web site-local by website
  - decision reduction estimate: `34.11%`
  - replay precision: `15.9%`
  - parameterized replay precision: `12.9%`
- Mind2Web site-local by `website_task_family`
  - decision reduction estimate: `29.34%`
  - replay precision: `21.22%`
  - parameterized replay precision: `19.16%`
- WebLINX BrowserGym global
  - decision reduction estimate: `23.36%`
  - replay precision: `4.33%`
  - parameterized replay precision: `1.32%`

Interpretation:

- the savings potential is already non-trivial
- blind global macro triggering is still too inaccurate
- site-local grouping makes replay precision much better
- site-plus-workflow grouping makes replay precision better still
- this again points to state-aware and workflow-local triggering as the next real bottleneck

Some site-local parameterized replay rates are already much stronger than the global average:

- `kayak`: `0.70`
- `gamestop`: `0.6667`
- `amazon`: `0.3333`
- `yelp`: `0.2985`
- `united`: `0.2857`

These are still small-scale and should be treated as exploratory, but they are exactly the sort of signal we want if the end goal is reusable functions.

### What this means

The project is still on track, but the target is now sharper.

What looks promising:

- public datasets are enough to keep making progress
- repeated browser routines definitely exist
- richer replay data like WebLINX BrowserGym is already useful
- coarse semantic target abstraction is a real improvement over raw signatures
- anonymous variable tracking makes parameterized macros visible
- site-local mining surfaces much more function-like redundancy than global mining

What looks unlikely to work:

- plain BPE over brittle target signatures
- using raw selectors or labels as-is and expecting good transfer
- claiming success from compression alone
- relying on global mining alone to discover site-specific workflows

## Updated next steps

The next work should be:

1. Mine within site and task families, not just globally
   Examples:
   login, search, checkout, booking flows inside one site

2. Improve `dataflow_coarse` instead of adding more raw tokenizers
   Examples:
   better role families, result-card detection, primary-action detection, modal controls

3. Add **page-state context** to the macro trigger instead of only previous actions
   Examples:
   URL pattern, form step, result-list page, detail page

4. Turn the new replay metrics into a site-family benchmark
   Examples:
   per-site replay precision, per-site step savings, parameterized macro counts

5. Measure real browser wall-clock time in a controlled benchmark
   Use WorkArena-L1 or a small local Playwright benchmark.

6. Keep raw-ish replay data in the loop
   WebLINX BrowserGym stays useful even without raw Mind2Web traces.

7. Treat raw Mind2Web `trace.zip` as a later upgrade
   Useful for finer timing and Playwright-level replay, but no longer needed to answer the current question.

### Experiment 2: macro quality by source

Compare:

- macros mined from human traces
- macros mined from model traces
- macros mined from a mixed pool

Expectation:

- human-mined macros should be cleaner and more reusable

### Experiment 3: controlled agent evaluation

Benchmark:

- WorkArena-L1

Compare:

- primitive-only agent
- primitive + macro agent

Metrics:

- task success
- wall-clock time
- tokens
- cost per successful task
- invalid-action rate

Expectation:

- hybrid agent reduces turns and cost on repetitive tasks first

## Harness shape

The harness in this repo should stay small and boring.

### Inputs

- JSONL trace events

### Outputs

- canonicalized JSONL trace events
- mined macros as JSON
- compression/eval summaries as JSON

### Scripts

- `scripts/convert_dataset.py`
- `scripts/prepare_traces.py`
- `scripts/mine_macros.py`
- `scripts/evaluate_macros.py`
- `scripts/compare_tokenizers.py`
- `scripts/profile_traces.py`

### Shared code

- `toolcalltokenization/trace_utils.py`

This is intentionally not a large package. It is just enough structure to keep the scripts from duplicating logic.

## Current repo findings

These are only from the tiny demo trace in this repo, so they are not claims about the real benchmarks yet.

### Demo result

On the sample trace:

- primitive length: 15 steps
- frequent-chunk compression: 6 steps total, ratio `0.4`
- BPE-style compression: 4 steps total, ratio `0.2667`

### What that suggests

1. BPE-style merges can compress more aggressively than fixed frequent chunks on the training set because merges can stack recursively.
2. That same property means BPE is especially vulnerable to overfitting if we only evaluate in-sample.
3. On a tiny held-out split of the demo, both frequent chunks and BPE compress the test episode from 5 steps to 2 steps, ratio `0.4`.
4. For cacheability, a 1-token next-token cache is the right starting point for compressed traces because compression makes the sequences much shorter.

The next meaningful result is therefore not “more toy compression,” but:

- run the converters on real Mind2Web / WONDERBREAD / WebLINX data
- inspect profile summaries
- compare in-sample vs held-out compression
- compare primitive vs macro vs BPE cacheability on held-out episodes

## Pilot findings on real WebLINX data

We now have one real-data pilot using the downloadable `WebLINX` validation chat split, reconstructed into action sequences by `demo` and `turn`.

### Full WebLINX chat-action slice

Current converted sample:

- 100 episodes
- 2,126 actions
- action mix dominated by `click`, `say`, and `scroll`

Observed results:

- in-sample frequent-chunk compression: `1848 / 2126`, ratio `0.8692`
- in-sample BPE compression after support filtering: `1852 / 2126`, ratio `0.8711`
- held-out frequent-chunk compression on test episodes: `415 / 477`, ratio `0.87`
- held-out BPE compression on test episodes: `419 / 477`, ratio `0.8784`

Cacheability result on held-out episodes with a 1-token prefix cache:

- primitive overall accuracy: `0.1554`
- frequent-chunk overall accuracy: `0.0253`
- BPE overall accuracy: `0.0226`

Interpretation:

- The split is heavily influenced by dialogue turns.
- The learned chunks mostly collapse repeated `say` and `scroll` behavior.
- Compression exists, but tokenization does **not** improve simple next-action caching in this representation.

### Browser-only WebLINX slice

If we drop `say` actions from the converted WebLINX split:

- 100 episodes
- 1,538 actions

Observed results:

- in-sample frequent-chunk compression: `1463 / 1538`, ratio `0.9512`
- in-sample BPE compression: `1467 / 1538`, ratio `0.9538`
- held-out frequent-chunk compression: `338 / 343`, ratio `0.9854`
- held-out BPE compression: `339 / 343`, ratio `0.9883`

Cacheability result on held-out episodes with a 1-token prefix cache:

- primitive overall accuracy: `0.0464`
- frequent-chunk overall accuracy: `0.0314`
- BPE overall accuracy: `0.0313`

Interpretation:

- Once dialogue is removed, compression becomes much weaker.
- The remaining representation is still too selector-heavy and not abstract enough.
- Better semantic canonicalization helps a bit, but not enough.

### Practical conclusion from the pilot

This is a strong signal that:

1. **Processed WebLINX chat data is not the ideal primary source** for browser macro discovery.
2. **Raw replay traces or BrowserGym-style traces are still the better target** for the main study.
3. **Canonicalization quality dominates results.** If actions are mostly opaque selectors, useful chunks do not transfer.
4. **BPE should require cross-episode support by default.** Without that, it overfits repeated patterns inside a single episode.

## New local raw-ish sources

We now have richer local sources under `data/local/`:

1. **Mind2Web train_10**
   - official task shard from `osunlp/Mind2Web`
   - about `27 MB`
   - 9 tasks and 49 actions after conversion
   - useful as an ingestion-proof and canonicalization testbed

2. **WebLINX BrowserGym replay sample**
   - 30 demos with `replay.json`, `metadata.json`, and `form.json`
   - about `195 MB` locally
   - 745 browser actions after conversion with chat excluded
   - much closer to the kind of replay-style traces we actually want

3. **One full WebLINX BrowserGym demo**
   - `apfyesq.zip` unpacked locally
   - includes screenshots, DOM snapshots, AX trees, bboxes, and extra element properties
   - this is the best current local source for improving semantic canonicalization beyond the replay event itself

## Findings from the new raw-ish sources

### Mind2Web train_10

Converted profile:

- 9 episodes
- 49 actions
- average length `5.44`

Observed result:

- no cross-episode frequent chunks
- no BPE merges under the current support thresholds

Interpretation:

- this shard is too small and diverse for chunk discovery by itself
- it is still useful for validating the Mind2Web ingestion path

### WebLINX BrowserGym replay sample, 30 demos

Converted profile:

- 30 episodes
- 745 browser actions
- average length `24.83`

Observed results:

- in-sample frequent-chunk compression: `605 / 745`, ratio `0.8121`
- in-sample BPE compression: `623 / 745`, ratio `0.8362`
- held-out frequent-chunk compression: `117 / 137`, ratio `0.854`
- held-out BPE compression: `122 / 137`, ratio `0.8905`

Held-out next-token cache with 1-token context:

- primitive overall accuracy: `0.1298`
- frequent-chunk overall accuracy: `0.027`
- BPE overall accuracy: `0.0259`

Interpretation:

- replay-style traces do show meaningful held-out compressibility
- frequent chunks currently beat BPE slightly on compression
- primitive actions are still far easier to cache with a naive next-token cache
- the data is now rich enough that better canonicalization looks like the main opportunity, not more aggressive token merging

## Trace format

Each event should be a single JSON object with simple fields like:

- `episode_id`
- `step_index`
- `action_type`
- `url`
- `target_role`
- `target_text`
- `target_label`
- `selector`
- `value`
- `slot`

The format is intentionally permissive because we want to ingest traces from:

- hand-built demos
- Playwright logs
- BrowserGym / AgentLab runs
- converted benchmark traces

## What we are not building yet

Not yet:

- full BrowserGym integration
- full Playwright runtime logging
- macro-conditioned policy learning
- a paper-ready benchmark runner
- advanced BPE or grammar induction

Those are good next steps, but the repo should first prove that the trace format and mining loop are worthwhile.

## Immediate next steps

1. Add real dataset adapters, starting with Mind2Web.
2. Add one BrowserGym trace adapter.
3. Compare frequent-chunk mining against BPE-style merges on real traces.
4. Add a typed-slot macro miner beyond simple frequent n-grams.
5. Add hybrid macro execution inside a controlled browser agent.
6. Measure online success / speed / cost on WorkArena-L1.
