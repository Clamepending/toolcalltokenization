from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Callable, Dict, Iterable, List, Sequence, Tuple
import re
import random

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
from .llm_client import CachedOpenAIChooser


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


def copy_step(step: Step) -> Step:
    return dict(step)


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

TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "button",
    "click",
    "field",
    "for",
    "from",
    "in",
    "input",
    "into",
    "item",
    "of",
    "on",
    "or",
    "select",
    "submit",
    "task",
    "text",
    "the",
    "then",
    "to",
    "value",
}


def build_plan(task_name: str, goal: str, obs: dict) -> List[Step]:
    if task_name not in TASK_BUILDERS:
        raise ValueError(f"Unsupported MiniWoB benchmark task: {task_name!r}")
    return TASK_BUILDERS[task_name](goal, obs)


def token_field(token: str, field: str) -> str:
    prefix = f"{field}="
    for part in str(token).split("|"):
        if part.startswith(prefix):
            return part[len(prefix) :]
    return ""


def normalize_label(value: str) -> str:
    label = str(value or "").strip().lower()
    if not label or label == "<text>":
        return ""
    label = label.replace("_", " ")
    label = re.sub(r"\s+", " ", label)
    return label


def step_phrase_from_canonical(token: str) -> str:
    action = token.split("|", 1)[0]
    role = token_field(token, "role")
    label = normalize_label(token_field(token, "label"))
    if action == "FILL":
        target = label or (role if role and role != "input" else "field")
        return f"fill {target}"
    if action == "SELECT":
        if label:
            return f"choose {label}"
        if role in {"select", "combobox"}:
            return "choose requested value from list"
        return "choose requested value"
    if action == "CLICK":
        target = label or role or "element"
        return f"click {target}"
    return action.lower()


def semantic_macro_name(task_name: str, macro: dict, rank: int) -> str:
    phrases = [step_phrase_from_canonical(token) for token in macro.get("sequence", [])]
    normalized = "_then_".join(
        re.sub(r"[^a-z0-9]+", "_", phrase).strip("_")
        for phrase in phrases[:3]
        if phrase
    )
    base = normalized or task_name
    base = re.sub(r"_+", "_", base).strip("_")
    return f"{task_name}_{base}_m{rank:03d}"


def semantic_macro_description(task_name: str, macro: dict) -> str:
    phrases = [step_phrase_from_canonical(token) for token in macro.get("sequence", [])]
    steps_text = ", then ".join(phrases)
    if task_name == "login_user":
        return "Fill the username and password fields, then click login."
    if task_name == "enter_password":
        return "Enter the password twice, then submit the form."
    if task_name in {"enter_text", "enter_text_dynamic"}:
        return "Fill the text field, then submit."
    if task_name == "choose_list":
        return "Choose the requested value from the list, then click submit."
    if task_name == "use_autocomplete":
        return "Type a prefix, pick an autocomplete suggestion, then submit."
    if task_name == "form_sequence_2":
        return "Choose the requested option, fill the textbox, then submit."
    if task_name == "form_sequence_3":
        return "Choose a dropdown value, then click the requested button."
    if task_name == "click_button_sequence":
        return "Click the two requested buttons in order."
    return f"For {task_name.replace('_', ' ')}, {steps_text}."


def text_tokens(text: str) -> set[str]:
    tokens = {token for token in re.findall(r"[a-z0-9]+", str(text).lower()) if token not in TOKEN_STOPWORDS}
    return tokens


def observation_text(obs: dict) -> str:
    parts = [str(obs.get("goal", ""))]
    for node in obs.get("axtree_object", {}).get("nodes", []):
        role = (node.get("role", {}) or {}).get("value", "")
        name = (node.get("name", {}) or {}).get("value", "")
        if role:
            parts.append(str(role))
        if name:
            parts.append(str(name))
    return " ".join(parts)


def primitive_action_name(step: Step, index: int) -> str:
    kind = str(step.get("kind", "action"))
    label = normalize_label(str(step.get("target_label", "")))
    if kind == "fill":
        target = label or "field"
        return f"step_{index+1}_fill_{re.sub(r'[^a-z0-9]+', '_', target).strip('_') or 'field'}"
    if kind == "select":
        target = label or "dropdown"
        return f"step_{index+1}_select_{re.sub(r'[^a-z0-9]+', '_', target).strip('_') or 'dropdown'}"
    target = label or str(step.get("target_role", "")) or "element"
    return f"step_{index+1}_click_{re.sub(r'[^a-z0-9]+', '_', target).strip('_') or 'element'}"


def primitive_action_description(step: Step) -> str:
    kind = str(step.get("kind", "action"))
    label = normalize_label(str(step.get("target_label", "")))
    role = normalize_label(str(step.get("target_role", "")))
    if kind == "fill":
        target = label or role or "field"
        return f"Type the requested value into the {target}."
    if kind == "select":
        target = label or role or "dropdown"
        return f"Choose the requested value from the {target}."
    target = label or role or "element"
    return f"Click the {target}."


GENERIC_STEP_LABELS = {"", "<text>", "field", "input", "item", "choice", "dropdown", "list", "submit"}


def step_label_tokens(step: Step) -> set[str]:
    label = normalize_label(str(step.get("target_label", "")))
    if label in GENERIC_STEP_LABELS:
        return set()
    return {token for token in re.findall(r"[a-z0-9]+", label) if token}


def macro_start_compatible(primitive_step: Step, macro: dict) -> bool:
    templates = list(macro.get("step_templates", []))
    if not templates:
        return False
    start = templates[0]

    primitive_kind = normalize_label(str(primitive_step.get("kind", "")))
    macro_kind = normalize_label(str(start.get("kind", "")))
    if primitive_kind and macro_kind and primitive_kind != macro_kind:
        return False

    primitive_role = normalize_label(str(primitive_step.get("target_role", "")))
    macro_role = normalize_label(str(start.get("target_role", "")))
    if primitive_role and macro_role and primitive_role != macro_role:
        return False

    primitive_tokens = step_label_tokens(primitive_step)
    macro_tokens = step_label_tokens(start)
    if primitive_tokens and macro_tokens and not (primitive_tokens & macro_tokens):
        return False

    return True


def action_semantic_text(name: str, description: str, extra: str = "") -> str:
    return " ".join(part for part in [name.replace("_", " "), description, extra] if part)


def semantic_score(
    *,
    goal_tokens: set[str],
    obs_tokens: set[str],
    action_tokens: set[str],
    is_macro: bool,
    length: int,
) -> float:
    score = 3.0 * len(goal_tokens & action_tokens)
    score += 1.0 * len(obs_tokens & action_tokens)
    if is_macro:
        score += 0.35 * max(length - 1, 0)
    return score


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
    if step.get("enable_autocomplete"):
        row["enable_autocomplete"] = True
    return row


def plan_to_trace_rows(
    *,
    task_name: str,
    env_id: str,
    seed: int,
    goal: str,
    plan: Sequence[Step],
    url: str = "",
) -> List[dict]:
    rows = []
    for step_index, step in enumerate(plan):
        rows.append(
            step_to_trace_row(
                task_name=task_name,
                env_id=env_id,
                seed=seed,
                goal=goal,
                step_index=step_index,
                step=step,
                action=render_action(step),
                url=url,
                step_duration_ms=0.0,
            )
        )
    return rows


def represented_plan(
    *,
    task_name: str,
    env_id: str,
    seed: int,
    goal: str,
    plan: Sequence[Step],
    canonicalization_mode: str = "dataflow_coarse",
    url: str = "",
) -> List[dict]:
    rows = plan_to_trace_rows(
        task_name=task_name,
        env_id=env_id,
        seed=seed,
        goal=goal,
        plan=plan,
        url=url,
    )
    return represent_rows(rows, mode=canonicalization_mode)


def binding_values_from_plan_rows(rows: Sequence[dict]) -> Dict[str, str]:
    binding_values: Dict[str, str] = {}
    for row in rows:
        value = str(row.get("value", "")).strip()
        if not value:
            continue
        for binding_id in row.get("binding_uses", []):
            binding_values.setdefault(str(binding_id), value)
    return binding_values


def macro_sort_key(macro: dict) -> Tuple:
    return (
        -float(macro.get("replay_precision", 0.0)),
        -len(macro.get("sequence", [])),
        -int(macro.get("support", 0)),
        str(macro.get("suggested_name", macro.get("macro_id", ""))),
    )


def represented_rows_by_episode(rows: Sequence[dict], mode: str) -> Dict[str, List[dict]]:
    represented = represent_rows(rows, mode=mode)
    grouped: Dict[str, List[Tuple[int, dict]]] = defaultdict(list)
    for row in represented:
        episode_id = str(row.get("episode_id", "unknown"))
        step_index = int(row.get("step_index", 0))
        grouped[episode_id].append((step_index, row))
    return {
        episode_id: [row for _, row in sorted(items)]
        for episode_id, items in grouped.items()
    }


