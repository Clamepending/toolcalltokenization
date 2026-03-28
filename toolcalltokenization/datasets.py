from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional
import gzip
import json
import re


LABEL_ATTR_KEYS = (
    "aria-label",
    "label",
    "placeholder",
    "title",
    "name",
    "value",
    "text",
    "textContent",
    "innerText",
    "option",
)
WEBLINX_FIELD_KEYS = ("tag", "text", "xpath", "bbox", "attributes", "children")


def load_json(path: str) -> object:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_jsonl(path: str, rows: Iterable[dict]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def coerce_to_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def pick_label_from_attributes(attrs: dict) -> str:
    for key in LABEL_ATTR_KEYS:
        value = attrs.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = " ".join(str(item) for item in value if str(item).strip())
        text = str(value).strip()
        if text:
            return text
    return ""


def parse_html_like_attributes(raw: str) -> dict:
    attrs = {}
    for key, value in re.findall(r"([a-zA-Z0-9_:-]+)='([^']*)'", raw or ""):
        attrs[key] = value
    return attrs


def choose_mind2web_target(action: dict) -> dict:
    candidates = action.get("pos_candidates", []) or []
    for candidate in candidates:
        if candidate.get("is_original_target"):
            return candidate
    if candidates:
        return candidates[0]
    return {}


def iter_json_files(path: str) -> List[Path]:
    root = Path(path)
    if root.is_file():
        return [root]
    return sorted(candidate for candidate in root.rglob("*.json") if candidate.is_file())


def iter_data_files(path: str, suffixes: tuple = (".json", ".jsonl", ".gz")) -> List[Path]:
    root = Path(path)
    if root.is_file():
        return [root]
    return sorted(
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file() and candidate.suffix in suffixes
    )


def convert_mind2web(input_path: str) -> List[dict]:
    events: List[dict] = []
    for json_path in iter_json_files(input_path):
        payload = load_json(str(json_path))
        tasks = payload if isinstance(payload, list) else [payload]
        for task in tasks:
            if not isinstance(task, dict) or "actions" not in task:
                continue
            action_reprs = task.get("action_reprs", []) or []
            for step_index, action in enumerate(task.get("actions", [])):
                operation = action.get("operation", {}) or {}
                target = choose_mind2web_target(action)
                attrs = coerce_to_dict(target.get("attributes"))
                events.append(
                    {
                        "source_dataset": "mind2web",
                        "episode_id": str(task.get("annotation_id", f"{json_path.stem}:{step_index}")),
                        "task_id": str(task.get("annotation_id", f"{json_path.stem}:{step_index}")),
                        "step_index": step_index,
                        "benchmark": "mind2web",
                        "website": task.get("website"),
                        "domain": task.get("domain"),
                        "subdomain": task.get("subdomain"),
                        "task": task.get("confirmed_task"),
                        "action_type": str(operation.get("op", "unknown")).lower(),
                        "original_action_type": operation.get("original_op"),
                        "value": operation.get("value"),
                        "target_role": target.get("tag"),
                        "target_label": pick_label_from_attributes(attrs),
                        "selector": target.get("backend_node_id"),
                        "raw_action_repr": action_reprs[step_index] if step_index < len(action_reprs) else "",
                        "candidate_attributes": attrs,
                        "source_file": str(json_path),
                    }
                )
    return events


def convert_weblinx_replay(input_path: str, include_chat: bool = False) -> List[dict]:
    root = Path(input_path)
    replay_files: List[Path]
    if root.is_file():
        replay_files = [root]
    else:
        replay_files = sorted(root.rglob("replay.json"))

    events: List[dict] = []
    for replay_path in replay_files:
        payload = load_json(str(replay_path))
        turns = payload.get("data", []) if isinstance(payload, dict) else []
        episode_id = replay_path.parent.name
        step_index = 0
        for turn_index, turn in enumerate(turns):
            turn_type = turn.get("type")
            if turn_type == "chat" and not include_chat:
                continue

            if turn_type == "chat":
                utterance = str(turn.get("utterance", "")).strip()
                events.append(
                    {
                        "source_dataset": "weblinx",
                        "episode_id": episode_id,
                        "step_index": step_index,
                        "benchmark": "weblinx",
                        "turn_type": "chat",
                        "original_turn_index": turn_index,
                        "action_type": "say",
                        "value": utterance,
                        "speaker": turn.get("speaker"),
                        "source_file": str(replay_path),
                    }
                )
                step_index += 1
                continue

            action = turn.get("action", {}) or {}
            args = action.get("arguments", {}) or {}
            metadata = args.get("metadata", {}) or {}
            element = turn.get("element", {}) or {}
            properties = args.get("properties", {}) or {}
            events.append(
                {
                    "source_dataset": "weblinx",
                    "episode_id": episode_id,
                    "step_index": step_index,
                    "benchmark": "weblinx",
                    "turn_type": turn_type,
                    "original_turn_index": turn_index,
                    "action_type": map_weblinx_intent(action.get("intent")),
                    "original_action_type": action.get("intent"),
                    "url": metadata.get("url"),
                    "tab_id": metadata.get("tabId"),
                    "target_role": element.get("tagName") or element.get("role"),
                    "target_label": element.get("textContent") or element.get("ariaLabel"),
                    "selector": args.get("xpath") or args.get("uid"),
                    "value": args.get("text") or args.get("value") or args.get("utterance"),
                    "element": element,
                    "properties": properties,
                    "source_file": str(replay_path),
                }
            )
            step_index += 1
    return events


ACTION_PATTERN = re.compile(r"^(?P<name>[a-zA-Z_]+)\((?P<args>.*)\)$")
ARG_PATTERN = re.compile(r'([a-zA-Z_]+)="((?:[^"\\\\]|\\\\.)*)"')


def parse_action_string(action: str) -> tuple[str, dict]:
    action = str(action).strip()
    match = ACTION_PATTERN.match(action)
    if not match:
        return action.lower(), {}
    name = match.group("name").lower()
    args = {}
    for key, value in ARG_PATTERN.findall(match.group("args")):
        args[key] = bytes(value, "utf-8").decode("unicode_escape")
    return name, args


def parse_weblinx_candidate_blob(candidates: str, uid: str) -> dict:
    if not candidates or not uid:
        return {}
    marker = f"(uid = {uid})"
    start = candidates.find(marker)
    if start < 0:
        return {}
    next_start = candidates.find("\n(uid = ", start + len(marker))
    block = candidates[start: next_start if next_start >= 0 else len(candidates)]
    result = {"uid": uid}
    matches = list(re.finditer(r"\[\[([a-zA-Z]+)\]\]", block))
    for index, match in enumerate(matches):
        key = match.group(1).lower()
        if key not in WEBLINX_FIELD_KEYS:
            continue
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        result[key] = block[value_start:value_end].strip()
    attributes = parse_html_like_attributes(result.get("attributes", ""))
    result["attributes_dict"] = attributes
    return result


def load_jsonl_records(path: Path) -> List[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: List[dict] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def convert_weblinx_chat(input_path: str) -> List[dict]:
    files = [
        candidate
        for candidate in iter_data_files(input_path)
        if candidate.name.endswith(".jsonl") or candidate.name.endswith(".json.gz") or candidate.name.endswith(".json")
    ]
    grouped = {}
    for path in files:
        for row in load_jsonl_records(path):
            if not isinstance(row, dict) or "demo" not in row or "action" not in row:
                continue
            grouped.setdefault(str(row["demo"]), []).append((int(row.get("turn", 0)), row, path))

    events: List[dict] = []
    for demo_name, entries in sorted(grouped.items()):
        for step_index, (turn, row, path) in enumerate(sorted(entries, key=lambda item: item[0])):
            action_name, args = parse_action_string(row.get("action", ""))
            candidate = parse_weblinx_candidate_blob(str(row.get("candidates", "")), str(args.get("uid", "")))
            attributes = candidate.get("attributes_dict", {})
            events.append(
                {
                    "source_dataset": "weblinx_chat",
                    "episode_id": demo_name,
                    "step_index": step_index,
                    "benchmark": "weblinx_chat",
                    "original_turn_index": turn,
                    "action_type": map_weblinx_chat_action(action_name),
                    "original_action_type": action_name,
                    "url": args.get("url"),
                    "selector": args.get("uid"),
                    "target_role": candidate.get("tag"),
                    "target_label": pick_label_from_attributes(attributes) or candidate.get("text"),
                    "value": args.get("text") or args.get("utterance"),
                    "speaker": args.get("speaker"),
                    "candidate": candidate,
                    "raw_action": row.get("action"),
                    "source_file": str(path),
                }
            )
    return events


def map_weblinx_chat_action(action_name: str) -> str:
    mapping = {
        "text_input": "type",
        "load": "goto",
    }
    return mapping.get(action_name, action_name).lower()


def map_weblinx_intent(intent: Optional[str]) -> str:
    if intent is None:
        return "unknown"
    mapping = {
        "textInput": "type",
        "change": "select",
        "tabcreate": "open_tab",
        "tabremove": "close_tab",
        "tabswitch": "switch_tab",
        "load": "goto",
    }
    return mapping.get(str(intent), str(intent)).lower()


def convert_wonderbread_trace(input_path: str) -> List[dict]:
    root = Path(input_path)
    json_files: List[Path]
    if root.is_file():
        json_files = [root]
    else:
        json_files = sorted(
            candidate
            for candidate in root.rglob("*.json")
            if candidate.is_file() and not candidate.name.startswith("[raw]")
        )

    events: List[dict] = []
    for json_path in json_files:
        payload = load_json(str(json_path))
        trace = payload.get("trace", payload if isinstance(payload, list) else [])
        if not isinstance(trace, list):
            continue
        episode_id = json_path.parent.name
        last_state = {}
        step_index = 0
        for event in trace:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            data = event.get("data", {}) or {}
            if event_type == "state":
                last_state = data
                continue
            if event_type != "action":
                continue

            element_info = coerce_to_dict(data.get("element_attributes"))
            element = coerce_to_dict(element_info.get("element"))
            events.append(
                {
                    "source_dataset": "wonderbread",
                    "episode_id": episode_id,
                    "step_index": step_index,
                    "benchmark": "wonderbread",
                    "action_type": map_wonderbread_action(data.get("type")),
                    "original_action_type": data.get("type"),
                    "url": last_state.get("url"),
                    "target_role": element.get("tag") or element.get("tagName"),
                    "target_label": pick_label_from_attributes(element),
                    "selector": element.get("xpath") or element_info.get("xpath"),
                    "value": data.get("text") or data.get("key"),
                    "x": data.get("x"),
                    "y": data.get("y"),
                    "element": element,
                    "state_step": last_state.get("step"),
                    "source_file": str(json_path),
                }
            )
            step_index += 1
    return events


def map_wonderbread_action(action_type: Optional[str]) -> str:
    if action_type is None:
        return "unknown"
    mapping = {
        "mouseup": "click",
        "mousedown": "mousedown",
        "keystroke": "type",
        "keypress": "press",
        "keyrelease": "release",
        "scroll": "scroll",
    }
    return mapping.get(str(action_type), str(action_type)).lower()
