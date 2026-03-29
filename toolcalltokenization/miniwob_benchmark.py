from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Callable, Dict, Iterable, List, Sequence
import re

from .trace_utils import (
    compress_sequence,
    dump_json,
    dump_jsonl,
    evaluate_macro_replay,
    group_rows,
    group_sequences,
    macro_has_binding,
    macro_interface,
    mine_frequent_chunks,
    represent_rows,
    split_sequences,
)


Step = Dict[str, object]
TaskBuilder = Callable[[str, dict], List[Step]]


MINIWOB_TASKS = (
    "browsergym/miniwob.choose-list",
    "browsergym/miniwob.enter-password",
    "browsergym/miniwob.enter-text",
    "browsergym/miniwob.enter-text-dynamic",
    "browsergym/miniwob.form-sequence-2",
    "browsergym/miniwob.form-sequence-3",
    "browsergym/miniwob.login-user",
    "browsergym/miniwob.use-autocomplete",
)


def default_miniwob_url(root: Path | None = None) -> str:
    base = (root or Path(__file__).resolve().parents[1]) / "data" / "local" / "miniwob-plusplus" / "miniwob" / "html" / "miniwob"
    return f"file://{base.resolve()}/"


def task_name_for_env_id(env_id: str) -> str:
    short = str(env_id).split(".", 1)[-1]
    return short.replace("-", "_")


def episode_id_for(task_name: str, seed: int) -> str:
    return f"{task_name}::{seed:04d}"


def quoted_values(text: str) -> List[str]:
    return re.findall(r'"([^"]+)"', str(text))


def find_bid_by_role_name(obs: dict, role: str, name: str) -> str:
    expected_role = str(role or "").strip().lower()
    expected_name = str(name or "").strip().lower()
    for node in obs.get("axtree_object", {}).get("nodes", []):
        bid = node.get("browsergym_id")
        node_role = (node.get("role", {}) or {}).get("value", "")
        node_name = (node.get("name", {}) or {}).get("value", "")
        if not bid:
            continue
        if str(node_role).strip().lower() != expected_role:
            continue
        if str(node_name).strip().lower() != expected_name:
            continue
        return str(bid)
    raise ValueError(f"Could not find bid for role={role!r} name={name!r}")


def first_bid_for_role(obs: dict, role: str) -> str:
    expected_role = str(role or "").strip().lower()
    for node in obs.get("axtree_object", {}).get("nodes", []):
        bid = node.get("browsergym_id")
        node_role = (node.get("role", {}) or {}).get("value", "")
        if bid and str(node_role).strip().lower() == expected_role:
            return str(bid)
    raise ValueError(f"Could not find bid for role={role!r}")


def primitive_step(
    kind: str,
    bid: str,
    *,
    value: str = "",
    target_role: str = "",
    target_label: str = "",
    enable_autocomplete: bool = False,
) -> Step:
    step = {
        "kind": kind,
        "bid": str(bid),
        "target_role": target_role,
        "target_label": target_label,
    }
    if value:
        step["value"] = value
    if enable_autocomplete:
        step["enable_autocomplete"] = True
    return step


def render_action(step: Step) -> str:
    kind = str(step["kind"])
    bid = repr(str(step["bid"]))
    if kind == "click":
        return f"click({bid})"
    if kind == "fill":
        value = repr(str(step.get("value", "")))
        if step.get("enable_autocomplete"):
            return f"fill({bid}, {value}, True)"
        return f"fill({bid}, {value})"
    if kind == "select":
        value = repr(str(step.get("value", "")))
        return f"select_option({bid}, {value})"
    raise ValueError(f"Unsupported MiniWoB step kind: {kind!r}")


def build_choose_list(goal: str, obs: dict) -> List[Step]:
    match = re.search(r"Select (.+?) from the list", goal)
    if not match:
        raise ValueError(f"Could not parse choose-list goal: {goal!r}")
    option = match.group(1)
    return [
        primitive_step("select", first_bid_for_role(obs, "combobox"), value=option, target_role="combobox", target_label="list"),
        primitive_step("click", find_bid_by_role_name(obs, "button", "Submit"), target_role="button", target_label="submit"),
    ]