def step_template_from_row(row: dict) -> dict:
    template = {
        "kind": str(row.get("action_name", "")),
        "bid": str(row.get("selector", "")),
        "target_role": str(row.get("target_role", "")),
        "target_label": str(row.get("target_label", "")),
    }
    if row.get("enable_autocomplete"):
        template["enable_autocomplete"] = True
    uses = list(row.get("binding_uses", []))
    if uses:
        template["binding_id"] = str(uses[0])
    elif row.get("value"):
        template["value"] = str(row["value"])
    return template


def representative_templates_for_macro(
    represented_rows: Dict[str, List[dict]],
    macro: dict,
) -> List[dict]:
    sequence = list(macro.get("sequence", []))
    if not sequence:
        return []
    for episode_rows in represented_rows.values():
        actions = [str(row.get("canonical_action", "")) for row in episode_rows]
        for index in range(len(actions) - len(sequence) + 1):
            if actions[index : index + len(sequence)] == sequence:
                return [step_template_from_row(row) for row in episode_rows[index : index + len(sequence)]]
    return []


def bind_macro_steps(macro: dict, binding_values: Dict[str, str]) -> List[Step]:
    steps: List[Step] = []
    for template in macro.get("step_templates", []):
        step = copy_step(template)
        binding_id = str(step.pop("binding_id", "")).strip()
        if binding_id:
            if binding_id not in binding_values:
                raise KeyError(f"Missing binding value for {binding_id!r}")
            step["value"] = binding_values[binding_id]
        steps.append(step)
    return steps


def split_eval_episode_ids(
    rows: Sequence[dict],
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
) -> Dict[str, List[str]]:
    grouped_rows = group_rows(rows, group_by)
    eval_ids: Dict[str, List[str]] = {}
    for group_key, group in grouped_rows.items():
        represented_rows = represent_rows(group, mode=canonicalization_mode)
        sequences = group_sequences(represented_rows)
        _, eval_sequences = split_sequences(sequences, train_ratio=train_ratio, seed=split_seed)
        if not eval_sequences:
            eval_sequences = sequences
        eval_ids[group_key] = sorted(eval_sequences)
    return eval_ids


def macro_action_string(macro: dict, binding_values: Dict[str, str]) -> str:
    return "\n".join(render_action(step) for step in bind_macro_steps(macro, binding_values))


def macro_runtime_id(macro: dict) -> str:
    name = str(macro.get("suggested_name", "")).strip()
    if name:
        return name
    group_key = str(macro.get("group_key", "<all>")).strip()
    macro_id = str(macro.get("macro_id", "macro")).strip() or "macro"
    return f"{group_key}::{macro_id}"


def choose_macro(
    remaining_sequence: Sequence[str],
    macros: Sequence[dict],
    *,
    policy_mode: str,
    min_replay_precision: float,
    blocked_macro_ids: Sequence[str] = (),
) -> dict | None:
    blocked_ids = {str(macro_id) for macro_id in blocked_macro_ids}
    candidates = []
    for macro in macros:
        if macro_runtime_id(macro) in blocked_ids:
            continue
        if float(macro.get("replay_precision", 0.0)) < min_replay_precision:
            continue
        sequence = list(macro.get("sequence", []))
        if not sequence:
            continue
        if policy_mode == "oracle_exact":
            if list(remaining_sequence[: len(sequence)]) != sequence:
                continue
        elif policy_mode == "trigger_prefix":
            prefix_len = min(int(macro.get("trigger_prefix_len", 1)), len(sequence))
            if list(remaining_sequence[:prefix_len]) != sequence[:prefix_len]:
                continue
        else:
            raise ValueError(f"Unsupported policy_mode: {policy_mode!r}")
        candidates.append(macro)
    if not candidates:
        return None
    candidates.sort(key=macro_sort_key)
    return candidates[0]


def collect_miniwob_traces(
    *,
    tasks: Sequence[str] = MINIWOB_TASKS,
    episodes_per_task: int = 20,
    seed_start: int = 0,
    headless: bool = True,
    miniwob_url: str | None = None,
    launch_retries: int = 2,
) -> dict:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401
    import time

    rows: List[dict] = []
    episodes: List[dict] = []

    if miniwob_url:
        import os

        os.environ["MINIWOB_URL"] = miniwob_url

    for env_id in tasks:
        task_name = task_name_for_env_id(env_id)
        for seed in range(seed_start, seed_start + episodes_per_task):
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(env_id, headless=headless)
                    obs, _ = env.reset(seed=seed)
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - exercised in live benchmark only
                    last_error = exc
                    if env is not None:
                        try:
                            env.close()
                        except Exception:
                            pass
                        env = None
                    if attempt >= launch_retries:
                        raise
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            if last_error is not None:
                raise last_error
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
        train_episode_ids = set(train_sequences)
        represented_train_rows = {
            episode_id: rows
            for episode_id, rows in represented_rows_by_episode(group, canonicalization_mode).items()
            if episode_id in train_episode_ids
        }
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
                "suggested_name": semantic_macro_name(str(group_key), macro, len(promoted) + 1),
                "suggested_description": semantic_macro_description(str(group_key), macro),
                "has_binding": macro_has_binding(macro),
                "step_templates": representative_templates_for_macro(represented_train_rows, macro),
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


