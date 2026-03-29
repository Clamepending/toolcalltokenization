from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import Dict, Sequence
import json
import os
import re

import requests


def load_api_key(*, api_key: str = "", api_key_env_var: str = "OPENAI_API_KEY", env_file: str = "") -> str:
    direct = str(api_key or "").strip()
    if direct:
        return direct
    env_value = str(os.environ.get(api_key_env_var, "")).strip()
    if env_value:
        return env_value
    if env_file:
        path = Path(env_file)
        if path.exists():
            for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != api_key_env_var:
                    continue
                return value.strip().strip('"').strip("'")
    raise ValueError(f"Missing API key for {api_key_env_var!r}. Set the environment variable or pass --env-file.")


def truncate_text(value: object, limit: int = 2400) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def candidate_payload(candidate: dict) -> dict:
    def clean_label(value: object, role: str = "") -> str:
        text = str(value or "").strip()
        if not text:
            return role or "element"
        lowered = text.lower()
        if lowered in {"<text>", "field", "input", "item", "choice", "dropdown", "list", "submit"}:
            return role or text
        if re.match(r"^(io:|ni\.io:)", text, flags=re.IGNORECASE):
            return role or "field"
        if len(text) > 48:
            return role or text[:48]
        return text

    def step_outline(template: dict) -> str:
        kind = str(template.get("kind", "")).strip().lower() or "act"
        role = str(template.get("target_role", "")).strip().lower() or "element"
        label = clean_label(template.get("target_label"), role)
        if kind in {"fill", "type", "paste"}:
            return f"type into {label}"
        if kind == "select":
            return f"select {label}"
        if kind == "goto":
            return "navigate"
        return f"click {label}"

    payload = {
        "id": str(candidate.get("id", "")),
        "kind": str(candidate.get("kind", "")),
        "name": str(candidate.get("name", "")),
        "description": str(candidate.get("description", "")),
        "length": int(candidate.get("length", 1)),
    }
    macro = candidate.get("macro")
    if isinstance(macro, dict):
        payload["sequence"] = list(macro.get("sequence", []))
        payload["step_outline"] = [step_outline(template) for template in list(macro.get("step_templates", []))[:6]]
        payload["replay_precision"] = float(macro.get("replay_precision", 0.0))
        payload["support"] = int(macro.get("support", 0))
    return payload


def build_choice_prompt(
    *,
    goal: str,
    context_text: str,
    candidates: Sequence[dict],
) -> tuple[str, str]:
    system = (
        "You are selecting the next browser action for a web agent. "
        "Choose exactly one candidate id. Prefer a macro only when its first steps clearly fit the immediate next browser actions. "
        "Do not choose a macro just because its later steps sound relevant to the overall task. "
        "If uncertain, choose __primitive__. Respond as JSON with keys id and reason."
    )
    candidate_block = json.dumps([candidate_payload(candidate) for candidate in candidates], indent=2, sort_keys=True)
    user = (
        f"Goal:\n{truncate_text(goal, 1200)}\n\n"
        f"Current browser/task context:\n{truncate_text(context_text, 2400)}\n\n"
        "Candidate actions:\n"
        f"{candidate_block}\n\n"
        "Return JSON like {\"id\":\"candidate_id\",\"reason\":\"short reason\"}."
    )
    return system, user


class CachedOpenAIChooser:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        cache_path: str = "",
        temperature: float = 0.0,
        timeout_s: int = 60,
        max_retries: int = 3,
    ) -> None:
        self.model = str(model)
        self.api_key = str(api_key)
        self.base_url = str(base_url).rstrip("/")
        self.temperature = float(temperature)
        self.timeout_s = int(timeout_s)
        self.max_retries = int(max_retries)
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: Dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                self.cache[str(record["key"])] = dict(record)

    def _cache_key(self, *, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "system": system,
            "user": user,
            "temperature": self.temperature,
        }
        return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _append_cache(self, record: dict) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _parse_choice(self, content: str, candidate_ids: Sequence[str]) -> tuple[str, str]:
        content = str(content or "").strip()
        if not content:
            return "__primitive__", "empty_response"
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                choice_id = str(payload.get("id", "")).strip()
                reason = str(payload.get("reason", "")).strip()
                if choice_id in candidate_ids:
                    return choice_id, reason
        except json.JSONDecodeError:
            pass

        for candidate_id in candidate_ids:
            if candidate_id and re.search(rf"\b{re.escape(candidate_id)}\b", content):
                return candidate_id, "regex_match"
        return "__primitive__", "fallback_primitive"

    def choose(
        self,
        *,
        goal: str,
        context_text: str,
        candidates: Sequence[dict],
    ) -> dict:
        system, user = build_choice_prompt(goal=goal, context_text=context_text, candidates=candidates)
        key = self._cache_key(system=system, user=user)
        candidate_ids = [str(candidate.get("id", "")) for candidate in candidates]

        if key in self.cache:
            cached = dict(self.cache[key])
            choice_id, reason = self._parse_choice(str(cached.get("content", "")), candidate_ids)
            return {
                "id": choice_id,
                "reason": reason,
                "cached": True,
                "usage": dict(cached.get("usage", {})),
                "raw_content": str(cached.get("content", "")),
            }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": 120,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_s,
                )
                response.raise_for_status()
                result = response.json()
                choice_content = str(result["choices"][0]["message"]["content"])
                usage = dict(result.get("usage", {}))
                record = {
                    "key": key,
                    "content": choice_content,
                    "usage": usage,
                }
                self.cache[key] = dict(record)
                self._append_cache(record)
                choice_id, reason = self._parse_choice(choice_content, candidate_ids)
                return {
                    "id": choice_id,
                    "reason": reason,
                    "cached": False,
                    "usage": usage,
                    "raw_content": choice_content,
                }
            except Exception as exc:  # pragma: no cover - network/retry path
                last_error = exc
                if attempt >= self.max_retries - 1:
                    raise
                sleep(min(2.0 * (attempt + 1), 5.0))
        raise RuntimeError(f"LLM call failed: {last_error}")
