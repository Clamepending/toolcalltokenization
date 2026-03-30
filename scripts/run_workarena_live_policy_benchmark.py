#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.llm_client import CachedOpenAIChooser, load_api_key
from toolcalltokenization.miniwob_benchmark import build_group_registry
from toolcalltokenization.trace_utils import dump_json, load_jsonl
from toolcalltokenization.workarena_benchmark import evaluate_live_workarena_policy_benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live WorkArena named-action policy benchmark from saved traces and episode summaries."
    )
    parser.add_argument("--input-prefix", required=True, help="Prefix for *_traces.jsonl and *_trace_summary.json.")
    parser.add_argument("--output-prefix", required=True, help="Prefix for benchmark outputs.")
    parser.add_argument("--registry-path", default="", help="Optional existing macro registry. If omitted, rebuild from the input traces.")
    parser.add_argument("--group-by", default="task_family", help="Field used to group episodes for macro mining and action scoping.")
    parser.add_argument("--canonicalization-mode", default="dataflow_coarse", help="Trace representation to use.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes used for training/mining.")
    parser.add_argument("--split-seed", type=int, default=0, help="Train/eval split seed.")
    parser.add_argument("--max-chunk-len", type=int, default=8, help="Maximum macro length to mine when rebuilding the registry.")
    parser.add_argument("--top-k", type=int, default=20, help="Maximum macros to keep per group when rebuilding the registry.")
    parser.add_argument("--min-support", type=int, default=3, help="Minimum train support for a macro.")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum macro length to keep.")
    parser.add_argument("--min-registry-replay-precision", type=float, default=0.5, help="Minimum held-out replay precision required to keep a macro in the rebuilt registry.")
    parser.add_argument("--trigger-prefix-len", type=int, default=2, help="Leading-step trigger length used for held-out registry evaluation.")
    parser.add_argument("--action-scope", choices=("task", "global"), default="task", help="Whether the controller sees task-local macros or one shared action space.")
    parser.add_argument("--policy-mode", choices=("primitive", "oracle", "semantic", "learned", "llm"), default="llm", help="Policy used to choose between primitives and macros.")
    parser.add_argument("--margin", type=float, default=0.0, help="Semantic margin required before choosing a macro.")
    parser.add_argument("--training-epochs", type=int, default=20, help="Perceptron epochs for the learned selector.")
    parser.add_argument("--training-seed", type=int, default=0, help="Random seed for learned selector training.")
    parser.add_argument("--no-start-step-guard", action="store_true", help="Disable the structural first-step guard before offering macros.")
    parser.add_argument("--decision-latency-ms", type=int, default=1000, help="Estimated agent decision latency.")
    parser.add_argument("--headless", action="store_true", help="Run BrowserGym in headless mode.")
    parser.add_argument("--launch-retries", type=int, default=2, help="Number of BrowserGym relaunch retries per episode.")
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI-compatible chat model used for llm policy mode.")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key-env-var", default="OPENAI_API_KEY", help="Environment variable name containing the API key.")
    parser.add_argument("--env-file", default="", help="Optional dotenv-style file containing the API key variable.")
    parser.add_argument("--cache-path", default="outputs/cache/workarena_live_llm_choices.jsonl", help="Prompt-response cache JSONL path for llm policy mode.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature for the chat model.")
    return parser.parse_args()


def load_collection(prefix: Path) -> tuple[list[dict], list[dict]]:
    rows = load_jsonl(str(prefix.with_name(prefix.name + "_traces.jsonl")))
    with open(prefix.with_name(prefix.name + "_trace_summary.json"), "r", encoding="utf-8") as handle:
        summary = json.load(handle)
    return rows, list(summary.get("episodes", []))


def main() -> None:
    args = parse_args()
    input_prefix = Path(args.input_prefix)
    output_prefix = Path(args.output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    rows, episodes = load_collection(input_prefix)

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

    chooser = None
    if args.policy_mode == "llm":
        api_key = load_api_key(api_key_env_var=args.api_key_env_var, env_file=args.env_file)
        chooser = CachedOpenAIChooser(
            model=args.model,
            api_key=api_key,
            base_url=args.base_url,
            cache_path=args.cache_path,
            temperature=args.temperature,
        )

    benchmark = evaluate_live_workarena_policy_benchmark(
        rows,
        episodes,
        registry,
        group_by=args.group_by,
        canonicalization_mode=args.canonicalization_mode,
        train_ratio=args.train_ratio,
        split_seed=args.split_seed,
        action_scope=args.action_scope,
        policy_mode=args.policy_mode,
        margin=args.margin,
        use_start_step_guard=not args.no_start_step_guard,
        training_epochs=args.training_epochs,
        training_seed=args.training_seed,
        llm_chooser=chooser,
        decision_latency_ms=args.decision_latency_ms,
        headless=args.headless,
        launch_retries=args.launch_retries,
    )
    benchmark["collection"] = {
        "input_prefix": str(input_prefix),
        "registry_path": registry_path,
        "episodes": len(episodes),
        "rows": len(rows),
    }
    if args.policy_mode == "llm":
        benchmark["llm"] = {
            "model": args.model,
            "base_url": args.base_url,
            "api_key_env_var": args.api_key_env_var,
            "cache_path": args.cache_path,
            "temperature": args.temperature,
        }
    dump_json(str(output_prefix.with_name(output_prefix.name + "_live_policy_benchmark.json")), benchmark)


if __name__ == "__main__":
    main()