def evaluate_live_macro_policy_benchmark(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    decision_latency_ms: int = 1000,
    headless: bool = True,
    miniwob_url: str | None = None,
    policy_mode: str = "oracle_exact",
    min_replay_precision: float = 0.5,
    launch_retries: int = 2,
    action_scope: str = "task",
) -> dict:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401
    import os
    import time

    if miniwob_url:
        os.environ["MINIWOB_URL"] = miniwob_url

    eval_ids_by_group = split_eval_episode_ids(
        rows,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        train_ratio=train_ratio,
        split_seed=split_seed,
    )
    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)

    episode_meta = {episode["episode_id"]: episode for episode in episodes}
    total_primitive_steps = 0
    total_agent_decisions = 0
    total_browser_time_ms = 0.0
    total_successes = 0
    total_episodes = 0
    total_attempted_macro_calls = 0
    total_successful_macro_calls = 0
    total_failed_macro_calls = 0
    macro_hits: Counter = Counter()
    groups = []

    for group_key, eval_ids in sorted(eval_ids_by_group.items()):
        if action_scope == "task":
            macros = sorted(registry_by_group.get(group_key, []), key=macro_sort_key)
        elif action_scope == "global":
            macros = all_macros
        else:
            raise ValueError(f"Unsupported action_scope: {action_scope!r}")
        group_reports = []
        for episode_id in eval_ids:
            meta = episode_meta[episode_id]
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(str(meta["env_id"]), headless=headless)
                    obs, _ = env.reset(seed=int(meta["seed"]))
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - exercised in live benchmark only
                    last_error = exc
                    if env is not None:
                        try:
                            env.close()
                        except Exception:
                            pass
                        env = None
                    if attempt >= launch_retries:
                        raise
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            if last_error is not None:
                raise last_error

            goal = str(obs.get("goal", ""))
            task_name = str(meta["task_name"])
            plan = build_plan(task_name, goal, obs)
            represented = represented_plan(
                task_name=task_name,
                env_id=str(meta["env_id"]),
                seed=int(meta["seed"]),
                goal=goal,
                plan=plan,
                canonicalization_mode=canonicalization_mode,
                url=str(obs.get("url", "")),
            )
            sequence = [row["canonical_action"] for row in represented]
            binding_values = binding_values_from_plan_rows(represented)

            index = 0
            agent_decisions = 0
            browser_time_ms = 0.0
            attempted_macro_calls = 0
            successful_macro_calls = 0
            failed_macro_calls = 0
            episode_macro_hits: Counter = Counter()
            blocked_macros_by_index: Dict[int, set[str]] = defaultdict(set)
            attempted_macro_ids: List[str] = []
            successful_macro_ids: List[str] = []
            failed_macro_ids: List[str] = []
            success = False
            final_error = ""

            while index < len(plan):
                macro = choose_macro(
                    sequence[index:],
                    macros,
                    policy_mode=policy_mode,
                    min_replay_precision=min_replay_precision,
                    blocked_macro_ids=blocked_macros_by_index[index],
                )
                if macro and macro.get("step_templates"):
                    span = len(macro.get("sequence", []))
                    macro_sequence = list(macro.get("sequence", []))
                    macro_id = str(macro.get("macro_id", macro.get("suggested_name", "macro")))
                    attempted_macro_calls += 1
                    attempted_macro_ids.append(macro_id)
                    agent_decisions += 1
                    macro_failed = False
                    current_sequence = list(sequence[index : index + span])
                    if current_sequence != macro_sequence:
                        failed_macro_calls += 1
                        failed_macro_ids.append(macro_id)
                        blocked_macros_by_index[index].add(macro_id)
                        macro_failed = True
                        bound_steps = []
                    else:
                        bound_steps = [copy_step(step) for step in plan[index : index + span]]
                    executed_steps = 0

                    if not macro_failed:
                        for step in bound_steps:
                            action = render_action(step)
                            start = perf_counter()
                            obs, reward, terminated, truncated, info = env.step(action)
                            browser_time_ms += (perf_counter() - start) * 1000.0
                            final_error = str(obs.get("last_action_error", ""))
                            if final_error:
                                failed_macro_calls += 1
                                failed_macro_ids.append(macro_id)
                                blocked_macros_by_index[index + executed_steps].add(macro_id)
                                macro_failed = True
                                break
                            executed_steps += 1
                            if terminated or truncated:
                                task_info = info.get("task_info", {})
                                success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                                break

                    if macro_failed:
                        index += executed_steps
                        continue

                    successful_macro_calls += 1
                    successful_macro_ids.append(macro_id)
                    episode_macro_hits[macro_id] += 1
                    index += span
                    if terminated or truncated:
                        break
                    continue

                action = render_action(plan[index])
                agent_decisions += 1
                start = perf_counter()
                obs, reward, terminated, truncated, info = env.step(action)
                browser_time_ms += (perf_counter() - start) * 1000.0
                final_error = str(obs.get("last_action_error", ""))
                index += 1
                if terminated or truncated:
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                    break

            env.close()

            primitive_steps = int(meta["primitive_steps"])
            total_primitive_steps += primitive_steps
            total_agent_decisions += agent_decisions
            total_browser_time_ms += browser_time_ms
            total_successes += int(success)
            total_episodes += 1
            total_attempted_macro_calls += attempted_macro_calls
            total_successful_macro_calls += successful_macro_calls
            total_failed_macro_calls += failed_macro_calls
            macro_hits.update(episode_macro_hits)

            group_reports.append(
                {
                    "episode_id": episode_id,
                    "success": success,
                    "primitive_steps": primitive_steps,
                    "agent_decisions": agent_decisions,
                    "steps_saved": primitive_steps - agent_decisions,
                    "attempted_macro_calls": attempted_macro_calls,
                    "successful_macro_calls": successful_macro_calls,
                    "failed_macro_calls": failed_macro_calls,
                    "attempted_macro_ids": attempted_macro_ids,
                    "successful_macro_ids": successful_macro_ids,
                    "failed_macro_ids": failed_macro_ids,
                    "browser_time_ms": round(browser_time_ms, 3),
                    "primitive_total_time_ms": round(float(meta["browser_time_ms"]) + primitive_steps * decision_latency_ms, 3),
                    "macro_total_time_ms": round(browser_time_ms + agent_decisions * decision_latency_ms, 3),
                    "macro_hits": dict(episode_macro_hits),
                    "last_action_error": final_error,
                }
            )

        if not group_reports:
            continue

        primitive_group_steps = sum(item["primitive_steps"] for item in group_reports)
        agent_group_steps = sum(item["agent_decisions"] for item in group_reports)
        groups.append(
            {
                "group_key": group_key,
                "macros_available": len(macros),
                "episodes": group_reports,
                "summary": {
                    "episodes": len(group_reports),
                    "success_rate": round(sum(1 for item in group_reports if item["success"]) / len(group_reports), 4),
                    "primitive_steps": primitive_group_steps,
                    "agent_decisions": agent_group_steps,
                    "steps_saved": primitive_group_steps - agent_group_steps,
                    "decision_reduction_ratio": round((primitive_group_steps - agent_group_steps) / primitive_group_steps, 4)
                    if primitive_group_steps
                    else 0.0,
                    "attempted_macro_calls": sum(item["attempted_macro_calls"] for item in group_reports),
                    "successful_macro_calls": sum(item["successful_macro_calls"] for item in group_reports),
                    "failed_macro_calls": sum(item["failed_macro_calls"] for item in group_reports),
                    "browser_time_ms": round(sum(item["browser_time_ms"] for item in group_reports), 3),
                },
            }
        )

    primitive_total_time_ms = sum(float(episode_meta[episode["episode_id"]]["browser_time_ms"]) + episode["primitive_steps"] * decision_latency_ms for group in groups for episode in group["episodes"])
    macro_total_time_ms = sum(float(episode["macro_total_time_ms"]) for group in groups for episode in group["episodes"])
    return {
        "summary": {
            "policy_mode": policy_mode,
            "action_scope": action_scope,
            "episodes": total_episodes,
            "success_rate": round(total_successes / total_episodes, 4) if total_episodes else 0.0,
            "primitive_steps": total_primitive_steps,
            "agent_decisions": total_agent_decisions,
            "steps_saved": total_primitive_steps - total_agent_decisions,
            "decision_reduction_ratio": round((total_primitive_steps - total_agent_decisions) / total_primitive_steps, 4)
            if total_primitive_steps
            else 0.0,
            "attempted_macro_calls": total_attempted_macro_calls,
            "successful_macro_calls": total_successful_macro_calls,
            "failed_macro_calls": total_failed_macro_calls,
            "macro_success_rate": round(total_successful_macro_calls / total_attempted_macro_calls, 4)
            if total_attempted_macro_calls
            else 0.0,
            "browser_time_ms": round(total_browser_time_ms, 3),
            "primitive_total_time_ms": round(primitive_total_time_ms, 3),
            "macro_total_time_ms": round(macro_total_time_ms, 3),
            "estimated_time_saved_ms": round(primitive_total_time_ms - macro_total_time_ms, 3),
            "macro_hits": dict(macro_hits),
        },
        "groups": groups,
    }


def semantic_choice(
    *,
    goal: str,
    obs: dict,
    primitive_step: Step,
    primitive_index: int,
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    margin: float = 0.0,
    use_start_step_guard: bool = True,
) -> dict:
    goal_tokens = text_tokens(goal)
    obs_tokens = text_tokens(observation_text(obs))

    primitive_name = primitive_action_name(primitive_step, primitive_index)
    primitive_description = primitive_action_description(primitive_step)
    primitive_text = action_semantic_text(
        primitive_name,
        primitive_description,
        f"{primitive_step.get('target_role', '')} {primitive_step.get('target_label', '')}",
    )
    primitive_score = semantic_score(
        goal_tokens=goal_tokens,
        obs_tokens=obs_tokens,
        action_tokens=text_tokens(primitive_text),
        is_macro=False,
        length=1,
    )

    best_macro = None
    best_macro_score = float("-inf")
    blocked = {str(macro_id) for macro_id in blocked_macro_ids}
    for macro in macros:
        macro_id = macro_runtime_id(macro)
        if macro_id in blocked:
            continue
        if use_start_step_guard and not macro_start_compatible(primitive_step, macro):
            continue
        action_text = action_semantic_text(
            str(macro.get("suggested_name", "")),
            str(macro.get("suggested_description", "")),
            " ".join(str(step) for step in macro.get("sequence", [])),
        )
        score = semantic_score(
            goal_tokens=goal_tokens,
            obs_tokens=obs_tokens,
            action_tokens=text_tokens(action_text),
            is_macro=True,
            length=len(macro.get("sequence", [])),
        )
        if score > best_macro_score:
            best_macro = macro
            best_macro_score = score

    if best_macro is None or best_macro_score < primitive_score + margin:
        return {
            "kind": "primitive",
            "score": primitive_score,
            "primitive_name": primitive_name,
            "primitive_description": primitive_description,
        }
    return {
        "kind": "macro",
        "score": best_macro_score,
        "macro": best_macro,
        "macro_id": macro_runtime_id(best_macro),
        "primitive_score": primitive_score,
        "primitive_name": primitive_name,
        "primitive_description": primitive_description,
    }


def candidate_set(
    *,
    primitive_step: Step,
    primitive_index: int,
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    use_start_step_guard: bool,
) -> List[dict]:
    primitive_name = primitive_action_name(primitive_step, primitive_index)
    primitive_description = primitive_action_description(primitive_step)
    candidates = [
        {
            "kind": "primitive",
            "id": "__primitive__",
            "name": primitive_name,
            "description": primitive_description,
            "length": 1,
            "tokens": text_tokens(
                action_semantic_text(
                    primitive_name,
                    primitive_description,
                    f"{primitive_step.get('target_role', '')} {primitive_step.get('target_label', '')}",
                )
            ),
            "primitive_name": primitive_name,
            "primitive_description": primitive_description,
        }
    ]

    blocked = {str(macro_id) for macro_id in blocked_macro_ids}
    for macro in macros:
        macro_id = macro_runtime_id(macro)
        if macro_id in blocked:
            continue
        if use_start_step_guard and not macro_start_compatible(primitive_step, macro):
            continue
        action_text = action_semantic_text(
            str(macro.get("suggested_name", "")),
            str(macro.get("suggested_description", "")),
            " ".join(str(step) for step in macro.get("sequence", [])),
        )
        candidates.append(
            {
                "kind": "macro",
                "id": macro_id,
                "name": str(macro.get("suggested_name", "")),
                "description": str(macro.get("suggested_description", "")),
                "length": len(macro.get("sequence", [])),
                "tokens": text_tokens(action_text),
                "macro": macro,
            }
        )
    return candidates


