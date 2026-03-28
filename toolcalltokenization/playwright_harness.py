from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlsplit

from toolcalltokenization.action_space import load_action_space


class PlaywrightHarnessError(RuntimeError):
    pass


def parse_canonical_step(step: str) -> dict:
    parts = str(step).split("|")
    action = parts[0].strip().upper()
    fields: Dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key] = value
    return {"action": action, "fields": fields}


def binding_map_from_args(parameters: List[dict], arg_values: Dict[str, str]) -> Dict[str, str]:
    bindings: Dict[str, str] = {}
    for parameter in parameters:
        name = parameter["name"]
        binding_id = parameter.get("binding_id")
        if binding_id and name in arg_values:
            bindings[binding_id] = str(arg_values[name])
    return bindings


def fill_value_for_step(parsed_step: dict, bindings: Dict[str, str]) -> str:
    fields = parsed_step["fields"]
    if "use" in fields:
        binding_ids = [value for value in fields["use"].split(",") if value]
        if not binding_ids:
            return ""
        binding_id = binding_ids[0]
        if binding_id not in bindings:
            raise PlaywrightHarnessError(f"Missing binding value for {binding_id}.")
        return bindings[binding_id]
    if "value" in fields:
        return fields["value"]
    return ""


def primitive_name_for_step(parsed_step: dict) -> str:
    action = parsed_step["action"]
    mapping = {
        "GOTO": "goto",
        "CLICK": "click",
        "TYPE": "type",
        "SELECT": "select",
        "SCROLL": "scroll",
        "COPY": "copy",
        "PASTE": "paste",
        "OPEN_TAB": "open_tab",
        "SWITCH_TAB": "switch_tab",
    }
    return mapping.get(action, action.lower())