def build_click_button_sequence(goal: str, obs: dict) -> List[Step]:
    match = re.search(r"Click button (.+?), then click button (.+?)\.", goal)
    if not match:
        raise ValueError(f"Could not parse click-button-sequence goal: {goal!r}")
    first_label, second_label = match.groups()
    return [
        primitive_step("click", find_bid_by_role_name(obs, "button", first_label), target_role="button", target_label=first_label.lower()),
        primitive_step("click", find_bid_by_role_name(obs, "button", second_label), target_role="button", target_label=second_label.lower()),
    ]


def build_enter_password(goal: str, obs: dict) -> List[Step]:
    values = quoted_values(goal)
    if len(values) != 1:
        raise ValueError(f"Could not parse enter-password goal: {goal!r}")
    password = values[0]
    return [
        primitive_step("fill", "16", value=password, target_role="textbox", target_label="password"),
        primitive_step("fill", "19", value=password, target_role="textbox", target_label="verify_password"),
        primitive_step("click", find_bid_by_role_name(obs, "button", "Submit"), target_role="button", target_label="submit"),
    ]


def build_enter_text(goal: str, obs: dict) -> List[Step]:
    values = quoted_values(goal)
    if len(values) != 1:
        raise ValueError(f"Could not parse enter-text goal: {goal!r}")
    text = values[0]
    return [
        primitive_step("fill", "14", value=text, target_role="textbox", target_label="text"),
        primitive_step("click", find_bid_by_role_name(obs, "button", "Submit"), target_role="button", target_label="submit"),
    ]


def build_form_sequence_2(goal: str, obs: dict) -> List[Step]:
    values = quoted_values(goal)
    match = re.search(r"Check the (\d)(?:st|nd|rd|th) radio button and enter the number", goal)
    textbox_match = re.search(r"into the (\d)(?:st|nd|rd|th) textbox", goal)
    if len(values) != 1 or not match or not textbox_match:
        raise ValueError(f"Could not parse form-sequence-2 goal: {goal!r}")
    number = values[0]
    radio_bid = str(15 + int(match.group(1)))
    textbox_bid = str(19 + int(textbox_match.group(1)))
    return [
        primitive_step("click", radio_bid, target_role="radio", target_label=f"radio_{match.group(1)}"),
        primitive_step("fill", textbox_bid, value=number, target_role="textbox", target_label=f"textbox_{textbox_match.group(1)}"),
        primitive_step("click", find_bid_by_role_name(obs, "button", "Submit"), target_role="button", target_label="submit"),
    ]


def build_form_sequence_3(goal: str, obs: dict) -> List[Step]:
    match = re.search(r"Choose (.+?) from the dropdown, then click the button labeled \"(.+?)\"", goal)
    if not match:
        raise ValueError(f"Could not parse form-sequence-3 goal: {goal!r}")
    option, button_label = match.groups()
    return [
        primitive_step("select", first_bid_for_role(obs, "combobox"), value=option, target_role="combobox", target_label="dropdown"),
        primitive_step("click", find_bid_by_role_name(obs, "button", button_label), target_role="button", target_label=button_label.lower()),
    ]


def build_login_user(goal: str, obs: dict) -> List[Step]:
    values = quoted_values(goal)
    if len(values) != 2:
        raise ValueError(f"Could not parse login-user goal: {goal!r}")
    username, password = values
    return [
        primitive_step("fill", "16", value=username, target_role="textbox", target_label="username"),
        primitive_step("fill", "19", value=password, target_role="textbox", target_label="password"),
        primitive_step("click", find_bid_by_role_name(obs, "button", "Login"), target_role="button", target_label="login"),
    ]


def build_use_autocomplete(goal: str, obs: dict) -> List[Step]:
    values = quoted_values(goal)
    if not values:
        raise ValueError(f"Could not parse use-autocomplete goal: {goal!r}")
    prefix = values[0]
    return [
        primitive_step("fill", "17", value=prefix, target_role="textbox", target_label="tags", enable_autocomplete=True),
        primitive_step("click", "21", target_role="listitem", target_label="autocomplete_option"),
        primitive_step("click", find_bid_by_role_name(obs, "button", "Submit"), target_role="button", target_label="submit"),
    ]