def candidate_features(
    *,
    goal_tokens: set[str],
    obs_tokens: set[str],
    primitive_step: Step,
    candidate: dict,
) -> Dict[str, float]:
    features: Dict[str, float] = {
        "bias": 1.0,
        f"kind:{candidate['kind']}": 1.0,
        f"length:{candidate['length']}": 1.0,
    }
    action_tokens = set(candidate.get("tokens", set()))
    for token in sorted(goal_tokens & action_tokens):
        features[f"goal_overlap:{token}"] = 1.0
    for token in sorted(obs_tokens & action_tokens):
        features[f"obs_overlap:{token}"] = 1.0
    for token in sorted(action_tokens):
        features[f"action_token:{token}"] = features.get(f"action_token:{token}", 0.0) + 0.15

    if candidate["kind"] == "primitive":
        kind = normalize_label(str(primitive_step.get("kind", ""))) or "action"
        label = normalize_label(str(primitive_step.get("target_label", ""))) or normalize_label(str(primitive_step.get("target_role", ""))) or "element"
        features["primitive_bias"] = 1.0
        features[f"primitive_kind:{kind}"] = 1.0
        features[f"primitive_label:{label}"] = 1.0
        return features

    macro = dict(candidate["macro"])
    features["macro_bias"] = 1.0
    features["macro_length"] = float(candidate["length"])
    features[f"macro_name:{candidate['name']}"] = 1.0
    templates = list(macro.get("step_templates", []))
    if not templates:
        return features
    start = templates[0]
    primitive_kind = normalize_label(str(primitive_step.get("kind", "")))
    start_kind = normalize_label(str(start.get("kind", "")))
    if primitive_kind and start_kind and primitive_kind == start_kind:
        features["start_kind_match"] = 1.0
    primitive_role = normalize_label(str(primitive_step.get("target_role", "")))
    start_role = normalize_label(str(start.get("target_role", "")))
    if primitive_role and start_role and primitive_role == start_role:
        features[f"start_role_match:{start_role}"] = 1.0
    for token in sorted(step_label_tokens(primitive_step) & step_label_tokens(start)):
        features[f"start_label_match:{token}"] = 1.0
    return features


def score_linear(weights: Dict[str, float], features: Dict[str, float]) -> float:
    return sum(weights.get(key, 0.0) * value for key, value in features.items())


def update_averaged_weights(
    *,
    weights: Dict[str, float],
    totals: Dict[str, float],
    stamps: Dict[str, int],
    step: int,
    features: Dict[str, float],
    scale: float,
) -> None:
    for key, value in features.items():
        current = weights.get(key, 0.0)
        totals[key] = totals.get(key, 0.0) + (step - stamps.get(key, 0)) * current
        stamps[key] = step
        weights[key] = current + scale * value


def finalize_averaged_weights(
    weights: Dict[str, float],
    totals: Dict[str, float],
    stamps: Dict[str, int],
    step: int,
) -> Dict[str, float]:
    averaged: Dict[str, float] = {}
    if step <= 0:
        return dict(weights)
    for key, value in weights.items():
        total = totals.get(key, 0.0) + (step - stamps.get(key, 0)) * value
        averaged_value = total / step
        if averaged_value:
            averaged[key] = averaged_value
    return averaged


def split_train_eval_episode_ids(
    rows: Sequence[dict],
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    grouped_rows = group_rows(rows, group_by)
    train_ids: Dict[str, List[str]] = {}
    eval_ids: Dict[str, List[str]] = {}
    for group_key, group in grouped_rows.items():
        represented_rows = represent_rows(group, mode=canonicalization_mode)
        sequences = group_sequences(represented_rows)
        train_sequences, eval_sequences = split_sequences(sequences, train_ratio=train_ratio, seed=split_seed)
        if not eval_sequences:
            eval_sequences = sequences
        if not train_sequences:
            train_sequences = sequences
        train_ids[group_key] = sorted(train_sequences)
        eval_ids[group_key] = sorted(eval_sequences)
    return train_ids, eval_ids


def action_space_macros(
    *,
    group_key: str,
    registry_by_group: Dict[str, List[dict]],
    all_macros: Sequence[dict],
    action_scope: str,
) -> List[dict]:
    if action_scope == "task":
        return sorted(registry_by_group.get(group_key, []), key=macro_sort_key)
    if action_scope == "global":
        return list(all_macros)
    raise ValueError(f"Unsupported action_scope: {action_scope!r}")


def oracle_choice_id(
    *,
    remaining_sequence: Sequence[str],
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
) -> str:
    macro = choose_macro(
        remaining_sequence,
        macros,
        policy_mode="oracle_exact",
        min_replay_precision=0.0,
        blocked_macro_ids=blocked_macro_ids,
    )
    if macro is None:
        return "__primitive__"
    return macro_runtime_id(macro)


def collect_learned_policy_examples(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    episode_ids_by_group: Dict[str, List[str]],
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    action_scope: str = "task",
    headless: bool = True,
    miniwob_url: str | None = None,
    launch_retries: int = 2,
    use_start_step_guard: bool = True,
) -> List[dict]:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401
    import os
    import time

    if miniwob_url:
        os.environ["MINIWOB_URL"] = miniwob_url

    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)
    episode_meta = {str(episode["episode_id"]): episode for episode in episodes}
    examples: List[dict] = []

    for group_key, episode_ids in sorted(episode_ids_by_group.items()):
        macros = action_space_macros(group_key=group_key, registry_by_group=registry_by_group, all_macros=all_macros, action_scope=action_scope)
        for episode_id in episode_ids:
            meta = episode_meta[str(episode_id)]
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(str(meta["env_id"]), headless=headless)
                    obs, _ = env.reset(seed=int(meta["seed"]))
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - live-only path
                    last_error = exc
                    if env is not None:
                        try:
                            env.close()
                        except Exception:
                            pass
                        env = None
                    if attempt >= launch_retries:
                        raise
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            if last_error is not None:
                raise last_error

            goal = str(obs.get("goal", ""))
            task_name = str(meta["task_name"])
            plan = build_plan(task_name, goal, obs)
            represented = represented_plan(
                task_name=task_name,
                env_id=str(meta["env_id"]),
                seed=int(meta["seed"]),
                goal=goal,
                plan=plan,
                canonicalization_mode=canonicalization_mode,
                url=str(obs.get("url", "")),
            )
            sequence = [row["canonical_action"] for row in represented]

            for index, step in enumerate(plan):
                candidates = candidate_set(
                    primitive_step=step,
                    primitive_index=index,
                    macros=macros,
                    blocked_macro_ids=[],
                    use_start_step_guard=use_start_step_guard,
                )
                candidate_ids = {candidate["id"] for candidate in candidates}
                gold_id = oracle_choice_id(
                    remaining_sequence=sequence[index:],
                    macros=[candidate["macro"] for candidate in candidates if candidate["kind"] == "macro"],
                    blocked_macro_ids=[],
                )
                if gold_id not in candidate_ids:
                    gold_id = "__primitive__"
                examples.append(
                    {
                        "episode_id": str(episode_id),
                        "group_key": str(group_key),
                        "goal": goal,
                        "obs_text": observation_text(obs),
                        "primitive_step": dict(step),
                        "primitive_index": index,
                        "candidates": candidates,
                        "gold_id": gold_id,
                    }
                )
                obs, reward, terminated, truncated, info = env.step(render_action(step))
                if terminated or truncated:
                    break

            env.close()

    return examples


def train_learned_selector(
    examples: Sequence[dict],
    *,
    epochs: int = 8,
    seed: int = 0,
) -> dict:
    weights: Dict[str, float] = {}
    totals: Dict[str, float] = {}
    stamps: Dict[str, int] = {}
    updates = 0
    step_count = 0
    rng = random.Random(seed)
    ordered = list(examples)

    for _ in range(epochs):
        rng.shuffle(ordered)
        for example in ordered:
            goal_tokens = text_tokens(str(example["goal"]))
            obs_tokens = text_tokens(str(example["obs_text"]))
            feature_map = {
                candidate["id"]: candidate_features(
                    goal_tokens=goal_tokens,
                    obs_tokens=obs_tokens,
                    primitive_step=dict(example["primitive_step"]),
                    candidate=candidate,
                )
                for candidate in example["candidates"]
            }
            scored = sorted(
                ((score_linear(weights, features), candidate_id) for candidate_id, features in feature_map.items()),
                key=lambda item: (item[0], item[1] != "__primitive__", item[1]),
                reverse=True,
            )
            predicted_id = scored[0][1] if scored else "__primitive__"
            gold_id = str(example["gold_id"])
            step_count += 1
            if predicted_id == gold_id:
                continue
            updates += 1
            update_averaged_weights(
                weights=weights,
                totals=totals,
                stamps=stamps,
                step=step_count,
                features=feature_map[gold_id],
                scale=1.0,
            )
            update_averaged_weights(
                weights=weights,
                totals=totals,
                stamps=stamps,
                step=step_count,
                features=feature_map[predicted_id],
                scale=-1.0,
            )

    averaged = finalize_averaged_weights(weights, totals, stamps, max(step_count, 1))
    return {
        "model_type": "averaged_perceptron",
        "epochs": epochs,
        "seed": seed,
        "examples": len(examples),
        "updates": updates,
        "weights": averaged,
    }


