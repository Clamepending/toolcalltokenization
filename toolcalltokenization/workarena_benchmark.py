from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import json
import re
from time import perf_counter
from typing import Dict, Iterator, List, Sequence, Tuple

from .llm_client import CachedOpenAIChooser
from .selector_benchmark import (
    action_space_macros,
    collect_selector_examples,
    learned_choice,
    llm_choice as replay_llm_choice,
    macro_runtime_id,
    macro_start_compatible,
    choose_oracle_macro,
    replay_rows_by_episode,
    row_context_text,
    semantic_choice,
    split_train_eval_episode_ids,
    train_learned_selector,
)


WORKARENA_SERVICE_CATALOG_TASKS = (
    "browsergym/workarena.servicenow.order-apple-mac-book-pro15",
    "browsergym/workarena.servicenow.order-apple-watch",
    "browsergym/workarena.servicenow.order-developer-laptop",
    "browsergym/workarena.servicenow.order-development-laptop-p-c",
    "browsergym/workarena.servicenow.order-ipad-mini",
    "browsergym/workarena.servicenow.order-ipad-pro",
    "browsergym/workarena.servicenow.order-loaner-laptop",
    "browsergym/workarena.servicenow.order-sales-laptop",
    "browsergym/workarena.servicenow.order-standard-laptop",
)


ACTION_METADATA_JS = """el => ({
  tag: (el.tagName || '').toLowerCase(),
  role: el.getAttribute('role') || '',
  aria_label: el.getAttribute('aria-label') || '',
  placeholder: el.getAttribute('placeholder') || '',
  text: ((el.innerText || el.textContent || '') + '').trim().slice(0, 240),
  value: ((el.value || '') + '').trim().slice(0, 240),
  id: el.id || '',
  name: el.getAttribute('name') || '',
  type: el.getAttribute('type') || '',
  url: window.location.href
})"""


def workarena_task_name(env_id: str) -> str:
    short = str(env_id).split(".")[-1]
    return short.replace("-", "_")


def episode_id_for(task_name: str, seed: int) -> str:
    return f"{task_name}::{seed:04d}"


def normalize_target_role(meta: dict) -> str:
    explicit_role = str(meta.get("role", "")).strip().lower()
    if explicit_role:
        return explicit_role
    tag = str(meta.get("tag", "")).strip().lower()
    input_type = str(meta.get("type", "")).strip().lower()
    if tag in {"input", "textarea"}:
        if input_type in {"button", "submit"}:
            return "button"
        return "input"
    if tag == "select":
        return "select"
    if tag == "button":
        return "button"
    if tag == "a":
        return "link"
    if tag == "label":
        return "choice"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "div"}:
        return "text"
    return tag or "element"


def choose_target_label(meta: dict) -> str:
    candidates = [
        str(meta.get("aria_label", "")).strip(),
        str(meta.get("placeholder", "")).strip(),
        str(meta.get("name", "")).strip(),
        str(meta.get("id", "")).strip(),
        str(meta.get("value", "")).strip(),
        str(meta.get("text", "")).strip(),
    ]
    for candidate in candidates:
        if candidate:
            return " ".join(candidate.split())[:120]
    return ""


def selector_hint(meta: dict) -> str:
    for key in ("id", "name", "placeholder"):
        value = str(meta.get(key, "")).strip()
        if value:
            return value
    label = choose_target_label(meta)
    if label:
        return label[:80]
    return str(meta.get("tag", "")).strip().lower() or "element"


