#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.speculative_decoding import (
    build_prompt_completion,
    build_trace_episodes,
    load_jsonl,
    split_episodes_holdout,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run small-model-only speculative proxy benchmark on held-out traces.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "outputs" / "ottoauth_live_collection" / "canonical_trace.jsonl"),
        help="Canonical trace JSONL file.",
    )
    parser.add_argument("--website", default="amazon.com")
    parser.add_argument("--min-steps", type=int, default=6)
    parser.add_argument("--heldout-ratio", type=float, default=0.2)
    parser.add_argument("--prefix-ratio", type=float, default=0.5)
    parser.add_argument(
        "--model",
        default="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
        help="Small MLX model repo.",
    )
    parser.add_argument("--adapter-path", default=None, help="Optional MLX adapter path.")
    parser.add_argument("--draft-lengths", default="1,2,4,6,8")
    parser.add_argument(
        "--output",
        default=str(ROOT / "outputs" / "speculative_decoding" / "amazon_proxy_baseline.json"),
        help="Output JSON path.",
    )
    return parser.parse_args()


def dump_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def expected_speedup_upper_bound(acceptance_probability: float, horizon: int) -> float:
    p = max(0.0, min(1.0, float(acceptance_probability)))
    h = max(1, int(horizon))
    return 1.0 + sum(p**i for i in range(1, h + 1))


def main() -> None:
    args = parse_args()
    draft_lengths = [int(item.strip()) for item in args.draft_lengths.split(",") if item.strip()]

    rows = load_jsonl(args.input)
    episodes = build_trace_episodes(rows, website=args.website, min_steps=args.min_steps)
    _, heldout = split_episodes_holdout(episodes, heldout_ratio=args.heldout_ratio, min_heldout=1)
    examples = [
        build_prompt_completion(
            episode,
            prefix_ratio=args.prefix_ratio,
            min_prefix_actions=2,
            min_suffix_actions=2,
        )
        for episode in heldout
    ]

    import mlx.core as mx
    from mlx_lm import load
    from mlx_lm.generate import generate_step

    model, tokenizer = load(args.model, adapter_path=args.adapter_path)

    total_tokens = 0
    correct_tokens = 0
    episode_stats = []
    for example in examples:
        prompt_tokens = tokenizer.encode(example["prompt_text"])
        gold_tokens = tokenizer.encode(example["completion_text"], add_special_tokens=False)
        prefix_tokens = list(prompt_tokens)
        episode_correct = 0
        for gold_token in gold_tokens:
            token, _ = next(generate_step(mx.array(prefix_tokens), model, max_tokens=1))
            if int(token) == int(gold_token):
                episode_correct += 1
            prefix_tokens.append(int(gold_token))
        total_tokens += len(gold_tokens)
        correct_tokens += episode_correct
        episode_stats.append(
            {
                "episode_id": example["episode_id"],
                "task_family": example["task_family"],
                "gold_tokens": len(gold_tokens),
                "correct_next_tokens": episode_correct,
                "next_token_accuracy": (episode_correct / len(gold_tokens)) if gold_tokens else 0.0,
            }
        )

    acceptance_probability = (correct_tokens / total_tokens) if total_tokens else 0.0
    payload = {
        "input": args.input,
        "website": args.website,
        "min_steps": args.min_steps,
        "heldout_ratio": args.heldout_ratio,
        "prefix_ratio": args.prefix_ratio,
        "model": args.model,
        "adapter_path": args.adapter_path,
        "heldout_episode_ids": [episode.episode_id for episode in heldout],
        "heldout_episode_count": len(heldout),
        "total_eval_tokens": total_tokens,
        "correct_next_tokens": correct_tokens,
        "acceptance_probability_proxy": acceptance_probability,
        "episodes": episode_stats,
        "draft_lengths": draft_lengths,
        "speedup_upper_bounds": {
            str(horizon): expected_speedup_upper_bound(acceptance_probability, horizon)
            for horizon in draft_lengths
        },
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