def learned_choice(
    *,
    model: dict,
    goal: str,
    obs: dict,
    primitive_step: Step,
    primitive_index: int,
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    use_start_step_guard: bool = True,
) -> dict:
    candidates = candidate_set(
        primitive_step=primitive_step,
        primitive_index=primitive_index,
        macros=macros,
        blocked_macro_ids=blocked_macro_ids,
        use_start_step_guard=use_start_step_guard,
    )
    weights = dict(model.get("weights", {}))
    goal_tokens = text_tokens(goal)
    obs_tokens = text_tokens(observation_text(obs))
    scored: List[Tuple[float, dict]] = []
    for candidate in candidates:
        features = candidate_features(
            goal_tokens=goal_tokens,
            obs_tokens=obs_tokens,
            primitive_step=primitive_step,
            candidate=candidate,
        )
        score = score_linear(weights, features)
        scored.append((score, candidate))
    scored.sort(key=lambda item: (item[0], item[1]["kind"] == "macro", item[1]["id"]), reverse=True)
    best_score, best = scored[0]
    if best["kind"] == "primitive":
        return {
            "kind": "primitive",
            "score": best_score,
            "primitive_name": best["primitive_name"],
            "primitive_description": best["primitive_description"],
        }
    return {
        "kind": "macro",
        "score": best_score,
        "macro": best["macro"],
        "macro_id": best["id"],
        "primitive_name": candidates[0]["primitive_name"],
        "primitive_description": candidates[0]["primitive_description"],
    }


def llm_choice(
    *,
    chooser: CachedOpenAIChooser,
    goal: str,
    obs: dict,
    primitive_step: Step,
    primitive_index: int,
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    use_start_step_guard: bool = True,
) -> dict:
    candidates = candidate_set(
        primitive_step=primitive_step,
        primitive_index=primitive_index,
        macros=macros,
        blocked_macro_ids=blocked_macro_ids,
        use_start_step_guard=use_start_step_guard,
    )
    result = chooser.choose(
        goal=goal,
        context_text=observation_text(obs),
        candidates=candidates,
    )
    chosen_id = str(result.get("id", "__primitive__"))
    chosen = next((candidate for candidate in candidates if candidate["id"] == chosen_id), candidates[0])
    if chosen["kind"] == "primitive":
        return {
            "kind": "primitive",
            "primitive_name": chosen["primitive_name"],
            "primitive_description": chosen["primitive_description"],
            "score": 0.0,
            "llm_reason": str(result.get("reason", "")),
            "llm_cached": bool(result.get("cached", False)),
            "llm_usage": dict(result.get("usage", {})),
            "llm_raw_content": str(result.get("raw_content", "")),
        }
    return {
        "kind": "macro",
        "macro": chosen["macro"],
        "macro_id": chosen["id"],
        "score": 0.0,
        "primitive_name": candidates[0]["primitive_name"],
        "primitive_description": candidates[0]["primitive_description"],
        "llm_reason": str(result.get("reason", "")),
        "llm_cached": bool(result.get("cached", False)),
        "llm_usage": dict(result.get("usage", {})),
        "llm_raw_content": str(result.get("raw_content", "")),
    }


def evaluate_live_semantic_policy_benchmark(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    decision_latency_ms: int = 1000,
    headless: bool = True,
    miniwob_url: str | None = None,
    action_scope: str = "task",
    margin: float = 0.0,
    launch_retries: int = 2,
    use_start_step_guard: bool = True,
) -> dict:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401
    import os
    import time

    if miniwob_url:
        os.environ["MINIWOB_URL"] = miniwob_url

    eval_ids_by_group = split_eval_episode_ids(
        rows,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        train_ratio=train_ratio,
        split_seed=split_seed,
    )
    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)

    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)
    episode_meta = {episode["episode_id"]: episode for episode in episodes}
    total_primitive_steps = 0
    total_agent_decisions = 0
    total_browser_time_ms = 0.0
    total_successes = 0
    total_episodes = 0
    total_attempted_macro_calls = 0
    total_successful_macro_calls = 0
    total_failed_macro_calls = 0
    macro_hits: Counter = Counter()
    groups = []

    for group_key, eval_ids in sorted(eval_ids_by_group.items()):
        if action_scope == "task":
            macros = sorted(registry_by_group.get(group_key, []), key=macro_sort_key)
        elif action_scope == "global":
            macros = all_macros
        else:
            raise ValueError(f"Unsupported action_scope: {action_scope!r}")

        group_reports = []
        for episode_id in eval_ids:
            meta = episode_meta[episode_id]
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(str(meta["env_id"]), headless=headless)
                    obs, _ = env.reset(seed=int(meta["seed"]))
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - exercised in live benchmark only
                    last_error = exc
                    if env is not None:
                        try:
                            env.close()
                        except Exception:
                            pass
                        env = None
                    if attempt >= launch_retries:
                        raise
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            if last_error is not None:
                raise last_error

            goal = str(obs.get("goal", ""))
            task_name = str(meta["task_name"])
            plan = build_plan(task_name, goal, obs)
            represented = represented_plan(
                task_name=task_name,
                env_id=str(meta["env_id"]),
                seed=int(meta["seed"]),
                goal=goal,
                plan=plan,
                canonicalization_mode=canonicalization_mode,
                url=str(obs.get("url", "")),
            )
            sequence = [row["canonical_action"] for row in represented]

            index = 0
            agent_decisions = 0
            browser_time_ms = 0.0
            attempted_macro_calls = 0
            successful_macro_calls = 0
            failed_macro_calls = 0
            episode_macro_hits: Counter = Counter()
            blocked_macros_by_index: Dict[int, set[str]] = defaultdict(set)
            attempted_macro_ids: List[str] = []
            successful_macro_ids: List[str] = []
            failed_macro_ids: List[str] = []
            choice_trace: List[dict] = []
            success = False
            final_error = ""

            while index < len(plan):
                choice = semantic_choice(
                    goal=goal,
                    obs=obs,
                    primitive_step=plan[index],
                    primitive_index=index,
                    macros=macros,
                    blocked_macro_ids=blocked_macros_by_index[index],
                    margin=margin,
                    use_start_step_guard=use_start_step_guard,
                )
                if choice["kind"] == "macro":
                    macro = choice["macro"]
                    span = len(macro.get("sequence", []))
                    macro_sequence = list(macro.get("sequence", []))
                    macro_id = str(macro.get("macro_id", macro.get("suggested_name", "macro")))
                    attempted_macro_calls += 1
                    attempted_macro_ids.append(macro_id)
                    agent_decisions += 1
                    choice_trace.append(
                        {
                            "index": index,
                            "choice": "macro",
                            "macro_id": macro_id,
                            "macro_name": macro.get("suggested_name"),
                            "macro_score": round(float(choice["score"]), 3),
                            "primitive_score": round(float(choice.get("primitive_score", 0.0)), 3),
                        }
                    )
                    current_sequence = list(sequence[index : index + span])
                    if current_sequence != macro_sequence:
                        failed_macro_calls += 1
                        failed_macro_ids.append(macro_id)
                        blocked_macros_by_index[index].add(macro_id)
                        continue

                    macro_failed = False
                    executed_steps = 0
                    for step in plan[index : index + span]:
                        action = render_action(step)
                        start = perf_counter()
                        obs, reward, terminated, truncated, info = env.step(action)
                        browser_time_ms += (perf_counter() - start) * 1000.0
                        final_error = str(obs.get("last_action_error", ""))
                        if final_error:
                            failed_macro_calls += 1
                            failed_macro_ids.append(macro_id)
                            blocked_macros_by_index[index + executed_steps].add(macro_id)
                            macro_failed = True
                            break
                        executed_steps += 1
                        if terminated or truncated:
                            task_info = info.get("task_info", {})
                            success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                            break

                    if macro_failed:
                        index += executed_steps
                        continue

                    successful_macro_calls += 1
                    successful_macro_ids.append(macro_id)
                    episode_macro_hits[macro_id] += 1
                    index += span
                    if terminated or truncated:
                        break
                    continue

                action = render_action(plan[index])
                agent_decisions += 1
                choice_trace.append(
                    {
                        "index": index,
                        "choice": "primitive",
                        "primitive_name": choice["primitive_name"],
                        "primitive_description": choice["primitive_description"],
                        "primitive_score": round(float(choice["score"]), 3),
                    }
                )
                start = perf_counter()
                obs, reward, terminated, truncated, info = env.step(action)
                browser_time_ms += (perf_counter() - start) * 1000.0
                final_error = str(obs.get("last_action_error", ""))
                index += 1
                if terminated or truncated:
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                    break

            env.close()

            primitive_steps = int(meta["primitive_steps"])
            total_primitive_steps += primitive_steps
            total_agent_decisions += agent_decisions
            total_browser_time_ms += browser_time_ms
            total_successes += int(success)
            total_episodes += 1
            total_attempted_macro_calls += attempted_macro_calls
            total_successful_macro_calls += successful_macro_calls
            total_failed_macro_calls += failed_macro_calls
            macro_hits.update(episode_macro_hits)

            group_reports.append(
                {
                    "episode_id": episode_id,
                    "success": success,
                    "primitive_steps": primitive_steps,
                    "agent_decisions": agent_decisions,
                    "steps_saved": primitive_steps - agent_decisions,
                    "attempted_macro_calls": attempted_macro_calls,
                    "successful_macro_calls": successful_macro_calls,
                    "failed_macro_calls": failed_macro_calls,
                    "attempted_macro_ids": attempted_macro_ids,
                    "successful_macro_ids": successful_macro_ids,
                    "failed_macro_ids": failed_macro_ids,
                    "browser_time_ms": round(browser_time_ms, 3),
                    "primitive_total_time_ms": round(float(meta["browser_time_ms"]) + primitive_steps * decision_latency_ms, 3),
                    "macro_total_time_ms": round(browser_time_ms + agent_decisions * decision_latency_ms, 3),
                    "macro_hits": dict(episode_macro_hits),
                    "choice_trace": choice_trace,
                    "last_action_error": final_error,
                }
            )

        if not group_reports:
            continue

        primitive_group_steps = sum(item["primitive_steps"] for item in group_reports)
        agent_group_steps = sum(item["agent_decisions"] for item in group_reports)
        groups.append(
            {
                "group_key": group_key,
                "macros_available": len(macros),
                "episodes": group_reports,
                "summary": {
                    "episodes": len(group_reports),
                    "success_rate": round(sum(1 for item in group_reports if item["success"]) / len(group_reports), 4),
                    "primitive_steps": primitive_group_steps,
                    "agent_decisions": agent_group_steps,
                    "steps_saved": primitive_group_steps - agent_group_steps,
                    "decision_reduction_ratio": round((primitive_group_steps - agent_group_steps) / primitive_group_steps, 4)
                    if primitive_group_steps
                    else 0.0,
                    "attempted_macro_calls": sum(item["attempted_macro_calls"] for item in group_reports),
                    "successful_macro_calls": sum(item["successful_macro_calls"] for item in group_reports),
                    "failed_macro_calls": sum(item["failed_macro_calls"] for item in group_reports),
                    "browser_time_ms": round(sum(item["browser_time_ms"] for item in group_reports), 3),
                },
            }
        )

    primitive_total_time_ms = sum(
        float(episode_meta[episode["episode_id"]]["browser_time_ms"]) + episode["primitive_steps"] * decision_latency_ms
        for group in groups
        for episode in group["episodes"]
    )
    macro_total_time_ms = sum(float(episode["macro_total_time_ms"]) for group in groups for episode in group["episodes"])
    return {
        "summary": {
            "policy_mode": "semantic",
            "action_scope": action_scope,
            "margin": margin,
            "use_start_step_guard": use_start_step_guard,
            "episodes": total_episodes,
            "success_rate": round(total_successes / total_episodes, 4) if total_episodes else 0.0,
            "primitive_steps": total_primitive_steps,
            "agent_decisions": total_agent_decisions,
            "steps_saved": total_primitive_steps - total_agent_decisions,
            "decision_reduction_ratio": round((total_primitive_steps - total_agent_decisions) / total_primitive_steps, 4)
            if total_primitive_steps
            else 0.0,
            "attempted_macro_calls": total_attempted_macro_calls,
            "successful_macro_calls": total_successful_macro_calls,
            "failed_macro_calls": total_failed_macro_calls,
            "macro_success_rate": round(total_successful_macro_calls / total_attempted_macro_calls, 4)
            if total_attempted_macro_calls
            else 0.0,
            "browser_time_ms": round(total_browser_time_ms, 3),
            "primitive_total_time_ms": round(primitive_total_time_ms, 3),
            "macro_total_time_ms": round(macro_total_time_ms, 3),
            "estimated_time_saved_ms": round(primitive_total_time_ms - macro_total_time_ms, 3),
            "macro_hits": dict(macro_hits),
        },
        "groups": groups,
    }