def stringify_action_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("value", "label", "index"):
            if key in value:
                return stringify_action_value(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(part for part in (stringify_action_value(item) for item in value) if part)
    return str(value)


def extract_target_metadata(target: object) -> dict:
    try:
        payload = target.evaluate(ACTION_METADATA_JS)
    except Exception:
        payload = {}
    return payload or {}


def workarena_trace_row(
    *,
    task_name: str,
    env_id: str,
    seed: int,
    goal: str,
    task_family: str,
    step_index: int,
    action_name: str,
    meta: dict,
    value: str,
    step_duration_ms: float,
) -> dict:
    target_role = normalize_target_role(meta)
    target_label = choose_target_label(meta)
    row = {
        "episode_id": episode_id_for(task_name, seed),
        "task_name": task_name,
        "benchmark": "workarena",
        "website": "servicenow",
        "task_family": task_family,
        "website_task_family": f"servicenow::{task_family}",
        "env_id": env_id,
        "seed": seed,
        "task": goal,
        "confirmed_task": goal,
        "step_index": step_index,
        "action_type": action_name,
        "action_name": action_name,
        "raw_action_repr": f"{action_name}({selector_hint(meta)})",
        "selector": selector_hint(meta),
        "target_role": target_role,
        "target_label": target_label,
        "url": str(meta.get("url", "")),
        "step_duration_ms": round(step_duration_ms, 3),
    }
    if value:
        row["value"] = value
    return row


@contextmanager
def record_playwright_actions(
    rows: List[dict],
    *,
    task_name: str,
    env_id: str,
    seed: int,
    goal: str,
    task_family: str,
) -> Iterator[None]:
    from playwright.sync_api import ElementHandle, Locator

    originals: List[Tuple[type, str, object]] = []

    def patch(cls: type, method_name: str, action_name: str) -> None:
        original = getattr(cls, method_name, None)
        if original is None:
            return

        def wrapped(target, *args, **kwargs):
            meta = extract_target_metadata(target)
            value = ""
            if action_name in {"fill", "select"}:
                payload = args[0] if args else kwargs.get("value", kwargs.get("values"))
                value = stringify_action_value(payload)
            start = perf_counter()
            result = original(target, *args, **kwargs)
            duration_ms = (perf_counter() - start) * 1000.0
            rows.append(
                workarena_trace_row(
                    task_name=task_name,
                    env_id=env_id,
                    seed=seed,
                    goal=goal,
                    task_family=task_family,
                    step_index=len(rows),
                    action_name=action_name,
                    meta=meta,
                    value=value,
                    step_duration_ms=duration_ms,
                )
            )
            return result

        setattr(cls, method_name, wrapped)
        originals.append((cls, method_name, original))

    for cls in (Locator, ElementHandle):
        patch(cls, "click", "click")
        patch(cls, "fill", "fill")
        patch(cls, "select_option", "select")

    try:
        yield
    finally:
        for cls, method_name, original in reversed(originals):
            setattr(cls, method_name, original)


def collect_workarena_cheat_traces(
    *,
    tasks: Sequence[str] = WORKARENA_SERVICE_CATALOG_TASKS,
    episodes_per_task: int = 2,
    seed_start: int = 0,
    headless: bool = True,
    launch_retries: int = 2,
) -> dict:
    import time

    import browsergym.workarena
    import gymnasium as gym

    rows: List[dict] = []
    episodes: List[dict] = []

    for env_id in tasks:
        task_name = workarena_task_name(env_id)
        for seed in range(seed_start, seed_start + episodes_per_task):
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(env_id, headless=headless)
                    obs, _ = env.reset(seed=seed)
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - exercised only in live benchmark
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

            base = env.unwrapped
            task_id = str(base.task.get_task_id())
            _, task_family = browsergym.workarena.get_task_category(task_id)
            task_family = task_family or "unknown"
            goal = str(obs.get("goal", ""))
            episode_rows: List[dict] = []

            cheat_start = perf_counter()
            with record_playwright_actions(
                episode_rows,
                task_name=task_name,
                env_id=env_id,
                seed=seed,
                goal=goal,
                task_family=task_family,
            ):
                base.task.cheat(page=base.page, chat_messages=list(base.chat.messages))
            cheat_time_ms = (perf_counter() - cheat_start) * 1000.0
            obs_after, reward, terminated, truncated, info = base.post_step({}, validate=True)
            success = bool(reward > 0)
            rows.extend(episode_rows)
            episodes.append(
                {
                    "episode_id": episode_id_for(task_name, seed),
                    "task_name": task_name,
                    "task_family": task_family,
                    "env_id": env_id,
                    "seed": seed,
                    "goal": goal,
                    "primitive_steps": len(episode_rows),
                    "browser_time_ms": round(cheat_time_ms, 3),
                    "success": success,
                    "reward": float(reward),
                    "done": bool(terminated or truncated),
                    "last_action_error": str(obs_after.get("last_action_error", "")),
                    "actions": [row["raw_action_repr"] for row in episode_rows],
                }
            )
            env.close()

    return {"rows": rows, "episodes": episodes}


def workarena_observation_text(obs: dict, *, max_named_nodes: int = 48) -> str:
    parts = [str(obs.get("url", ""))]
    interesting_roles = {
        "button",
        "checkbox",
        "combobox",
        "heading",
        "link",
        "listitem",
        "menuitem",
        "option",
        "radio",
        "searchbox",
        "select",
        "tab",
        "textbox",
    }
    count = 0
    for node in obs.get("axtree_object", {}).get("nodes", []):
        role = str((node.get("role", {}) or {}).get("value", "")).strip().lower()
        name = str((node.get("name", {}) or {}).get("value", "")).strip()
        if not name or not role or role not in interesting_roles:
            continue
        name = " ".join(name.split())[:120]
        parts.append(f"{role}:{name}")
        count += 1
        if count >= max_named_nodes:
            break
    return " ".join(part for part in parts if part)


def _attribute_selector(attr: str, value: str) -> str:
    return f"[{attr}={json.dumps(value)}]"


def target_hints(row: dict) -> List[str]:
    hints: List[str] = []
    for candidate in (
        str(row.get("selector", "")).strip(),
        str(row.get("target_label", "")).strip(),
    ):
        if not candidate or candidate in hints or candidate == "<TEXT>":
            continue
        hints.append(candidate)
    return hints


def is_machine_label(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(re.match(r"^(io:|ni\.io:)", text, flags=re.IGNORECASE))


def search_contexts(page) -> List[object]:
    contexts: List[object] = []
    seen = set()
    for frame in reversed(page.frames):
        key = (frame.name, frame.url)
        if key in seen:
            continue
        seen.add(key)
        contexts.append(frame)
    return contexts


def preferred_locator(locator):
    try:
        count = locator.count()
    except Exception:
        return None
    if count <= 0:
        return None
    for index in range(min(count, 5)):
        candidate = locator.nth(index)
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    return locator.first


def locator_for_row(page, row: dict):
    role = str(row.get("target_role", "")).strip().lower()
    label = str(row.get("target_label", "")).strip()
    hints = target_hints(row)
    contexts = search_contexts(page)

    for context in contexts:
        for hint in hints:
            for attr in ("id", "name", "aria-label", "placeholder"):
                locator = context.locator(_attribute_selector(attr, hint))
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen

    if role == "link":
        for context in contexts:
            if label and not is_machine_label(label):
                locator = context.get_by_role("link", name=label, exact=False)
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
                locator = context.get_by_text(label, exact=False)
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
            locator = context.get_by_role("link").first
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
        return None

    if role == "button":
        for context in contexts:
            if label and not is_machine_label(label):
                locator = context.get_by_role("button", name=label, exact=False)
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
                locator = context.locator(f'input[type="submit"][value={json.dumps(label)}], input[type="button"][value={json.dumps(label)}]')
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
                locator = context.get_by_text(label, exact=False)
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
            locator = context.get_by_role("button").first
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
        return None

    if role == "select":
        for context in contexts:
            if label and not is_machine_label(label):
                locator = context.get_by_label(label, exact=False)
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
            locator = context.locator("select")
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
        return None

    if role in {"input", "searchbox", "textbox"}:
        for context in contexts:
            if label and not is_machine_label(label):
                for locator in (
                    context.get_by_label(label, exact=False),
                    context.get_by_role("textbox", name=label, exact=False),
                    context.get_by_role("searchbox", name=label, exact=False),
                    context.get_by_placeholder(label),
                ):
                    chosen = preferred_locator(locator)
                    if chosen is not None:
                        return chosen
            locator = context.locator("input, textarea").filter(has_not=context.locator("[type=hidden]"))
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
        return None

    if role in {"choice", "checkbox", "radio", "option", "listitem"}:
        for context in contexts:
            if label and not is_machine_label(label):
                for locator in (
                    context.get_by_label(label, exact=False),
                    context.get_by_role("radio", name=label, exact=False),
                    context.get_by_role("checkbox", name=label, exact=False),
                    context.get_by_role("option", name=label, exact=False),
                    context.get_by_text(label, exact=False),
                ):
                    chosen = preferred_locator(locator)
                    if chosen is not None:
                        return chosen
            locator = context.locator("label, input[type=radio], input[type=checkbox]").first
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
        return None

    if role == "text":
        for context in contexts:
            if label and not is_machine_label(label):
                locator = context.get_by_text(label, exact=False)
                chosen = preferred_locator(locator)
                if chosen is not None:
                    return chosen
            locator = context.locator("p, span, div, li, h1, h2, h3").first
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
        return None

    if label and not is_machine_label(label):
        for context in contexts:
            locator = context.get_by_text(label, exact=False)
            chosen = preferred_locator(locator)
            if chosen is not None:
                return chosen
    return None


def execute_row_action(base, row: dict) -> tuple[dict, float, bool, bool, dict]:
    page = base.page
    action_name = str(row.get("action_name") or row.get("action_type") or "").strip().lower()
    locator = locator_for_row(page, row)
    if locator is None or locator.count() == 0:
        raise RuntimeError(f"Unable to resolve target for {action_name}:{row.get('target_role')}:{row.get('target_label')}")

    value = str(row.get("value", ""))
    if action_name == "click":
        locator.scroll_into_view_if_needed()
        try:
            locator.click()
        except Exception:
            locator.click(force=True)
    elif action_name == "fill":
        locator.scroll_into_view_if_needed()
        locator.fill(value)
    elif action_name == "select":
        locator.scroll_into_view_if_needed()
        selected = False
        for kwargs in ({"label": value}, {"value": value}):
            try:
                locator.select_option(**kwargs)
                selected = True
                break
            except Exception:
                continue
        if not selected:
            try:
                locator.select_option(index=int(value))
                selected = True
            except Exception as exc:
                raise RuntimeError(f"Unable to select {value!r} for {row.get('target_label')!r}") from exc
    else:
        raise RuntimeError(f"Unsupported action: {action_name}")

    return base.post_step({}, validate=True)


def live_llm_choice(
    *,
    chooser: CachedOpenAIChooser,
    row: dict,
    obs: dict,
    previous_actions: Sequence[str],
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    use_start_step_guard: bool,
) -> dict:
    from .selector_benchmark import candidate_set

    candidates = candidate_set(
        row=row,
        macros=macros,
        blocked_macro_ids=blocked_macro_ids,
        use_start_step_guard=use_start_step_guard,
    )
    result = chooser.choose(
        goal=str(row.get("task") or row.get("confirmed_task") or ""),
        context_text=f"{row_context_text(row, previous_actions)}\n\n{workarena_observation_text(obs)}",
        candidates=candidates,
    )
    chosen_id = str(result.get("id", "__primitive__"))
    chosen = next((candidate for candidate in candidates if candidate["id"] == chosen_id), candidates[0])
    base = {
        "score": 0.0,
        "llm_reason": str(result.get("reason", "")),
        "llm_cached": bool(result.get("cached", False)),
        "llm_usage": dict(result.get("usage", {})),
        "llm_raw_content": str(result.get("raw_content", "")),
    }
    if chosen["kind"] == "primitive":
        return {"kind": "primitive", **base}
    return {
        "kind": "macro",
        "macro": chosen["macro"],
        "macro_id": chosen["id"],
        **base,
    }


def evaluate_live_workarena_policy_benchmark(
    rows: Sequence[dict],
    episodes: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str = "task_family",
    canonicalization_mode: str = "dataflow_coarse",
    train_ratio: float = 0.8,
    split_seed: int = 0,
    action_scope: str = "task",
    policy_mode: str = "llm",
    margin: float = 0.0,
    use_start_step_guard: bool = True,
    training_epochs: int = 20,
    training_seed: int = 0,
    llm_chooser: CachedOpenAIChooser | None = None,
    decision_latency_ms: int = 1000,
    headless: bool = True,
    launch_retries: int = 2,
) -> dict:
    import gymnasium as gym
    import browsergym.workarena  # noqa: F401
    import time

    train_ids_by_group, eval_ids_by_group = split_train_eval_episode_ids(
        rows,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        train_ratio=train_ratio,
        split_seed=split_seed,
    )
    replay_by_episode = replay_rows_by_episode(rows, canonicalization_mode)

    model = None
    if policy_mode == "learned":
        examples = collect_selector_examples(
            rows,
            registry_payload,
            episode_ids_by_group=train_ids_by_group,
            group_by=group_by,
            canonicalization_mode=canonicalization_mode,
            action_scope=action_scope,
            use_start_step_guard=use_start_step_guard,
        )
        model = train_learned_selector(examples, epochs=training_epochs, seed=training_seed)
    elif policy_mode == "llm" and llm_chooser is None:
        raise ValueError("LLM policy requested without llm_chooser.")

    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=lambda item: (
        -float(item.get("replay_precision", 0.0)) * max(len(item.get("sequence", [])) - 1, 0),
        -float(item.get("replay_precision", 0.0)),
        -len(item.get("sequence", [])),
        -int(item.get("support", 0)),
        str(item.get("suggested_name", item.get("macro_id", ""))),
    ))
    episode_meta = {str(episode["episode_id"]): episode for episode in episodes}

    total_primitive_steps = 0
    total_agent_decisions = 0
    total_browser_time_ms = 0.0
    total_successes = 0
    total_episodes = 0
    total_attempted_macro_calls = 0
    total_successful_macro_calls = 0
    total_failed_macro_calls = 0
    total_llm_calls = 0
    total_llm_cached_calls = 0
    total_llm_prompt_tokens = 0
    total_llm_completion_tokens = 0
    macro_hits: Counter = Counter()
    groups = []

    for group_key, eval_ids in sorted(eval_ids_by_group.items()):
        macros = action_space_macros(
            group_key=group_key,
            registry_by_group=registry_by_group,
            all_macros=all_macros,
            action_scope=action_scope,
        )
        group_reports = []
        for episode_id in eval_ids:
            rows_for_episode = replay_by_episode.get(str(episode_id), [])
            if not rows_for_episode:
                continue

            meta = episode_meta[str(episode_id)]
            env = None
            last_error = None
            for attempt in range(launch_retries + 1):
                try:
                    env = gym.make(str(meta["env_id"]), headless=headless)
                    obs, _ = env.reset(seed=int(meta["seed"]))
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - live benchmark only
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

            base = env.unwrapped
            sequence = [str(row.get("canonical_action", "")) for row in rows_for_episode]
            index = 0
            agent_decisions = 0
            browser_time_ms = 0.0
            attempted_macro_calls = 0
            successful_macro_calls = 0
            failed_macro_calls = 0
            llm_calls = 0
            llm_cached_calls = 0
            llm_prompt_tokens = 0
            llm_completion_tokens = 0
            episode_macro_hits: Counter = Counter()
            blocked_macros_by_index: Dict[int, set[str]] = defaultdict(set)
            attempted_macro_ids: List[str] = []
            successful_macro_ids: List[str] = []
            failed_macro_ids: List[str] = []
            choice_trace: List[dict] = []
            previous_actions: List[str] = []
            success = False
            final_error = ""

            while index < len(rows_for_episode):
                row = rows_for_episode[index]
                if policy_mode == "oracle":
                    macro = choose_oracle_macro(sequence[index:], macros, blocked_macros_by_index[index])
                    choice = {"kind": "macro", "macro": macro, "macro_id": macro_runtime_id(macro)} if macro else {"kind": "primitive"}
                elif policy_mode == "primitive":
                    choice = {"kind": "primitive"}
                elif policy_mode == "semantic":
                    choice = semantic_choice(
                        row=row,
                        previous_actions=previous_actions,
                        macros=macros,
                        blocked_macro_ids=blocked_macros_by_index[index],
                        margin=margin,
                        use_start_step_guard=use_start_step_guard,
                    )
                elif policy_mode == "learned":
                    if model is None:
                        raise ValueError("Learned policy requested without a trained model.")
                    choice = learned_choice(
                        model=model,
                        row=row,
                        previous_actions=previous_actions,
                        macros=macros,
                        blocked_macro_ids=blocked_macros_by_index[index],
                        use_start_step_guard=use_start_step_guard,
                    )
                elif policy_mode == "llm":
                    if llm_chooser is None:
                        raise ValueError("LLM policy requested without llm_chooser.")
                    choice = live_llm_choice(
                        chooser=llm_chooser,
                        row=row,
                        obs=obs,
                        previous_actions=previous_actions,
                        macros=macros,
                        blocked_macro_ids=blocked_macros_by_index[index],
                        use_start_step_guard=use_start_step_guard,
                    )
                    llm_calls += 1
                    usage = dict(choice.get("llm_usage", {}))
                    llm_prompt_tokens += int(usage.get("prompt_tokens", 0))
                    llm_completion_tokens += int(usage.get("completion_tokens", 0))
                    if choice.get("llm_cached"):
                        llm_cached_calls += 1
                else:
                    raise ValueError(f"Unsupported policy_mode: {policy_mode!r}")

                if choice["kind"] == "macro":
                    macro = dict(choice["macro"])
                    macro_id = str(choice["macro_id"])
                    span = len(macro.get("sequence", []))
                    attempted_macro_calls += 1
                    attempted_macro_ids.append(macro_id)
                    agent_decisions += 1
                    choice_trace.append(
                        {
                            "index": index,
                            "choice": "macro",
                            "macro_id": macro_id,
                            "macro_name": macro.get("suggested_name"),
                            "score": round(float(choice.get("score", 0.0)), 3),
                            "llm_reason": str(choice.get("llm_reason", "")),
                            "llm_cached": bool(choice.get("llm_cached", False)),
                        }
                    )
                    if list(sequence[index : index + span]) != list(macro.get("sequence", [])):
                        failed_macro_calls += 1
                        failed_macro_ids.append(macro_id)
                        blocked_macros_by_index[index].add(macro_id)
                        continue

                    macro_failed = False
                    executed_steps = 0
                    for step_row in rows_for_episode[index : index + span]:
                        try:
                            start = perf_counter()
                            obs, reward, terminated, truncated, info = execute_row_action(base, step_row)
                            browser_time_ms += (perf_counter() - start) * 1000.0
                            final_error = str(obs.get("last_action_error", ""))
                            if final_error:
                                raise RuntimeError(final_error)
                        except Exception as exc:
                            failed_macro_calls += 1
                            failed_macro_ids.append(macro_id)
                            blocked_macros_by_index[index + executed_steps].add(macro_id)
                            final_error = str(exc)
                            macro_failed = True
                            break
                        previous_actions.append(str(step_row.get("canonical_action", "")))
                        executed_steps += 1
                        if terminated or truncated:
                            task_info = info.get("task_info", {})
                            success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                            break

                    if macro_failed:
                        index += executed_steps
                        if final_error:
                            break
                        continue

                    successful_macro_calls += 1
                    successful_macro_ids.append(macro_id)
                    episode_macro_hits[macro_id] += 1
                    index += span
                    if terminated or truncated:
                        break
                    continue

                try:
                    start = perf_counter()
                    obs, reward, terminated, truncated, info = execute_row_action(base, row)
                    browser_time_ms += (perf_counter() - start) * 1000.0
                    final_error = str(obs.get("last_action_error", ""))
                    if final_error:
                        raise RuntimeError(final_error)
                except Exception as exc:
                    final_error = str(exc)
                    agent_decisions += 1
                    choice_trace.append(
                        {
                            "index": index,
                            "choice": "primitive",
                            "llm_reason": str(choice.get("llm_reason", "")),
                            "llm_cached": bool(choice.get("llm_cached", False)),
                            "error": final_error,
                        }
                    )
                    break

                agent_decisions += 1
                choice_trace.append(
                    {
                        "index": index,
                        "choice": "primitive",
                        "llm_reason": str(choice.get("llm_reason", "")),
                        "llm_cached": bool(choice.get("llm_cached", False)),
                    }
                )
                previous_actions.append(str(row.get("canonical_action", "")))
                index += 1
                if terminated or truncated:
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                    break

            if not final_error and not success:
                try:
                    obs, reward, terminated, truncated, info = base.post_step({}, validate=True)
                    final_error = str(obs.get("last_action_error", ""))
                    task_info = info.get("task_info", {})
                    success = bool(task_info.get("RAW_REWARD_GLOBAL", 0) > 0 or reward > 0)
                except Exception as exc:
                    final_error = str(exc)

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
            total_llm_calls += llm_calls
            total_llm_cached_calls += llm_cached_calls
            total_llm_prompt_tokens += llm_prompt_tokens
            total_llm_completion_tokens += llm_completion_tokens
            macro_hits.update(episode_macro_hits)

            group_reports.append(
                {
                    "episode_id": str(episode_id),
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
                    "llm_calls": llm_calls,
                    "llm_cached_calls": llm_cached_calls,
                    "llm_prompt_tokens": llm_prompt_tokens,
                    "llm_completion_tokens": llm_completion_tokens,
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
                    "llm_calls": sum(item.get("llm_calls", 0) for item in group_reports),
                    "llm_cached_calls": sum(item.get("llm_cached_calls", 0) for item in group_reports),
                    "llm_prompt_tokens": sum(item.get("llm_prompt_tokens", 0) for item in group_reports),
                    "llm_completion_tokens": sum(item.get("llm_completion_tokens", 0) for item in group_reports),
                },
            }
        )

    primitive_total_time_ms = sum(
        float(episode_meta[str(episode["episode_id"])]["browser_time_ms"]) + episode["primitive_steps"] * decision_latency_ms
        for group in groups
        for episode in group["episodes"]
    )
    macro_total_time_ms = sum(float(episode["macro_total_time_ms"]) for group in groups for episode in group["episodes"])
    summary = {
        "policy_mode": policy_mode,
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
    }
    if policy_mode == "learned" and model is not None:
        summary["model"] = {
            "model_type": model.get("model_type"),
            "epochs": model.get("epochs"),
            "training_examples": model.get("examples"),
            "updates": model.get("updates"),
            "nonzero_weights": len(model.get("weights", {})),
        }
    if policy_mode == "llm":
        summary["llm_calls"] = total_llm_calls
        summary["llm_cached_calls"] = total_llm_cached_calls
        summary["llm_prompt_tokens"] = total_llm_prompt_tokens
        summary["llm_completion_tokens"] = total_llm_completion_tokens
        summary["llm_total_tokens"] = total_llm_prompt_tokens + total_llm_completion_tokens
    return {"summary": summary, "groups": groups}
