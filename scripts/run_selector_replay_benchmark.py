#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    parser.add_argument("--policy-mode", choices=("oracle", "semantic", "learned"), default="learned", help="Macro selection policy to evaluate.")
    parser.add_argument("--margin", type=float, default=0.0, help="Semantic margin required before choosing a macro over a primitive.")
    parser.add_argument("--training-epochs", type=int, default=8, help="Perceptron epochs for the learned selector.")
    parser.add_argument("--training-seed", type=int, default=0, help="Random seed for learned selector training.")
    parser.add_argument("--no-start-step-guard", action="store_true", help="Disable the structural first-step guard before offering macros.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.rows_path)
    with open(args.registry_path, "r", encoding="utf-8") as handle:
        registry = json.load(handle)

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
    )
    dump_json(args.output_path, result)


if __name__ == "__main__":
    main()