def evaluate_live_learned_policy_benchmark(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    decision_latency_ms: int = 1000,
    headless: bool = True,
    miniwob_url: str | None = None,
    action_scope: str = "task",
    launch_retries: int = 2,
    use_start_step_guard: bool = True,
    training_epochs: int = 8,
    training_seed: int = 0,
) -> dict:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401
    import os
    import time

    if miniwob_url:
        os.environ["MINIWOB_URL"] = miniwob_url

    train_ids_by_group, eval_ids_by_group = split_train_eval_episode_ids(
        rows,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        train_ratio=train_ratio,
        split_seed=split_seed,
    )
    training_examples = collect_learned_policy_examples(
        rows,
        episodes,
        registry_payload,
        episode_ids_by_group=train_ids_by_group,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        action_scope=action_scope,
        headless=headless,
        miniwob_url=miniwob_url,
        launch_retries=launch_retries,
        use_start_step_guard=use_start_step_guard,
    )
    model = train_learned_selector(training_examples, epochs=training_epochs, seed=training_seed)

    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)
    episode_meta = {episode["episode_id"]: episode for episode in episodes}
    total_primitive_steps = 0
    total_agent_decisions = 0
    total_browser_time_ms = 0.0
    total_successes = 0
    total_episodes = 0
    total_attempted_macro_calls = 0
    total_successful_macro_calls = 0
    total_failed_macro_calls = 0
    macro_hits: Counter = Counter()
    groups = []

    for group_key, eval_ids in sorted(eval_ids_by_group.items()):
        macros = action_space_macros(group_key=group_key, registry_by_group=registry_by_group, all_macros=all_macros, action_scope=action_scope)
        group_reports = []
        for episode_id in eval_ids:
            meta = episode_meta[episode_id]
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(str(meta["env_id"]), headless=headless)
                    obs, _ = env.reset(seed=int(meta["seed"]))
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - exercised in live benchmark only
                    last_error = exc
                    if env is not None:
                        try:
                            env.close()
                        except Exception:
                            pass
                        env = None
                    if attempt >= launch_retries:
                        raise
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            if last_error is not None:
                raise last_error

            goal = str(obs.get("goal", ""))
            task_name = str(meta["task_name"])
            plan = build_plan(task_name, goal, obs)
            represented = represented_plan(
                task_name=task_name,
                env_id=str(meta["env_id"]),
                seed=int(meta["seed"]),
                goal=goal,
                plan=plan,
                canonicalization_mode=canonicalization_mode,
                url=str(obs.get("url", "")),
            )
            sequence = [row["canonical_action"] for row in represented]

            index = 0
            agent_decisions = 0
            browser_time_ms = 0.0
            attempted_macro_calls = 0
            successful_macro_calls = 0
            failed_macro_calls = 0
            episode_macro_hits: Counter = Counter()
            blocked_macros_by_index: Dict[int, set[str]] = defaultdict(set)
            attempted_macro_ids: List[str] = []
            successful_macro_ids: List[str] = []
            failed_macro_ids: List[str] = []
            choice_trace: List[dict] = []
            success = False
            final_error = ""

            while index < len(plan):
                choice = learned_choice(
                    model=model,
                    goal=goal,
                    obs=obs,
                    primitive_step=plan[index],
                    primitive_index=index,
                    macros=macros,
                    blocked_macro_ids=blocked_macros_by_index[index],
                    use_start_step_guard=use_start_step_guard,
                )
                if choice["kind"] == "macro":
                    macro = choice["macro"]
                    span = len(macro.get("sequence", []))
                    macro_sequence = list(macro.get("sequence", []))
                    macro_id = str(choice["macro_id"])
                    attempted_macro_calls += 1
                    attempted_macro_ids.append(macro_id)
                    agent_decisions += 1
                    choice_trace.append(
                        {
                            "index": index,
                            "choice": "macro",
                            "macro_id": macro_id,
                            "macro_name": macro.get("suggested_name"),
                            "score": round(float(choice["score"]), 3),
                        }
                    )
                    current_sequence = list(sequence[index : index + span])
                    if current_sequence != macro_sequence:
                        failed_macro_calls += 1
                        failed_macro_ids.append(macro_id)
                        blocked_macros_by_index[index].add(macro_id)
                        continue

                    macro_failed = False
                    executed_steps = 0
                    for step in plan[index : index + span]:
                        action = render_action(step)
                        start = perf_counter()
                        obs, reward, terminated, truncated, info = env.step(action)
                        browser_time_ms += (perf_counter() - start) * 1000.0
                        final_error = str(obs.get("last_action_error", ""))
                        if final_error:
                            failed_macro_calls += 1
                            failed_macro_ids.append(macro_id)
                            blocked_macros_by_index[index + executed_steps].add(macro_id)
                            macro_failed = True
                            break
                        executed_steps += 1
                        if terminated or truncated:
                            task_info = info.get("task_info", {})
                            success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                            break

                    if macro_failed:
                        index += executed_steps
                        continue

                    successful_macro_calls += 1
                    successful_macro_ids.append(macro_id)
                    episode_macro_hits[macro_id] += 1
                    index += span
                    if terminated or truncated:
                        break
                    continue

                action = render_action(plan[index])
                agent_decisions += 1
                choice_trace.append(
                    {
                        "index": index,
                        "choice": "primitive",
                        "primitive_name": choice["primitive_name"],
                        "primitive_description": choice["primitive_description"],
                        "score": round(float(choice["score"]), 3),
                    }
                )
                start = perf_counter()
                obs, reward, terminated, truncated, info = env.step(action)
                browser_time_ms += (perf_counter() - start) * 1000.0
                final_error = str(obs.get("last_action_error", ""))
                index += 1
                if terminated or truncated:
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                    break

            env.close()

            primitive_steps = int(meta["primitive_steps"])
            total_primitive_steps += primitive_steps
            total_agent_decisions += agent_decisions
            total_browser_time_ms += browser_time_ms
            total_successes += int(success)
            total_episodes += 1
            total_attempted_macro_calls += attempted_macro_calls
            total_successful_macro_calls += successful_macro_calls
            total_failed_macro_calls += failed_macro_calls
            macro_hits.update(episode_macro_hits)

            group_reports.append(
                {
                    "episode_id": episode_id,
                    "success": success,
                    "primitive_steps": primitive_steps,
                    "agent_decisions": agent_decisions,
                    "steps_saved": primitive_steps - agent_decisions,
                    "attempted_macro_calls": attempted_macro_calls,
                    "successful_macro_calls": successful_macro_calls,
                    "failed_macro_calls": failed_macro_calls,
                    "attempted_macro_ids": attempted_macro_ids,
                    "successful_macro_ids": successful_macro_ids,
                    "failed_macro_ids": failed_macro_ids,
                    "browser_time_ms": round(browser_time_ms, 3),
                    "primitive_total_time_ms": round(float(meta["browser_time_ms"]) + primitive_steps * decision_latency_ms, 3),
                    "macro_total_time_ms": round(browser_time_ms + agent_decisions * decision_latency_ms, 3),
                    "macro_hits": dict(episode_macro_hits),
                    "choice_trace": choice_trace,
                    "last_action_error": final_error,
                }
            )

        if not group_reports:
            continue

        primitive_group_steps = sum(item["primitive_steps"] for item in group_reports)
        agent_group_steps = sum(item["agent_decisions"] for item in group_reports)
        groups.append(
            {
                "group_key": group_key,
                "macros_available": len(macros),
                "episodes": group_reports,
                "summary": {
                    "episodes": len(group_reports),
                    "success_rate": round(sum(1 for item in group_reports if item["success"]) / len(group_reports), 4),
                    "primitive_steps": primitive_group_steps,
                    "agent_decisions": agent_group_steps,
                    "steps_saved": primitive_group_steps - agent_group_steps,
                    "decision_reduction_ratio": round((primitive_group_steps - agent_group_steps) / primitive_group_steps, 4)
                    if primitive_group_steps
                    else 0.0,
                    "attempted_macro_calls": sum(item["attempted_macro_calls"] for item in group_reports),
                    "successful_macro_calls": sum(item["successful_macro_calls"] for item in group_reports),
                    "failed_macro_calls": sum(item["failed_macro_calls"] for item in group_reports),
                    "browser_time_ms": round(sum(item["browser_time_ms"] for item in group_reports), 3),
                },
            }
        )

    primitive_total_time_ms = sum(
        float(episode_meta[episode["episode_id"]]["browser_time_ms"]) + episode["primitive_steps"] * decision_latency_ms
        for group in groups
        for episode in group["episodes"]
    )
    macro_total_time_ms = sum(float(episode["macro_total_time_ms"]) for group in groups for episode in group["episodes"])
    return {
        "summary": {
            "policy_mode": "learned",
            "action_scope": action_scope,
            "use_start_step_guard": use_start_step_guard,
            "episodes": total_episodes,
            "success_rate": round(total_successes / total_episodes, 4) if total_episodes else 0.0,
            "primitive_steps": total_primitive_steps,
            "agent_decisions": total_agent_decisions,
            "steps_saved": total_primitive_steps - total_agent_decisions,
            "decision_reduction_ratio": round((total_primitive_steps - total_agent_decisions) / total_primitive_steps, 4)
            if total_primitive_steps
            else 0.0,
            "attempted_macro_calls": total_attempted_macro_calls,
            "successful_macro_calls": total_successful_macro_calls,
            "failed_macro_calls": total_failed_macro_calls,
            "macro_success_rate": round(total_successful_macro_calls / total_attempted_macro_calls, 4)
            if total_attempted_macro_calls
            else 0.0,
            "browser_time_ms": round(total_browser_time_ms, 3),
            "primitive_total_time_ms": round(primitive_total_time_ms, 3),
            "macro_total_time_ms": round(macro_total_time_ms, 3),
            "estimated_time_saved_ms": round(primitive_total_time_ms - macro_total_time_ms, 3),
            "macro_hits": dict(macro_hits),
        },
        "training": {
            "examples": len(training_examples),
            "epochs": training_epochs,
            "seed": training_seed,
            "updates": int(model.get("updates", 0)),
        },
        "model": model,
        "groups": groups,
    }


