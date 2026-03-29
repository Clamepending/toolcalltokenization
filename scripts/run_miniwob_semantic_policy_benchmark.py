#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.miniwob_benchmark import (
    build_group_registry,
    default_miniwob_url,
    evaluate_live_semantic_policy_benchmark,
)
from toolcalltokenization.trace_utils import dump_json, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live MiniWoB semantic macro-policy benchmark from saved traces and episodes."
    )
    parser.add_argument("--input-prefix", required=True, help="Prefix for *_traces.jsonl and *_trace_summary.json.")
    parser.add_argument("--output-prefix", required=True, help="Prefix for benchmark outputs.")
    parser.add_argument("--registry-path", default="", help="Optional existing macro registry. If omitted, rebuild from the input traces.")
    parser.add_argument("--include-task-name", action="append", default=[], help="Optional task_name filter to include. Repeatable.")
    parser.add_argument("--exclude-task-name", action="append", default=[], help="Optional task_name filter to exclude. Repeatable.")
    parser.add_argument("--group-by", default="task_name", help="Field used to group episodes for macro mining.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Trace representation to use for macro mining.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes used for mining.")
    parser.add_argument("--split-seed", type=int, default=0, help="Seed for the train/eval split.")
    parser.add_argument("--max-chunk-len", type=int, default=6, help="Maximum macro length to mine when rebuilding the registry.")
    parser.add_argument("--top-k", type=int, default=10, help="Maximum macros to keep per task family when rebuilding the registry.")
    parser.add_argument("--min-support", type=int, default=3, help="Minimum train support for a macro.")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum macro length to keep.")
    parser.add_argument("--min-registry-replay-precision", type=float, default=0.5, help="Minimum held-out replay precision required to keep a macro in the rebuilt registry.")
    parser.add_argument("--trigger-prefix-len", type=int, default=2, help="Leading-step trigger length used for held-out registry evaluation.")
    parser.add_argument("--action-scope", choices=("task", "global"), default="task", help="Whether semantic selection sees only task-local macros or one shared global action space.")
    parser.add_argument("--margin", type=float, default=0.0, help="Minimum score advantage required before selecting a macro over the current primitive step.")
    parser.add_argument("--no-start-step-guard", action="store_true", help="Disable the first-step structural compatibility guard for semantic macro selection.")
    parser.add_argument("--decision-latency-ms", type=int, default=1000, help="Estimated agent decision latency added on top of browser time.")
    parser.add_argument("--headless", action="store_true", help="Run BrowserGym in headless mode.")
    parser.add_argument("--miniwob-url", default="", help="Optional MiniWoB base URL. Defaults to the local clone in data/local/miniwob-plusplus.")
    parser.add_argument("--launch-retries", type=int, default=2, help="Number of BrowserGym relaunch retries per episode.")
    return parser.parse_args()


def load_collection(prefix: Path) -> tuple[list[dict], list[dict]]:
    rows = load_jsonl(str(prefix.with_name(prefix.name + "_traces.jsonl")))
    with open(prefix.with_name(prefix.name + "_trace_summary.json"), "r", encoding="utf-8") as handle:
        summary = json.load(handle)
    return rows, list(summary.get("episodes", []))


def filter_collection(
    rows: list[dict],
    episodes: list[dict],
    *,
    include_task_names: set[str],
    exclude_task_names: set[str],
) -> tuple[list[dict], list[dict]]:
    def keep_task(task_name: str) -> bool:
        if include_task_names and task_name not in include_task_names:
            return False
        if task_name in exclude_task_names:
            return False
        return True

    kept_episodes = [episode for episode in episodes if keep_task(str(episode.get("task_name", "")))]
    kept_ids = {str(episode.get("episode_id", "")) for episode in kept_episodes}
    kept_rows = [row for row in rows if str(row.get("episode_id", "")) in kept_ids]
    return kept_rows, kept_episodes


def main() -> None:
    args = parse_args()
    input_prefix = Path(args.input_prefix)
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    rows, episodes = load_collection(input_prefix)
    rows, episodes = filter_collection(
        rows,
        episodes,
        include_task_names=set(args.include_task_name),
        exclude_task_names=set(args.exclude_task_name),
    )

    if args.registry_path:
        with open(args.registry_path, "r", encoding="utf-8") as handle:
            registry = json.load(handle)
        registry_path = args.registry_path
    else:
        registry = build_group_registry(
            rows,
            group_by=args.group_by,
            canonicalization_mode=args.canonicalization_mode,
            train_ratio=args.train_ratio,
            split_seed=args.split_seed,
            max_chunk_len=args.max_chunk_len,
            top_k=args.top_k,
            min_support=args.min_support,
            min_length=args.min_length,
            min_replay_precision=args.min_registry_replay_precision,
            trigger_prefix_len=args.trigger_prefix_len,
        )
        registry_path = str(output_prefix.with_name(output_prefix.name + "_macro_registry.json"))
        dump_json(registry_path, registry)

    miniwob_url = args.miniwob_url or default_miniwob_url(ROOT)
    benchmark = evaluate_live_semantic_policy_benchmark(
        rows,
        episodes,
        registry,
        group_by=args.group_by,
        canonicalization_mode=args.canonicalization_mode,
        train_ratio=args.train_ratio,
        split_seed=args.split_seed,
        decision_latency_ms=args.decision_latency_ms,
        headless=args.headless,
        miniwob_url=miniwob_url,
        action_scope=args.action_scope,
        margin=args.margin,
        launch_retries=args.launch_retries,
        use_start_step_guard=not args.no_start_step_guard,
    )
    benchmark["collection"] = {
        "input_prefix": str(input_prefix),
        "registry_path": registry_path,
        "filtered_task_names": sorted({str(episode.get("task_name", "")) for episode in episodes}),
        "episodes": len(episodes),
        "rows": len(rows),
        "miniwob_url": miniwob_url,
    }
    dump_json(str(output_prefix.with_name(output_prefix.name + "_semantic_policy_benchmark.json")), benchmark)


if __name__ == "__main__":
    main()
