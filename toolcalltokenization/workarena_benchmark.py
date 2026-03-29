from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Dict, Iterator, List, Sequence, Tuple


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