TASK_BUILDERS: Dict[str, TaskBuilder] = {
    "choose_list": build_choose_list,
    "click_button_sequence": build_click_button_sequence,
    "enter_password": build_enter_password,
    "enter_text": build_enter_text,
    "enter_text_dynamic": build_enter_text,
    "form_sequence_2": build_form_sequence_2,
    "form_sequence_3": build_form_sequence_3,
    "login_user": build_login_user,
    "use_autocomplete": build_use_autocomplete,
}


def build_plan(task_name: str, goal: str, obs: dict) -> List[Step]:
    if task_name not in TASK_BUILDERS:
        raise ValueError(f"Unsupported MiniWoB benchmark task: {task_name!r}")
    return TASK_BUILDERS[task_name](goal, obs)


def step_to_trace_row(
    *,
    task_name: str,
    env_id: str,
    seed: int,
    goal: str,
    step_index: int,
    step: Step,
    action: str,
    url: str,
    step_duration_ms: float,
) -> dict:
    kind = str(step["kind"])
    action_type = {"fill": "type", "click": "click", "select": "select"}[kind]
    row = {
        "episode_id": episode_id_for(task_name, seed),
        "task_name": task_name,
        "benchmark": "miniwob",
        "website": "miniwob",
        "env_id": env_id,
        "seed": seed,
        "task": goal,
        "confirmed_task": goal,
        "step_index": step_index,
        "action_type": action_type,
        "action_name": kind,
        "raw_action_repr": action,
        "selector": str(step["bid"]),
        "target_role": str(step.get("target_role", "")),
        "target_label": str(step.get("target_label", "")),
        "url": url,
        "step_duration_ms": round(step_duration_ms, 3),
    }
    if "value" in step:
        row["value"] = str(step["value"])
    return row


def collect_miniwob_traces(
    *,
    tasks: Sequence[str] = MINIWOB_TASKS,
    episodes_per_task: int = 20,
    seed_start: int = 0,
    headless: bool = True,
    miniwob_url: str | None = None,
) -> dict:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401

    rows: List[dict] = []
    episodes: List[dict] = []

    if miniwob_url:
        import os

        os.environ["MINIWOB_URL"] = miniwob_url

    for env_id in tasks:
        task_name = task_name_for_env_id(env_id)
        for seed in range(seed_start, seed_start + episodes_per_task):
            env = gym.make(env_id, headless=headless)
            obs, _ = env.reset(seed=seed)
            goal = str(obs.get("goal", ""))
            plan = build_plan(task_name, goal, obs)
            step_rows: List[dict] = []
            browser_time_ms = 0.0
            success = False
            final_reward = 0.0
            final_error = ""
            done = False

            for step_index, step in enumerate(plan):
                action = render_action(step)
                start = perf_counter()
                obs, reward, terminated, truncated, info = env.step(action)
                elapsed_ms = (perf_counter() - start) * 1000.0
                browser_time_ms += elapsed_ms
                final_reward = float(reward)
                final_error = str(obs.get("last_action_error", ""))
                step_rows.append(
                    step_to_trace_row(
                        task_name=task_name,
                        env_id=env_id,
                        seed=seed,
                        goal=goal,
                        step_index=step_index,
                        step=step,
                        action=action,
                        url=str(obs.get("url", "")),
                        step_duration_ms=elapsed_ms,
                    )
                )
                if terminated or truncated:
                    done = True
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                    break

            env.close()
            rows.extend(step_rows)
            episodes.append(
                {
                    "episode_id": episode_id_for(task_name, seed),
                    "task_name": task_name,
                    "env_id": env_id,
                    "seed": seed,
                    "goal": goal,
                    "primitive_steps": len(step_rows),
                    "browser_time_ms": round(browser_time_ms, 3),
                    "success": success,
                    "reward": final_reward,
                    "done": done,
                    "last_action_error": final_error,
                    "actions": [row["raw_action_repr"] for row in step_rows],
                }
            )

    return {"rows": rows, "episodes": episodes}


