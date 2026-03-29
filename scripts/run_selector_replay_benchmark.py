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
from toolcalltokenization.selector_benchmark import evaluate_selector_replay
from toolcalltokenization.trace_utils import dump_json, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate named macro selection on existing trace datasets by replay.")
    parser.add_argument("--rows-path", required=True, help="JSONL trace rows to evaluate.")
    parser.add_argument("--registry-path", required=True, help="Promoted macro registry JSON.")
    parser.add_argument("--output-path", required=True, help="Path to write the replay benchmark JSON.")
    parser.add_argument("--group-by", default="", help="Optional grouping key override. Defaults to the registry value.")
    parser.add_argument("--canonicalization-mode", default="", help="Optional canonicalization mode override. Defaults to the registry value.")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Fraction of episodes used for training/mining.")
    parser.add_argument("--split-seed", type=int, default=0, help="Train/eval split seed.")
    parser.add_argument("--action-scope", choices=("task", "global"), default="task", help="Whether to expose only local macros or one shared macro vocabulary.")
    parser.add_argument("--policy-mode", choices=("oracle", "semantic", "learned", "llm"), default="learned", help="Macro selection policy to evaluate.")
    parser.add_argument("--margin", type=float, default=0.0, help="Semantic margin required before choosing a macro over a primitive.")
    parser.add_argument("--training-epochs", type=int, default=8, help="Perceptron epochs for the learned selector.")
    parser.add_argument("--training-seed", type=int, default=0, help="Random seed for learned selector training.")
    parser.add_argument("--no-start-step-guard", action="store_true", help="Disable the structural first-step guard before offering macros.")
    parser.add_argument("--model", default="gpt-4.1-mini", help="OpenAI-compatible chat model used for LLM selection.")
    parser.add_argument("--base-url", default="https://api.openai.com/v1", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key-env-var", default="OPENAI_API_KEY", help="Environment variable name containing the API key.")
    parser.add_argument("--env-file", default="", help="Optional dotenv-style file containing the API key variable.")
    parser.add_argument("--cache-path", default="outputs/cache/selector_llm_choices.jsonl", help="Prompt-response cache JSONL path for the LLM selector.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature for the chat model.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.rows_path)
    with open(args.registry_path, "r", encoding="utf-8") as handle:
        registry = json.load(handle)

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

    result = evaluate_selector_replay(
        rows,
        registry,
        group_by=args.group_by or str(registry.get("group_by", "task_name")),
        canonicalization_mode=args.canonicalization_mode or str(registry.get("canonicalization_mode", "dataflow_coarse")),
        train_ratio=args.train_ratio,
        split_seed=args.split_seed,
        action_scope=args.action_scope,
        policy_mode=args.policy_mode,
        margin=args.margin,
        use_start_step_guard=not args.no_start_step_guard,
        training_epochs=args.training_epochs,
        training_seed=args.training_seed,
        llm_chooser=chooser,
    )
    if args.policy_mode == "llm":
        result["llm"] = {
            "model": args.model,
            "base_url": args.base_url,
            "api_key_env_var": args.api_key_env_var,
            "cache_path": args.cache_path,
            "temperature": args.temperature,
        }
    dump_json(args.output_path, result)


if __name__ == "__main__":
    main()
