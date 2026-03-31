from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def infer_task_family(task: str) -> str:
    text = (task or "").lower()
    if "add to cart" in text or "cart" in text:
        return "cart"
    if "checkout" in text or "order review" in text:
        return "checkout"
    if "search for" in text or "first plausible product result" in text:
        return "search"
    return "other"


@dataclass
class TraceEpisode:
    episode_id: str
    website: str
    task_family: str
    task: str
    actions: list[str]

    @property
    def step_count(self) -> int:
        return len(self.actions)

    @property
    def text(self) -> str:
        return "\n".join(self.actions) + "\n"


def build_trace_episodes(
    rows: list[dict[str, Any]],
    *,
    website: str | None = None,
    min_steps: int = 1,
) -> list[TraceEpisode]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if website and str(row.get("website") or "") != website:
            continue
        grouped[str(row["episode_id"])].append(row)

    episodes: list[TraceEpisode] = []
    for episode_id, episode_rows in sorted(grouped.items()):
        ordered = sorted(episode_rows, key=lambda row: int(row.get("step_index", 0)))
        actions = [str(row.get("canonical_action") or "") for row in ordered if str(row.get("canonical_action") or "")]
        if len(actions) < min_steps:
            continue
        task = str(ordered[0].get("task") or "")
        episodes.append(
            TraceEpisode(
                episode_id=episode_id,
                website=str(ordered[0].get("website") or ""),
                task_family=infer_task_family(task),
                task=task,
                actions=actions,
            )
        )
    return episodes


def split_episodes_holdout(
    episodes: list[TraceEpisode],
    *,
    heldout_ratio: float = 0.2,
    min_heldout: int = 1,
) -> tuple[list[TraceEpisode], list[TraceEpisode]]:
    ordered = sorted(episodes, key=lambda episode: episode.episode_id)
    if len(ordered) < 2:
        return ordered, []
    ratio = max(0.0, min(1.0, float(heldout_ratio)))
    heldout = min(max(min_heldout, math.ceil(len(ordered) * ratio)), len(ordered) - 1)
    return ordered[:-heldout], ordered[-heldout:]


def split_train_valid_test(
    episodes: list[TraceEpisode],
    *,
    heldout_ratio: float = 0.2,
    valid_ratio_within_train: float = 0.2,
    min_valid: int = 1,
) -> tuple[list[TraceEpisode], list[TraceEpisode], list[TraceEpisode]]:
    train_pool, test = split_episodes_holdout(episodes, heldout_ratio=heldout_ratio, min_heldout=1)
    if len(train_pool) < 2:
        return train_pool, [], test
    valid = min(max(min_valid, math.ceil(len(train_pool) * valid_ratio_within_train)), len(train_pool) - 1)
    return train_pool[:-valid], train_pool[-valid:], test


def build_prompt_completion(
    episode: TraceEpisode,
    *,
    prefix_ratio: float = 0.5,
    min_prefix_actions: int = 2,
    min_suffix_actions: int = 2,
) -> dict[str, Any]:
    if episode.step_count < (min_prefix_actions + min_suffix_actions):
        raise ValueError(f"Episode {episode.episode_id} is too short for prompt/completion split")
    prefix_len = max(min_prefix_actions, math.floor(episode.step_count * prefix_ratio))
    prefix_len = min(prefix_len, episode.step_count - min_suffix_actions)
    prompt_actions = episode.actions[:prefix_len]
    completion_actions = episode.actions[prefix_len:]
    return {
        "episode_id": episode.episode_id,
        "task_family": episode.task_family,
        "website": episode.website,
        "prompt_actions": prompt_actions,
        "completion_actions": completion_actions,
        "prompt_text": "\n".join(prompt_actions) + "\n",
        "completion_text": "\n".join(completion_actions) + "\n",
        "prompt_step_count": len(prompt_actions),
        "completion_step_count": len(completion_actions),
        "total_step_count": episode.step_count,
    }


def export_text_dataset(path: str | Path, episodes: list[TraceEpisode]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            payload = {
                "episode_id": episode.episode_id,
                "website": episode.website,
                "task_family": episode.task_family,
                "text": episode.text,
            }
            handle.write(json.dumps(payload) + "\n")


def run_stream_generation(
    model: Any,
    tokenizer: Any,
    prompt_text: str,
    *,
    max_tokens: int,
    draft_model: Any | None = None,
    num_draft_tokens: int | None = None,
) -> dict[str, Any]:
    from mlx_lm import stream_generate

    kwargs: dict[str, Any] = {"max_tokens": max_tokens}
    if draft_model is not None:
        kwargs["draft_model"] = draft_model
        if num_draft_tokens is not None:
            kwargs["num_draft_tokens"] = num_draft_tokens

    start = time.perf_counter()
    responses = list(stream_generate(model, tokenizer, prompt_text, **kwargs))
    wall_time = time.perf_counter() - start

    if not responses:
        return {
            "text": "",
            "token_ids": [],
            "generated_tokens": 0,
            "accepted_tokens": 0,
            "acceptance_rate": 0.0,
            "wall_time_sec": wall_time,
            "generation_tps": 0.0,
            "prompt_tokens": 0,
            "peak_memory_gb": 0.0,
        }

    final = responses[-1]
    text = "".join(response.text for response in responses)
    nonfinal_tokens = [response.token for response in responses[:-1]]
    token_ids = list(nonfinal_tokens)
    if final.generation_tokens > len(nonfinal_tokens):
        token_ids.append(final.token)

    accepted = sum(1 for response in responses[:-1] if response.from_draft)
    if final.generation_tokens > len(nonfinal_tokens) and final.from_draft:
        accepted += 1

    generated_tokens = int(final.generation_tokens)
    return {
        "text": text,
        "token_ids": token_ids,
        "generated_tokens": generated_tokens,
        "accepted_tokens": accepted,
        "acceptance_rate": (accepted / generated_tokens) if generated_tokens else 0.0,
        "wall_time_sec": wall_time,
        "generation_tps": float(final.generation_tps),
        "prompt_tokens": int(final.prompt_tokens),
        "peak_memory_gb": float(final.peak_memory),
        "finish_reason": final.finish_reason,
    }


def prefix_token_match_length(predicted: list[int], gold: list[int]) -> int:
    matched = 0
    for pred, gold_token in zip(predicted, gold):
        if pred != gold_token:
            break
        matched += 1
    return matched