@dataclass
class PlaywrightHarness:
    action_space_path: str

    def __post_init__(self) -> None:
        payload = load_action_space(self.action_space_path)
        self.actions = {action["name"]: action for action in payload.get("actions", [])}

    def get_action(self, action_name: str) -> dict:
        if action_name not in self.actions:
            raise PlaywrightHarnessError(f"Unknown action: {action_name}")
        return self.actions[action_name]

    def current_scope(self, page) -> dict:
        parsed = urlsplit(page.url)
        host = parsed.netloc.lower()
        site = host.split(".")[0] if host else ""
        return {
            "url": page.url,
            "site": site,
        }

    def check_preconditions(self, page, action: dict, arg_values: Dict[str, str], enforce_scope: bool = False) -> dict:
        preconditions = action.get("preconditions", {})
        missing = [
            parameter["name"]
            for parameter in action.get("parameters", [])
            if parameter.get("required", False) and parameter["name"] not in arg_values
        ]
        if missing:
            return {"ok": False, "reason": f"missing_args:{','.join(missing)}"}

        if enforce_scope and action.get("kind") == "macro":
            scope = self.current_scope(page)
            required_site = preconditions.get("site") or ""
            if required_site and required_site not in scope["site"]:
                return {"ok": False, "reason": f"site_mismatch:{required_site}"}

        steps = action.get("steps", [])
        if action.get("kind") == "macro" and steps:
            parsed_step = parse_canonical_step(steps[0])
            locator = self.locator_for_step(page, parsed_step)
            if locator is None:
                return {"ok": False, "reason": "first_target_unresolved"}
            if locator.count() == 0:
                return {"ok": False, "reason": "first_target_missing"}

        return {"ok": True}

    def locator_for_step(self, page, parsed_step: dict):
        fields = parsed_step["fields"]
        role = fields.get("role", "")
        label = fields.get("label", "")

        if role == "text":
            if label and label != "<TEXT>":
                return page.get_by_text(label, exact=False)
            return page.locator("p, span, div, li, h1, h2, h3").first
        if role == "link":
            if label and label != "<TEXT>":
                return page.get_by_role("link", name=label)
            return page.get_by_role("link").first
        if role == "button":
            if label and label != "<TEXT>":
                return page.get_by_role("button", name=label)
            return page.get_by_role("button").first
        if role == "input":
            if label and label != "<TEXT>":
                attribute_locators = [
                    page.locator(f"input[aria-label*='{label}' i], textarea[aria-label*='{label}' i]"),
                    page.locator(f"input[placeholder*='{label}' i], textarea[placeholder*='{label}' i]"),
                    page.locator(f"input[name*='{label}' i], textarea[name*='{label}' i]"),
                    page.locator(f"input[id*='{label}' i], textarea[id*='{label}' i]"),
                ]
                for locator in attribute_locators:
                    if locator.count():
                        return locator.first
                textbox_locator = page.get_by_role("textbox", name=label)
                if textbox_locator.count():
                    return textbox_locator.first
                searchbox_locator = page.get_by_role("searchbox", name=label)
                if searchbox_locator.count():
                    return searchbox_locator.first
                label_locator = page.get_by_label(label, exact=False)
                if label_locator.count():
                    return label_locator.first
                placeholder_locator = page.get_by_placeholder(label)
                if placeholder_locator.count():
                    return placeholder_locator.first
            textboxes = page.locator("input, textarea").filter(has_not=page.locator("[type=hidden]"))
            return textboxes.first
        if role == "select":
            if label and label != "<TEXT>":
                label_locator = page.get_by_label(label, exact=False)
                if label_locator.count():
                    return label_locator
            return page.locator("select").first

        if label and label != "<TEXT>":
            return page.get_by_text(label, exact=False)
        return None

    def execute_primitive_step(self, page, parsed_step: dict, bindings: Dict[str, str]) -> dict:
        action = primitive_name_for_step(parsed_step)
        fields = parsed_step["fields"]

        if action == "goto":
            url = fields.get("url", "")
            if not url or "<QUERY>" in url:
                raise PlaywrightHarnessError(f"Cannot execute abstract goto step: {url}")
            page.goto(url)
            return {"action": action, "ok": True}

        if action == "scroll":
            page.mouse.wheel(0, 600)
            return {"action": action, "ok": True}

        if action in {"open_tab", "switch_tab", "copy", "paste"}:
            raise PlaywrightHarnessError(f"Primitive {action} is not supported in the first Playwright harness.")

        locator = self.locator_for_step(page, parsed_step)
        if locator is None or locator.count() == 0:
            raise PlaywrightHarnessError(f"Unable to resolve locator for step: {parsed_step}")

        if action == "click":
            locator.first.click()
            return {"action": action, "ok": True}

        value = fill_value_for_step(parsed_step, bindings)
        if action == "type":
            locator.first.fill(value)
            return {"action": action, "ok": True, "value": value}
        if action == "select":
            locator.first.select_option(label=value)
            return {"action": action, "ok": True, "value": value}

        raise PlaywrightHarnessError(f"Unsupported primitive action: {action}")

    def expand_macro(self, action: dict, arg_values: Dict[str, str]) -> List[dict]:
        bindings = binding_map_from_args(action.get("parameters", []), arg_values)
        return [
            {
                "parsed_step": parse_canonical_step(step),
                "bindings": bindings,
            }
            for step in action.get("steps", [])
        ]

    def execute_action(self, page, action_name: str, arg_values: Dict[str, str] | None = None, enforce_scope: bool = False) -> dict:
        arg_values = arg_values or {}
        action = self.get_action(action_name)
        preconditions = self.check_preconditions(page, action, arg_values, enforce_scope=enforce_scope)
        if not preconditions["ok"]:
            return {"action_name": action_name, "ok": False, "stage": "preconditions", "reason": preconditions["reason"]}

        if action.get("kind") == "primitive":
            if action_name == "goto":
                page.goto(arg_values["url"])
                return {"action_name": action_name, "ok": True, "steps": 1}
            raise PlaywrightHarnessError("Direct primitive execution is only implemented for goto in execute_action().")

        bindings = binding_map_from_args(action.get("parameters", []), arg_values)
        executed = []
        for parsed in (parse_canonical_step(step) for step in action.get("steps", [])):
            executed.append(self.execute_primitive_step(page, parsed, bindings))
        return {"action_name": action_name, "ok": True, "steps": len(executed), "executed": executed}


def require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PlaywrightHarnessError(
            "Playwright is not installed. Install it with `pip install playwright` and then run `playwright install chromium`."
        ) from exc
    return sync_playwright


def file_url(path: str) -> str:
    return Path(path).resolve().as_uri()


def stringify_args(items: Iterable[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise PlaywrightHarnessError(f"Expected KEY=VALUE argument, got: {item}")
        key, value = item.split("=", 1)
        parsed[key] = value
    return parsed
