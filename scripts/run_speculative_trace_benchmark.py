#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.speculative_decoding import (
    build_prompt_completion,
    build_trace_episodes,
    load_jsonl,
    prefix_token_match_length,
    run_stream_generation,
    split_episodes_holdout,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MLX speculative decoding experiments on trace continuations.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "outputs" / "ottoauth_live_collection" / "canonical_trace.jsonl"),
        help="Canonical trace JSONL file.",
    )
    parser.add_argument("--website", default="amazon.com", help="Website bucket to evaluate.")
    parser.add_argument("--min-steps", type=int, default=6, help="Minimum actions per episode to keep.")
    parser.add_argument("--heldout-ratio", type=float, default=0.2, help="Held-out episode ratio.")
    parser.add_argument("--prefix-ratio", type=float, default=0.5, help="Prefix ratio for prompt/completion splits.")
    parser.add_argument(
        "--target-model",
        default="mlx-community/Qwen2.5-1.5B-Instruct-4bit",
        help="Target MLX model repo.",
    )
    parser.add_argument(
        "--draft-model",
        default="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
        help="Draft MLX model repo.",
    )
    parser.add_argument(
        "--draft-adapter-path",
        default=None,
        help="Optional MLX adapter path for the draft model.",
    )
    parser.add_argument(
        "--draft-lengths",
        default="1,2,4,6,8",
        help="Comma-separated speculative draft lengths to evaluate.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "outputs" / "speculative_decoding" / "amazon_speculative_baseline.json"),
        help="Where to write the benchmark JSON.",
    )
    return parser.parse_args()


def dump_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def aggregate_variant(episodes: list[dict]) -> dict:
    generated_tokens = sum(item["generated_tokens"] for item in episodes)
    accepted_tokens = sum(item.get("accepted_tokens", 0) for item in episodes)
    baseline_wall_time = sum(item.get("baseline_wall_time_sec", item["wall_time_sec"]) for item in episodes)
    wall_time = sum(item["wall_time_sec"] for item in episodes)
    gold_match_tokens = sum(item.get("gold_prefix_match_tokens", 0) for item in episodes)
    gold_total_tokens = sum(item.get("gold_total_tokens", 0) for item in episodes)
    target_matches = sum(1 for item in episodes if item.get("matches_target", False))
    return {
        "episodes": len(episodes),
        "generated_tokens": generated_tokens,
        "accepted_tokens": accepted_tokens,
        "acceptance_rate": (accepted_tokens / generated_tokens) if generated_tokens else 0.0,
        "wall_time_sec": wall_time,
        "baseline_wall_time_sec": baseline_wall_time,
        "speedup_vs_target": (baseline_wall_time / wall_time) if wall_time else 0.0,
        "gold_prefix_match_tokens": gold_match_tokens,
        "gold_total_tokens": gold_total_tokens,
        "gold_prefix_match_rate": (gold_match_tokens / gold_total_tokens) if gold_total_tokens else 0.0,
        "target_output_match_rate": (target_matches / len(episodes)) if episodes else 0.0,
    }


def main() -> None:
    args = parse_args()
    draft_lengths = [int(item.strip()) for item in args.draft_lengths.split(",") if item.strip()]

    rows = load_jsonl(args.input)
    episodes = build_trace_episodes(rows, website=args.website, min_steps=args.min_steps)
    train_episodes, test_episodes = split_episodes_holdout(episodes, heldout_ratio=args.heldout_ratio, min_heldout=1)
    examples = [
        build_prompt_completion(
            episode,
            prefix_ratio=args.prefix_ratio,
            min_prefix_actions=2,
            min_suffix_actions=2,
        )
        for episode in test_episodes
    ]

    from mlx_lm import load

    target_model, tokenizer = load(args.target_model)
    draft_model, draft_tokenizer = load(args.draft_model, adapter_path=args.draft_adapter_path)
    if type(tokenizer).__name__ != type(draft_tokenizer).__name__:
        raise ValueError("Draft and target tokenizers are not compatible")

    warm_prompt = examples[0]["prompt_text"] if examples else "COMPUTER|role=screenshot\nNAVIGATE|use=B01\n"
    run_stream_generation(target_model, tokenizer, warm_prompt, max_tokens=4)
    run_stream_generation(
        target_model,
        tokenizer,
        warm_prompt,
        max_tokens=4,
        draft_model=draft_model,
        num_draft_tokens=draft_lengths[0] if draft_lengths else 2,
    )

    target_episode_results = []
    speculative_results: dict[int, list[dict]] = defaultdict(list)

    for example in examples:
        gold_token_ids = tokenizer.encode(example["completion_text"], add_special_tokens=False)
        max_tokens = max(1, len(gold_token_ids))

        baseline = run_stream_generation(
            target_model,
            tokenizer,
            example["prompt_text"],
            max_tokens=max_tokens,
        )
        baseline["episode_id"] = example["episode_id"]
        baseline["task_family"] = example["task_family"]
        baseline["max_tokens"] = max_tokens
        baseline["gold_total_tokens"] = len(gold_token_ids)
        baseline["gold_prefix_match_tokens"] = prefix_token_match_length(baseline["token_ids"], gold_token_ids)
        target_episode_results.append(baseline)

        for draft_len in draft_lengths:
            speculative = run_stream_generation(
                target_model,
                tokenizer,
                example["prompt_text"],
                max_tokens=max_tokens,
                draft_model=draft_model,
                num_draft_tokens=draft_len,
            )
            speculative.update(
                {
                    "episode_id": example["episode_id"],
                    "task_family": example["task_family"],
                    "draft_length": draft_len,
                    "max_tokens": max_tokens,
                    "gold_total_tokens": len(gold_token_ids),
                    "gold_prefix_match_tokens": prefix_token_match_length(speculative["token_ids"], gold_token_ids),
                    "matches_target": speculative["token_ids"] == baseline["token_ids"],
                    "baseline_wall_time_sec": baseline["wall_time_sec"],
                    "baseline_generated_tokens": baseline["generated_tokens"],
                }
            )
            speculative_results[draft_len].append(speculative)

    payload = {
        "input": args.input,
        "website": args.website,
        "min_steps": args.min_steps,
        "heldout_ratio": args.heldout_ratio,
        "prefix_ratio": args.prefix_ratio,
        "target_model": args.target_model,
        "draft_model": args.draft_model,
        "draft_adapter_path": args.draft_adapter_path,
        "draft_lengths": draft_lengths,
        "episode_count": len(episodes),
        "train_episode_count": len(train_episodes),
        "heldout_episode_count": len(test_episodes),
        "heldout_episode_ids": [episode.episode_id for episode in test_episodes],
        "target_baseline": {
            "aggregate": aggregate_variant(
                [
                    {
                        **item,
                        "accepted_tokens": 0,
                        "matches_target": True,
                        "baseline_wall_time_sec": item["wall_time_sec"],
                    }
                    for item in target_episode_results
                ]
            ),
            "episodes": target_episode_results,
        },
        "speculative_variants": {
            str(draft_len): {
                "aggregate": aggregate_variant(results),
                "episodes": results,
            }
            for draft_len, results in sorted(speculative_results.items())
        },
    }
    dump_json(args.output, payload)


if __name__ == "__main__":
    main()
