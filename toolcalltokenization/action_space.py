from __future__ import annotations

from pathlib import Path
import json


PRIMITIVE_ACTIONS = [
    {
        "name": "goto",
        "kind": "primitive",
        "description": "Navigate the browser to a URL.",
        "parameters": [{"name": "url", "type": "string", "required": True}],
    },
    {
        "name": "click",
        "kind": "primitive",
        "description": "Click a target element.",
        "parameters": [{"name": "target", "type": "string", "required": True}],
    },
    {
        "name": "type",
        "kind": "primitive",
        "description": "Type text into a target element.",
        "parameters": [
            {"name": "target", "type": "string", "required": True},
            {"name": "text", "type": "string", "required": True},
        ],
    },
    {
        "name": "select",
        "kind": "primitive",
        "description": "Choose a value from a selectable control.",
        "parameters": [
            {"name": "target", "type": "string", "required": True},
            {"name": "value", "type": "string", "required": True},
        ],
    },
    {
        "name": "scroll",
        "kind": "primitive",
        "description": "Scroll the current page or container.",
        "parameters": [{"name": "direction", "type": "string", "required": True}],
    },
    {
        "name": "copy",
        "kind": "primitive",
        "description": "Copy content from a target element.",
        "parameters": [{"name": "target", "type": "string", "required": True}],
    },
    {
        "name": "paste",
        "kind": "primitive",
        "description": "Paste content into a target element.",
        "parameters": [
            {"name": "target", "type": "string", "required": True},
            {"name": "text", "type": "string", "required": True},
        ],
    },
    {
        "name": "open_tab",
        "kind": "primitive",
        "description": "Open a new browser tab.",
        "parameters": [],
    },
    {
        "name": "switch_tab",
        "kind": "primitive",
        "description": "Switch to another browser tab.",
        "parameters": [{"name": "tab_ref", "type": "string", "required": True}],
    },
]


def load_registry(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def parameter_spec(binding_id: str, index: int) -> dict:
    return {
        "name": f"arg{index + 1}",
        "binding_id": binding_id,
        "type": "string",
        "required": True,
    }


def macro_action_spec(entry: dict) -> dict:
    parameters = [
        parameter_spec(binding_id, index)
        for index, binding_id in enumerate(entry.get("input_bindings", []))
    ]
    trigger_prefix_len = int(entry.get("trigger_prefix_len", 1))
    steps = list(entry.get("sequence", []))
    return {
        "name": entry["suggested_name"],
        "kind": "macro",
        "description": entry["suggested_description"],
        "parameters": parameters,
        "group_key": entry.get("group_key", "<all>"),
        "steps": steps,
        "preconditions": {
            "group_key": entry.get("group_key", "<all>"),
            "site": entry.get("site"),
            "task_family": entry.get("task_family"),
            "required_inputs": list(entry.get("input_bindings", [])),
            "trigger_prefix_len": trigger_prefix_len,
            "trigger_prefix": steps[: min(trigger_prefix_len, len(steps))],
        },
        "metadata": {
            "registry_id": entry.get("registry_id"),
            "macro_id": entry.get("macro_id"),
            "canonicalization_mode": entry.get("canonicalization_mode"),
            "support": entry.get("support", 0),
            "occurrences": entry.get("occurrences", 0),
            "replay_precision": entry.get("replay_precision", 0.0),
            "eval_steps_saved": entry.get("eval_steps_saved", 0),
            "num_inputs": entry.get("num_inputs", 0),
        },
    }


def build_action_space(registry_payload: dict, include_primitives: bool = True) -> dict:
    registry = list(registry_payload.get("registry", []))
    actions = []
    if include_primitives:
        actions.extend(PRIMITIVE_ACTIONS)
    actions.extend(macro_action_spec(entry) for entry in registry)

    return {
        "summary": {
            "primitive_actions": len(PRIMITIVE_ACTIONS) if include_primitives else 0,
            "macro_actions": len(registry),
            "parameterized_macro_actions": sum(1 for entry in registry if entry.get("num_inputs", 0) > 0),
            "total_actions": len(actions),
        },
        "actions": actions,
    }


def dump_action_space(path: str, payload: dict) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