def build_group_registry(
    rows: Sequence[dict],
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    max_chunk_len: int = 6,
    top_k: int = 10,
    min_support: int = 3,
    min_length: int = 2,
    min_replay_precision: float = 0.5,
    trigger_prefix_len: int = 1,
) -> dict:
    grouped_rows = group_rows(rows, group_by)
    registry: List[dict] = []
    groups: List[dict] = []

    for group_key, group in sorted(grouped_rows.items()):
        represented_rows = represent_rows(group, mode=canonicalization_mode)
        sequences = group_sequences(represented_rows)
        train_sequences, eval_sequences = split_sequences(sequences, train_ratio=train_ratio, seed=split_seed)
        if not eval_sequences:
            train_sequences = sequences
            eval_sequences = sequences
        macros = mine_frequent_chunks(
            train_sequences,
            min_support=min_support,
            max_chunk_len=max_chunk_len,
            top_k=top_k,
        )
        if not macros:
            continue
        replay = evaluate_macro_replay(macros, eval_sequences, trigger_prefix_len=trigger_prefix_len)
        replay_by_id = {item["macro_id"]: item for item in replay["macros"]}
        promoted = []
        for macro in macros:
            if len(macro["sequence"]) < min_length:
                continue
            replay_row = replay_by_id.get(macro["macro_id"])
            if not replay_row or replay_row["exact_replays"] <= 0:
                continue
            if float(replay_row["replay_precision"]) < min_replay_precision:
                continue
            interface = macro_interface(macro)
            entry = {
                **macro,
                **interface,
                "group_key": group_key,
                "task_name": group_key,
                "canonicalization_mode": canonicalization_mode,
                "trigger_prefix_len": trigger_prefix_len,
                "exact_replays": replay_row["exact_replays"],
                "replay_precision": replay_row["replay_precision"],
                "suggested_name": f"{group_key}_m{len(promoted) + 1:03d}",
                "suggested_description": f"Reusable MiniWoB macro for {group_key}.",
                "has_binding": macro_has_binding(macro),
            }
            promoted.append(entry)
            registry.append(entry)

        groups.append(
            {
                "group_key": group_key,
                "episodes": len(sequences),
                "train_episodes": len(train_sequences),
                "eval_episodes": len(eval_sequences),
                "num_macros": len(macros),
                "num_promoted_macros": len(promoted),
                "replay": replay["summary"],
                "promoted_macros": promoted,
            }
        )

    summary = {
        "groups_reported": len(groups),
        "promoted_macros": len(registry),
        "parameterized_promoted_macros": sum(1 for entry in registry if entry["num_inputs"] > 0),
    }
    return {
        "summary": summary,
        "group_by": group_by,
        "canonicalization_mode": canonicalization_mode,
        "registry": registry,
        "groups": groups,
    }


