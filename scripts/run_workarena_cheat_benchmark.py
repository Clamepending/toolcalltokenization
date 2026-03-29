#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.miniwob_benchmark import build_group_registry, evaluate_live_replay_benchmark, save_collection
from toolcalltokenization.trace_utils import dump_json
from toolcalltokenization.workarena_benchmark import WORKARENA_SERVICE_CATALOG_TASKS, collect_workarena_cheat_traces


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect real WorkArena cheat traces, mine macros, and estimate held-out replay savings."
    )
    parser.add_argument("--output-prefix", required=True, help="Output prefix for traces, registry, and benchmark JSON.")
    parser.add_argument("--episodes-per-task", type=int, default=2, help="Number of seeds to run per WorkArena task.")
    parser.add_argument("--seed-start", type=int, default=0, help="First seed to run for each task.")
    parser.add_argument("--headless", action="store_true", help="Run BrowserGym in headless mode.")
    parser.add_argument("--group-by", default="task_family", help="Field used to group episodes for macro mining.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Trace representation to use for macro mining.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes used for mining.")
    parser.add_argument("--split-seed", type=int, default=0, help="Seed for the train/eval split.")
    parser.add_argument("--max-chunk-len", type=int, default=8, help="Maximum macro length to mine.")
    parser.add_argument("--top-k", type=int, default=20, help="Maximum macros to keep per group.")
    parser.add_argument("--min-support", type=int, default=3, help="Minimum train support for a macro.")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum macro length to keep.")
    parser.add_argument("--min-replay-precision", type=float, default=0.5, help="Minimum held-out replay precision required to keep a macro.")
    parser.add_argument("--trigger-prefix-len", type=int, default=2, help="Leading-step trigger length used for held-out replay evaluation.")
    parser.add_argument("--decision-latency-ms", type=int, default=1000, help="Estimated agent decision latency added on top of browser time.")
    parser.add_argument("--tasks", nargs="*", default=list(WORKARENA_SERVICE_CATALOG_TASKS), help="Optional subset of WorkArena env ids to run.")
    parser.add_argument("--launch-retries", type=int, default=2, help="Number of BrowserGym relaunch retries per episode.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    collection = collect_workarena_cheat_traces(
        tasks=args.tasks,
        episodes_per_task=args.episodes_per_task,
        seed_start=args.seed_start,
        headless=args.headless,
        launch_retries=args.launch_retries,
    )
    saved = save_collection(str(output_prefix), collection)

    registry = build_group_registry(
        collection["rows"],
        group_by=args.group_by,
        canonicalization_mode=args.canonicalization_mode,
        train_ratio=args.train_ratio,
        split_seed=args.split_seed,
        max_chunk_len=args.max_chunk_len,
        top_k=args.top_k,
        min_support=args.min_support,
        min_length=args.min_length,
        min_replay_precision=args.min_replay_precision,
        trigger_prefix_len=args.trigger_prefix_len,
    )
    registry_path = str(output_prefix.with_name(output_prefix.name + "_macro_registry.json"))
    dump_json(registry_path, registry)

    benchmark = evaluate_live_replay_benchmark(
        collection["rows"],
        collection["episodes"],
        registry,
        group_by=args.group_by,
        canonicalization_mode=args.canonicalization_mode,
        train_ratio=args.train_ratio,
        split_seed=args.split_seed,
        decision_latency_ms=args.decision_latency_ms,
    )
    benchmark["collection"] = {
        "traces_path": saved["traces_path"],
        "summary_path": saved["summary_path"],
        "registry_path": registry_path,
        "tasks": list(args.tasks),
    }
    benchmark_path = str(output_prefix.with_name(output_prefix.name + "_benchmark.json"))
    dump_json(benchmark_path, benchmark)


if __name__ == "__main__":
    main()
