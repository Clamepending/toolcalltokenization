# Project Plan

Date: 2026-03-28

## Goal

Build the smallest useful experiment for this question:

**Can we mine repeated browser-action chunks from traces, expose them as higher-level actions, and reduce cost / latency without hurting task success?**

This repo should stay simple. The first milestone is **offline and replay-oriented**, not a full agent platform.

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
   It is the best immediate source of replayable human browser traces with screenshots, snapshots, HAR, and Playwright traces.

2. **WONDERBREAD**
   Why:
   It is explicitly workflow-oriented, which is where useful chunks are most likely to show up.

3. **WebLINX**
   Why:
   It is large and real-world, so it should tell us whether chunks survive outside curated benchmark workflows.

We are deliberately **not** starting with every dataset at once. These three are enough to test whether macro mining is even promising.

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

Success condition:

- we find readable, repeated routines and get non-trivial compression

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

- `scripts/prepare_traces.py`
- `scripts/mine_macros.py`
- `scripts/evaluate_macros.py`

### Shared code

- `toolcalltokenization/trace_utils.py`

This is intentionally not a large package. It is just enough structure to keep the scripts from duplicating logic.

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
3. Add a typed-slot macro miner beyond simple frequent n-grams.
4. Add hybrid macro execution inside a controlled browser agent.
5. Measure online success / speed / cost on WorkArena-L1.