def evaluate_live_replay_benchmark(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    decision_latency_ms: int = 1000,
) -> dict:
    grouped_rows = group_rows(rows, group_by)
    episode_meta = {episode["episode_id"]: episode for episode in episodes}
    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)

    groups = []
    total_primitive_steps = 0
    total_macro_steps = 0
    total_browser_time_ms = 0.0
    total_successes = 0
    total_episodes = 0
    macro_hit_counter: Counter = Counter()

    for group_key, group in sorted(grouped_rows.items()):
        represented_rows = represent_rows(group, mode=canonicalization_mode)
        sequences = group_sequences(represented_rows)
        _, eval_sequences = split_sequences(sequences, train_ratio=train_ratio, seed=split_seed)
        if not eval_sequences:
            eval_sequences = sequences
        macros = registry_by_group.get(group_key, [])
        episode_reports = []

        for episode_id, sequence in sorted(eval_sequences.items()):
            compressed, macro_hits = compress_sequence(sequence, macros)
            meta = episode_meta[episode_id]
            primitive_steps = len(sequence)
            macro_steps = len(compressed)
            browser_time_ms = float(meta["browser_time_ms"])
            success = bool(meta["success"])
            total_primitive_steps += primitive_steps
            total_macro_steps += macro_steps
            total_browser_time_ms += browser_time_ms
            total_successes += int(success)
            total_episodes += 1
            macro_hit_counter.update(macro_hits)

            episode_reports.append(
                {
                    "episode_id": episode_id,
                    "success": success,
                    "primitive_steps": primitive_steps,
                    "macro_steps": macro_steps,
                    "steps_saved": primitive_steps - macro_steps,
                    "browser_time_ms": round(browser_time_ms, 3),
                    "primitive_total_time_ms": round(browser_time_ms + primitive_steps * decision_latency_ms, 3),
                    "macro_total_time_ms": round(browser_time_ms + macro_steps * decision_latency_ms, 3),
                    "macro_hits": dict(macro_hits),
                }
            )

        if not episode_reports:
            continue

        primitive_group_steps = sum(item["primitive_steps"] for item in episode_reports)
        macro_group_steps = sum(item["macro_steps"] for item in episode_reports)
        groups.append(
            {
                "group_key": group_key,
                "macros_available": len(macros),
                "episodes": episode_reports,
                "summary": {
                    "episodes": len(episode_reports),
                    "success_rate": round(
                        sum(1 for item in episode_reports if item["success"]) / len(episode_reports),
                        4,
                    ),
                    "primitive_steps": primitive_group_steps,
                    "macro_steps": macro_group_steps,
                    "steps_saved": primitive_group_steps - macro_group_steps,
                    "decision_reduction_ratio": round(
                        (primitive_group_steps - macro_group_steps) / primitive_group_steps,
                        4,
                    )
                    if primitive_group_steps
                    else 0.0,
                    "browser_time_ms": round(sum(item["browser_time_ms"] for item in episode_reports), 3),
                },
            }
        )

    primitive_total_time_ms = total_browser_time_ms + total_primitive_steps * decision_latency_ms
    macro_total_time_ms = total_browser_time_ms + total_macro_steps * decision_latency_ms
    return {
        "summary": {
            "episodes": total_episodes,
            "success_rate": round(total_successes / total_episodes, 4) if total_episodes else 0.0,
            "primitive_steps": total_primitive_steps,
            "macro_steps": total_macro_steps,
            "steps_saved": total_primitive_steps - total_macro_steps,
            "decision_reduction_ratio": round((total_primitive_steps - total_macro_steps) / total_primitive_steps, 4)
            if total_primitive_steps
            else 0.0,
            "browser_time_ms": round(total_browser_time_ms, 3),
            "primitive_total_time_ms": round(primitive_total_time_ms, 3),
            "macro_total_time_ms": round(macro_total_time_ms, 3),
            "estimated_time_saved_ms": round(primitive_total_time_ms - macro_total_time_ms, 3),
            "macro_hits": dict(macro_hit_counter),
        },
        "groups": groups,
    }


def save_collection(output_prefix: str, payload: dict) -> dict:
    prefix = Path(output_prefix)
    traces_path = str(prefix.with_name(prefix.name + "_traces.jsonl"))
    summary_path = str(prefix.with_name(prefix.name + "_trace_summary.json"))
    dump_jsonl(traces_path, payload["rows"])
    dump_json(
        summary_path,
        {
            "summary": {
                "episodes": len(payload["episodes"]),
                "rows": len(payload["rows"]),
                "success_rate": round(
                    sum(1 for episode in payload["episodes"] if episode["success"]) / len(payload["episodes"]),
                    4,
                )
                if payload["episodes"]
                else 0.0,
                "primitive_steps": sum(int(episode["primitive_steps"]) for episode in payload["episodes"]),
                "browser_time_ms": round(sum(float(episode["browser_time_ms"]) for episode in payload["episodes"]), 3),
            },
            "episodes": payload["episodes"],
        },
    )
    return {"traces_path": traces_path, "summary_path": summary_path}