def evaluate_live_llm_policy_benchmark(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str = "task_name",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    decision_latency_ms: int = 1000,
    headless: bool = True,
    miniwob_url: str | None = None,
    action_scope: str = "task",
    launch_retries: int = 2,
    use_start_step_guard: bool = True,
    model: str = "gpt-4.1-mini",
    base_url: str = "https://api.openai.com/v1",
    api_key: str = "",
    cache_path: str = "",
    temperature: float = 0.0,
) -> dict:
    import gymnasium as gym
    import browsergym.miniwob  # noqa: F401
    import os
    import time

    if miniwob_url:
        os.environ["MINIWOB_URL"] = miniwob_url

    chooser = CachedOpenAIChooser(
        model=model,
        api_key=api_key,
        base_url=base_url,
        cache_path=cache_path,
        temperature=temperature,
    )

    _, eval_ids_by_group = split_train_eval_episode_ids(
        rows,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        train_ratio=train_ratio,
        split_seed=split_seed,
    )
    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)
    episode_meta = {episode["episode_id"]: episode for episode in episodes}
    total_primitive_steps = 0
    total_agent_decisions = 0
    total_browser_time_ms = 0.0
    total_successes = 0
    total_episodes = 0
    total_attempted_macro_calls = 0
    total_successful_macro_calls = 0
    total_failed_macro_calls = 0
    total_llm_prompt_tokens = 0
    total_llm_completion_tokens = 0
    total_llm_cached_calls = 0
    total_llm_calls = 0
    macro_hits: Counter = Counter()
    groups = []

    for group_key, eval_ids in sorted(eval_ids_by_group.items()):
        macros = action_space_macros(group_key=group_key, registry_by_group=registry_by_group, all_macros=all_macros, action_scope=action_scope)
        group_reports = []
        for episode_id in eval_ids:
            meta = episode_meta[episode_id]
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(str(meta["env_id"]), headless=headless)
                    obs, _ = env.reset(seed=int(meta["seed"]))
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - exercised in live benchmark only
                    last_error = exc
                    if env is not None:
                        try:
                            env.close()
                        except Exception:
                            pass
                        env = None
                    if attempt >= launch_retries:
                        raise
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            if last_error is not None:
                raise last_error

            goal = str(obs.get("goal", ""))
            task_name = str(meta["task_name"])
            plan = build_plan(task_name, goal, obs)
            represented = represented_plan(
                task_name=task_name,
                env_id=str(meta["env_id"]),
                seed=int(meta["seed"]),
                goal=goal,
                plan=plan,
                canonicalization_mode=canonicalization_mode,
                url=str(obs.get("url", "")),
            )
            sequence = [row["canonical_action"] for row in represented]

            index = 0
            agent_decisions = 0
            browser_time_ms = 0.0
            attempted_macro_calls = 0
            successful_macro_calls = 0
            failed_macro_calls = 0
            llm_prompt_tokens = 0
            llm_completion_tokens = 0
            llm_calls = 0
            llm_cached_calls = 0
            episode_macro_hits: Counter = Counter()
            blocked_macros_by_index: Dict[int, set[str]] = defaultdict(set)
            attempted_macro_ids: List[str] = []
            successful_macro_ids: List[str] = []
            failed_macro_ids: List[str] = []
            choice_trace: List[dict] = []
            success = False
            final_error = ""

            while index < len(plan):
                choice = llm_choice(
                    chooser=chooser,
                    goal=goal,
                    obs=obs,
                    primitive_step=plan[index],
                    primitive_index=index,
                    macros=macros,
                    blocked_macro_ids=blocked_macros_by_index[index],
                    use_start_step_guard=use_start_step_guard,
                )
                usage = dict(choice.get("llm_usage", {}))
                llm_prompt_tokens += int(usage.get("prompt_tokens", 0))
                llm_completion_tokens += int(usage.get("completion_tokens", 0))
                llm_calls += 1
                llm_cached_calls += int(bool(choice.get("llm_cached", False)))

                if choice["kind"] == "macro":
                    macro = choice["macro"]
                    span = len(macro.get("sequence", []))
                    macro_sequence = list(macro.get("sequence", []))
                    macro_id = str(choice["macro_id"])
                    attempted_macro_calls += 1
                    attempted_macro_ids.append(macro_id)
                    agent_decisions += 1
                    choice_trace.append(
                        {
                            "index": index,
                            "choice": "macro",
                            "macro_id": macro_id,
                            "macro_name": macro.get("suggested_name"),
                            "llm_reason": choice.get("llm_reason", ""),
                            "llm_cached": bool(choice.get("llm_cached", False)),
                        }
                    )
                    current_sequence = list(sequence[index : index + span])
                    if current_sequence != macro_sequence:
                        failed_macro_calls += 1
                        failed_macro_ids.append(macro_id)
                        blocked_macros_by_index[index].add(macro_id)
                        continue

                    macro_failed = False
                    executed_steps = 0
                    for step in plan[index : index + span]:
                        action = render_action(step)
                        start = perf_counter()
                        obs, reward, terminated, truncated, info = env.step(action)
                        browser_time_ms += (perf_counter() - start) * 1000.0
                        final_error = str(obs.get("last_action_error", ""))
                        if final_error:
                            failed_macro_calls += 1
                            failed_macro_ids.append(macro_id)
                            blocked_macros_by_index[index + executed_steps].add(macro_id)
                            macro_failed = True
                            break
                        executed_steps += 1
                        if terminated or truncated:
                            task_info = info.get("task_info", {})
                            success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                            break

                    if macro_failed:
                        index += executed_steps
                        continue

                    successful_macro_calls += 1
                    successful_macro_ids.append(macro_id)
                    episode_macro_hits[macro_id] += 1
                    index += span
                    if terminated or truncated:
                        break
                    continue

                action = render_action(plan[index])
                agent_decisions += 1
                choice_trace.append(
                    {
                        "index": index,
                        "choice": "primitive",
                        "primitive_name": choice["primitive_name"],
                        "primitive_description": choice["primitive_description"],
                        "llm_reason": choice.get("llm_reason", ""),
                        "llm_cached": bool(choice.get("llm_cached", False)),
                    }
                )
                start = perf_counter()
                obs, reward, terminated, truncated, info = env.step(action)
                browser_time_ms += (perf_counter() - start) * 1000.0
                final_error = str(obs.get("last_action_error", ""))
                index += 1
                if terminated or truncated:
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                    break

            env.close()

            primitive_steps = int(meta["primitive_steps"])
            total_primitive_steps += primitive_steps
            total_agent_decisions += agent_decisions
            total_browser_time_ms += browser_time_ms
            total_successes += int(success)
            total_episodes += 1
            total_attempted_macro_calls += attempted_macro_calls
            total_successful_macro_calls += successful_macro_calls
            total_failed_macro_calls += failed_macro_calls
            total_llm_prompt_tokens += llm_prompt_tokens
            total_llm_completion_tokens += llm_completion_tokens
            total_llm_calls += llm_calls
            total_llm_cached_calls += llm_cached_calls
            macro_hits.update(episode_macro_hits)

            group_reports.append(
                {
                    "episode_id": episode_id,
                    "success": success,
                    "primitive_steps": primitive_steps,
                    "agent_decisions": agent_decisions,
                    "steps_saved": primitive_steps - agent_decisions,
                    "attempted_macro_calls": attempted_macro_calls,
                    "successful_macro_calls": successful_macro_calls,
                    "failed_macro_calls": failed_macro_calls,
                    "attempted_macro_ids": attempted_macro_ids,
                    "successful_macro_ids": successful_macro_ids,
                    "failed_macro_ids": failed_macro_ids,
                    "browser_time_ms": round(browser_time_ms, 3),
                    "primitive_total_time_ms": round(float(meta["browser_time_ms"]) + primitive_steps * decision_latency_ms, 3),
                    "macro_total_time_ms": round(browser_time_ms + agent_decisions * decision_latency_ms, 3),
                    "macro_hits": dict(episode_macro_hits),
                    "choice_trace": choice_trace,
                    "last_action_error": final_error,
                    "llm_prompt_tokens": llm_prompt_tokens,
                    "llm_completion_tokens": llm_completion_tokens,
                    "llm_calls": llm_calls,
                    "llm_cached_calls": llm_cached_calls,
                }
            )

        if not group_reports:
            continue

        primitive_group_steps = sum(item["primitive_steps"] for item in group_reports)
        agent_group_steps = sum(item["agent_decisions"] for item in group_reports)
        groups.append(
            {
                "group_key": group_key,
                "macros_available": len(macros),
                "episodes": group_reports,
                "summary": {
                    "episodes": len(group_reports),
                    "success_rate": round(sum(1 for item in group_reports if item["success"]) / len(group_reports), 4),
                    "primitive_steps": primitive_group_steps,
                    "agent_decisions": agent_group_steps,
                    "steps_saved": primitive_group_steps - agent_group_steps,
                    "decision_reduction_ratio": round((primitive_group_steps - agent_group_steps) / primitive_group_steps, 4)
                    if primitive_group_steps
                    else 0.0,
                    "attempted_macro_calls": sum(item["attempted_macro_calls"] for item in group_reports),
                    "successful_macro_calls": sum(item["successful_macro_calls"] for item in group_reports),
                    "failed_macro_calls": sum(item["failed_macro_calls"] for item in group_reports),
                    "browser_time_ms": round(sum(item["browser_time_ms"] for item in group_reports), 3),
                    "llm_prompt_tokens": sum(item["llm_prompt_tokens"] for item in group_reports),
                    "llm_completion_tokens": sum(item["llm_completion_tokens"] for item in group_reports),
                    "llm_calls": sum(item["llm_calls"] for item in group_reports),
                    "llm_cached_calls": sum(item["llm_cached_calls"] for item in group_reports),
                },
            }
        )

    primitive_total_time_ms = sum(
        float(episode_meta[episode["episode_id"]]["browser_time_ms"]) + episode["primitive_steps"] * decision_latency_ms
        for group in groups
        for episode in group["episodes"]
    )
    macro_total_time_ms = sum(float(episode["macro_total_time_ms"]) for group in groups for episode in group["episodes"])
    return {
        "summary": {
            "policy_mode": "llm",
            "action_scope": action_scope,
            "use_start_step_guard": use_start_step_guard,
            "episodes": total_episodes,
            "success_rate": round(total_successes / total_episodes, 4) if total_episodes else 0.0,
            "primitive_steps": total_primitive_steps,
            "agent_decisions": total_agent_decisions,
            "steps_saved": total_primitive_steps - total_agent_decisions,
            "decision_reduction_ratio": round((total_primitive_steps - total_agent_decisions) / total_primitive_steps, 4)
            if total_primitive_steps
            else 0.0,
            "attempted_macro_calls": total_attempted_macro_calls,
            "successful_macro_calls": total_successful_macro_calls,
            "failed_macro_calls": total_failed_macro_calls,
            "macro_success_rate": round(total_successful_macro_calls / total_attempted_macro_calls, 4)
            if total_attempted_macro_calls
            else 0.0,
            "browser_time_ms": round(total_browser_time_ms, 3),
            "primitive_total_time_ms": round(primitive_total_time_ms, 3),
            "macro_total_time_ms": round(macro_total_time_ms, 3),
            "estimated_time_saved_ms": round(primitive_total_time_ms - macro_total_time_ms, 3),
            "macro_hits": dict(macro_hits),
            "llm_prompt_tokens": total_llm_prompt_tokens,
            "llm_completion_tokens": total_llm_completion_tokens,
            "llm_total_tokens": total_llm_prompt_tokens + total_llm_completion_tokens,
            "llm_calls": total_llm_calls,
            "llm_cached_calls": total_llm_cached_calls,
        },
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
