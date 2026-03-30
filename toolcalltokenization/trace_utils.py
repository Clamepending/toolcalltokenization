from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlsplit
import json
import random
import re


SHORT_TEXT_MAX_LEN = 24
SHORT_TEXT_MAX_WORDS = 3
EVENTWISE_MODES = (
    "name_only",
    "value_slots",
    "coarse_signature",
    "target_signature",
    "signature",
)
DATAFLOW_MODES = (
    "dataflow",
    "dataflow_coarse",
)
CANONICALIZATION_MODES = (
    *EVENTWISE_MODES,
    *DATAFLOW_MODES,
)
TEXT_KEYS = ("value", "text", "query", "search", "input")
LABEL_KEYS = ("target_text", "target_label", "label", "name")
ROLE_KEYS = ("target_role", "role")
SELECTOR_KEYS = ("selector", "target_selector")
SLOT_KEYS = ("slot", "value_slot")
ARGUMENT_KEYS = ("arguments", "args")
OUTPUT_KEYS = ("output", "result", "return_value", "return", "response")
SLOT_HINTS = {
    "search": "SEARCH_TERM",
    "query": "SEARCH_TERM",
    "city": "CITY",
    "location": "LOCATION",
    "destination": "DESTINATION",
    "origin": "ORIGIN",
    "email": "EMAIL",
    "mail": "EMAIL",
    "date": "DATE",
    "time": "TIME",
    "name": "NAME",
    "phone": "PHONE",
    "zip": "ZIP",
    "postal": "ZIP",
}
COARSE_ROLE_ALIASES = {
    "a": "link",
    "link": "link",
    "button": "button",
    "input": "input",
    "textarea": "input",
    "searchbox": "input",
    "textbox": "input",
    "select": "select",
    "combobox": "select",
    "option": "option",
    "checkbox": "choice",
    "radio": "choice",
    "tab": "tab",
    "img": "media",
    "image": "media",
}
TEXTISH_ROLES = {
    "div",
    "span",
    "p",
    "li",
    "td",
    "th",
    "tr",
    "label",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
COARSE_LABEL_HINTS = (
    ("add to cart", "add_to_cart"),
    ("check out", "checkout"),
    ("checkout", "checkout"),
    ("sign in", "login"),
    ("log in", "login"),
    ("login", "login"),
    ("sign up", "signup"),
    ("register", "signup"),
    ("first name", "first_name"),
    ("last name", "last_name"),
    ("phone", "phone"),
    ("postal", "zip"),
    ("zip", "zip"),
    ("email", "email"),
    ("password", "password"),
    ("destination", "destination"),
    ("origin", "origin"),
    ("depart", "depart"),
    ("return", "return"),
    ("city", "city"),
    ("location", "location"),
    ("date", "date"),
    ("time", "time"),
    ("guest", "guests"),
    ("adult", "adults"),
    ("children", "children"),
    ("search", "search"),
    ("submit", "submit"),
    ("save", "save"),
    ("apply", "apply"),
    ("filter", "filter"),
    ("sort", "sort"),
    ("next", "next"),
    ("continue", "next"),
    ("previous", "previous"),
    ("back", "back"),
    ("close", "close"),
    ("menu", "menu"),
    ("cart", "cart"),
    ("result", "result"),
)
TASK_FAMILY_HINTS = (
    ("auth", ("login", "log in", "sign in", "signin", "password", "register", "sign up", "signup")),
    ("checkout", ("checkout", "check out", "payment", "billing", "place order", "complete purchase")),
    ("cart", ("add to cart", "wishlist", "cart", "shopping bag", "bag")),
    ("flight", ("flight", "airline", "depart", "return", "round trip", "one way")),
    ("lodging", ("hotel", "homestay", "hostel", "room", "check in", "check-in", "check out", "check-out")),
    ("rental", ("rental", "rent", "pickup", "dropoff", "drop-off", "car hire")),
    ("reservation", ("reserve", "reservation", "booking", "book ")),
    ("filter_sort", ("filter", "sort", "refine")),
    ("profile", ("profile", "account", "settings", "edit profile", "update account")),
    ("search", ("search", "find", "look up", "locate", "browse", "show")),
)


def load_jsonl(path: str) -> List[dict]:
    rows: List[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def dump_jsonl(path: str, rows: Iterable[dict]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def dump_json(path: str, payload: object) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_url(value: str) -> str:
    if not value:
        return "<ROOT>"
    parsed = urlsplit(value)
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?<QUERY>"
    return path


def placeholder_for_value(value: str) -> str:
    normalized = normalize_whitespace(value)
    if not normalized:
        return "<EMPTY>"
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        return "<EMAIL>"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        return "<DATE>"
    if re.fullmatch(r"\d{1,2}:\d{2}", normalized):
        return "<TIME>"
    if re.fullmatch(r"\d+(\.\d+)?", normalized):
        return "<NUMBER>"
    return "<TEXT>"


def normalize_text_label(value: str) -> str:
    normalized = normalize_whitespace(value).lower()
    if not normalized:
        return ""
    if len(normalized) <= SHORT_TEXT_MAX_LEN and len(normalized.split()) <= SHORT_TEXT_MAX_WORDS:
        return normalized
    return placeholder_for_value(normalized)


def pick_first(row: dict, keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        string_value = str(value).strip()
        if string_value:
            return string_value
    return ""


def infer_slot_name(value: str, label: str) -> str:
    direct = placeholder_for_value(value).strip("<>")
    if direct not in {"TEXT", "EMPTY"}:
        return direct
    label_lower = normalize_text_label(label)
    for hint, slot_name in SLOT_HINTS.items():
        if hint in label_lower:
            return slot_name
    return ""


def coarse_role_name(value: str) -> str:
    normalized = normalize_text_label(value)
    if normalized in COARSE_ROLE_ALIASES:
        return COARSE_ROLE_ALIASES[normalized]
    if normalized in TEXTISH_ROLES:
        return "text"
    return normalized


def coarse_label_name(value: str) -> str:
    normalized = normalize_whitespace(value).lower()
    if not normalized:
        return ""
    for hint, coarse_name in COARSE_LABEL_HINTS:
        if hint in normalized:
            return coarse_name
    return "<TEXT>"


def normalize_canonicalization_mode(mode: str) -> str:
    normalized = str(mode or "signature").strip().lower()
    if normalized not in CANONICALIZATION_MODES:
        choices = ", ".join(CANONICALIZATION_MODES)
        raise ValueError(f"Unsupported canonicalization mode: {mode!r}. Expected one of: {choices}")
    return normalized


def infer_task_family(row_or_text: object) -> str:
    if isinstance(row_or_text, dict):
        parts = [
            str(row_or_text.get("task") or ""),
            str(row_or_text.get("confirmed_task") or ""),
            str(row_or_text.get("target_label") or ""),
            str(row_or_text.get("raw_action_repr") or ""),
        ]
        text = " ".join(part for part in parts if part)
    else:
        text = str(row_or_text or "")

    normalized = normalize_whitespace(text).lower()
    if not normalized:
        return "generic"
    # OttoAuth collection prompts often say "add to cart ... stop before checkout".
    # Those are cart workflows, not checkout workflows, even though they mention checkout.
    if (
        ("add to cart" in normalized or "to cart" in normalized)
        and (
            "stop before checkout" in normalized
            or "stop before check out" in normalized
            or "without checkout" in normalized
            or "without check out" in normalized
        )
    ):
        return "cart"
    for family, hints in TASK_FAMILY_HINTS:
        if any(hint in normalized for hint in hints):
            return family
    return "generic"


def group_value_for_row(row: dict, group_by: str) -> str:
    normalized = normalize_whitespace(str(group_by or "<all>")).lower()
    if not normalized or normalized in {"<all>", "all"}:
        return "<all>"
    if normalized == "task_family":
        return infer_task_family(row)
    if normalized in {"website_task_family", "site_task_family"}:
        website = str(row.get("website") or "<missing>")
        return f"{website}::{infer_task_family(row)}"
    if normalized == "domain_task_family":
        domain = str(row.get("domain") or "<missing>")
        return f"{domain}::{infer_task_family(row)}"
    return str(row.get(group_by) or "<missing>")


def group_rows(rows: Sequence[dict], group_by: str) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[group_value_for_row(row, group_by)].append(row)
    return grouped


def normalize_event_name(value: object) -> str:
    text = normalize_whitespace(str(value or "unknown"))
    if not text:
        return "UNKNOWN"
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text.upper() or "UNKNOWN"


def event_name(row: dict) -> str:
    for key in ("function_name", "tool_name", "action_name", "action_type"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return normalize_event_name(text)
    return "UNKNOWN"


def iter_scalar_values(value: object) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_scalar_values(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from iter_scalar_values(child)
        return
    text = str(value).strip()
    if text:
        yield text


def binding_key_for_value(value: object) -> str:
    normalized = normalize_whitespace(str(value))
    return normalized


def extract_input_literals(row: dict) -> List[str]:
    values: List[str] = []
    seen = set()
    for key in ARGUMENT_KEYS:
        if key not in row:
            continue
        for literal in iter_scalar_values(row.get(key)):
            binding_key = binding_key_for_value(literal)
            if not binding_key or binding_key in seen:
                continue
            values.append(literal)
            seen.add(binding_key)
    direct_value = pick_first(row, TEXT_KEYS)
    if direct_value:
        binding_key = binding_key_for_value(direct_value)
        if binding_key not in seen:
            values.append(direct_value)
            seen.add(binding_key)
    return values


def extract_output_literals(row: dict) -> List[str]:
    values: List[str] = []
    seen = set()
    for key in OUTPUT_KEYS:
        if key not in row:
            continue
        for literal in iter_scalar_values(row.get(key)):
            binding_key = binding_key_for_value(literal)
            if not binding_key or binding_key in seen:
                continue
            values.append(literal)
            seen.add(binding_key)
    if str(row.get("action_type", "")).strip().lower() == "copy":
        copied_value = pick_first(row, LABEL_KEYS)
        binding_key = binding_key_for_value(copied_value)
        if copied_value and binding_key not in seen:
            values.append(copied_value)
            seen.add(binding_key)
    return values


def canonicalize_event(row: dict, mode: str = "signature") -> dict:
    event = dict(row)
    mode = normalize_canonicalization_mode(mode)
    if mode in DATAFLOW_MODES:
        raise ValueError(
            f"{mode!r} is sequence-aware and must be rendered via represent_rows(), not canonicalize_event()."
        )
    action_type = str(event.get("action_type", "unknown")).strip().upper()
    raw_role = pick_first(event, ROLE_KEYS)
    raw_label = pick_first(event, LABEL_KEYS)
    role = normalize_text_label(raw_role)
    label = normalize_text_label(raw_label)
    selector = normalize_text_label(pick_first(event, SELECTOR_KEYS))
    slot = normalize_text_label(pick_first(event, SLOT_KEYS)).upper()
    value = pick_first(event, TEXT_KEYS)
    parts = [action_type]
    include_target = mode in {"coarse_signature", "target_signature", "signature"}
    include_value = mode in {"value_slots", "coarse_signature", "signature"}

    if action_type == "GOTO":
        if mode != "name_only":
            parts.append(f"url={normalize_url(str(event.get('url', '')))}")
    else:
        if include_target:
            if mode == "coarse_signature":
                role = coarse_role_name(raw_role)
                label = coarse_label_name(raw_label)
                selector = ""
            if role:
                parts.append(f"role={role}")
            if label:
                parts.append(f"label={label}")
            elif selector:
                parts.append(f"selector={selector}")
        if include_value and value:
            inferred_slot = slot or infer_slot_name(value, label)
            if inferred_slot:
                parts.append(f"value=<{inferred_slot}>")
            else:
                parts.append(f"value={placeholder_for_value(value)}")

    event["canonicalization_mode"] = mode
    event["canonical_action"] = "|".join(parts)
    return event


def next_binding_id(index: int) -> str:
    return f"B{index:02d}"


def annotate_dataflow_episode(rows: Sequence[dict], include_coarse_target: bool = False) -> List[dict]:
    value_to_binding: Dict[str, str] = {}
    binding_sources: Dict[str, str] = {}
    next_index = 1
    output_rows: List[dict] = []

    for row in sorted(rows, key=lambda item: int(item.get("step_index", 0))):
        event = dict(row)
        uses: List[str] = []
        defs: List[str] = []
        introduced: List[str] = []
        used_values: List[str] = []
        defined_values: List[str] = []

        for literal in extract_input_literals(event):
            binding_key = binding_key_for_value(literal)
            if not binding_key:
                continue
            binding_id = value_to_binding.get(binding_key)
            if not binding_id:
                binding_id = next_binding_id(next_index)
                next_index += 1
                value_to_binding[binding_key] = binding_id
                binding_sources[binding_id] = "input"
                introduced.append(binding_id)
            uses.append(binding_id)
            used_values.append(binding_key)

        for literal in extract_output_literals(event):
            binding_key = binding_key_for_value(literal)
            if not binding_key:
                continue
            binding_id = value_to_binding.get(binding_key)
            if not binding_id:
                binding_id = next_binding_id(next_index)
                next_index += 1
                value_to_binding[binding_key] = binding_id
                binding_sources[binding_id] = "output"
                introduced.append(binding_id)
            defs.append(binding_id)
            defined_values.append(binding_key)

        parts = [event_name(event)]
        if parts[0] == "GOTO":
            parts.append(f"url={normalize_url(str(event.get('url', '')))}")
        elif include_coarse_target:
            raw_role = pick_first(event, ROLE_KEYS)
            raw_label = pick_first(event, LABEL_KEYS)
            role = coarse_role_name(raw_role)
            label = coarse_label_name(raw_label)
            if role:
                parts.append(f"role={role}")
            if label:
                parts.append(f"label={label}")

        if uses:
            parts.append(f"use={','.join(uses)}")
        if defs:
            parts.append(f"def={','.join(defs)}")

        event["canonicalization_mode"] = "dataflow_coarse" if include_coarse_target else "dataflow"
        event["binding_uses"] = uses
        event["binding_defs"] = defs
        event["introduced_bindings"] = introduced
        event["binding_use_values"] = used_values
        event["binding_def_values"] = defined_values
        event["binding_sources"] = {
            binding_id: binding_sources[binding_id]
            for binding_id in uses + defs
            if binding_id in binding_sources
        }
        event["canonical_action"] = "|".join(parts)
        output_rows.append(event)

    return output_rows


def represent_rows(rows: Sequence[dict], mode: str = "signature") -> List[dict]:
    normalized_mode = normalize_canonicalization_mode(mode)
    if normalized_mode in EVENTWISE_MODES:
        return [canonicalize_event(row, mode=normalized_mode) for row in rows]

    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        episode_id = str(row.get("episode_id", "unknown"))
        grouped[episode_id].append(row)

    output_rows: List[dict] = []
    include_coarse_target = normalized_mode == "dataflow_coarse"
    for episode_id in sorted(grouped):
        output_rows.extend(
            annotate_dataflow_episode(
                grouped[episode_id],
                include_coarse_target=include_coarse_target,
            )
        )
    return output_rows


def group_sequences(rows: Iterable[dict]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for row in rows:
        episode_id = str(row.get("episode_id", "unknown"))
        step_index = int(row.get("step_index", 0))
        action = str(row.get("canonical_action", "")).strip()
        if action:
            grouped[episode_id].append((step_index, action))
    return {
        episode_id: [action for _, action in sorted(events)]
        for episode_id, events in grouped.items()
    }


def mine_frequent_chunks(
    sequences: Dict[str, List[str]],
    min_support: int = 2,
    max_chunk_len: int = 4,
    top_k: int = 50,
) -> List[dict]:
    support_sets: Dict[Tuple[str, ...], set] = defaultdict(set)
    occurrence_counts: Counter = Counter()

    for episode_id, sequence in sequences.items():
        for chunk_len in range(2, max_chunk_len + 1):
            if len(sequence) < chunk_len:
                continue
            seen_in_episode = set()
            for start in range(len(sequence) - chunk_len + 1):
                chunk = tuple(sequence[start : start + chunk_len])
                occurrence_counts[chunk] += 1
                seen_in_episode.add(chunk)
            for chunk in seen_in_episode:
                support_sets[chunk].add(episode_id)

    candidates = []
    for chunk, episodes in support_sets.items():
        support = len(episodes)
        if support < min_support:
            continue
        candidates.append(
            {
                "sequence": list(chunk),
                "length": len(chunk),
                "support": support,
                "occurrences": occurrence_counts[chunk],
            }
        )

    candidates.sort(
        key=lambda item: (
            -item["support"],
            -item["length"],
            -item["occurrences"],
            item["sequence"],
        )
    )

    trimmed = candidates[:top_k]
    for index, macro in enumerate(trimmed, start=1):
        macro["macro_id"] = f"M{index:03d}"
    return trimmed


def train_bpe_tokens(
    sequences: Dict[str, List[str]],
    num_merges: int = 25,
    min_occurrences: int = 2,
    min_support: int = 2,
) -> List[dict]:
    token_expansions = {}
    current = {episode_id: list(sequence) for episode_id, sequence in sequences.items()}
    merges: List[dict] = []

    def expansion(token: str) -> List[str]:
        return list(token_expansions.get(token, [token]))

    for merge_index in range(num_merges):
        pair_counts: Counter = Counter()
        pair_support: Dict[Tuple[str, str], set] = defaultdict(set)

        for episode_id, sequence in current.items():
            if len(sequence) < 2:
                continue
            seen_in_episode = set()
            for index in range(len(sequence) - 1):
                pair = (sequence[index], sequence[index + 1])
                pair_counts[pair] += 1
                seen_in_episode.add(pair)
            for pair in seen_in_episode:
                pair_support[pair].add(episode_id)

        if not pair_counts:
            break

        candidates = [
            (pair, occurrences)
            for pair, occurrences in pair_counts.items()
            if occurrences >= min_occurrences and len(pair_support[pair]) >= min_support
        ]
        if not candidates:
            break

        best_pair, occurrences = max(
            candidates,
            key=lambda item: (
                item[1],
                len(pair_support[item[0]]),
                len(expansion(item[0][0])) + len(expansion(item[0][1])),
                item[0],
            ),
        )

        left, right = best_pair
        token_id = f"BPE{merge_index + 1:03d}"
        token_expansions[token_id] = expansion(left) + expansion(right)

        merged_any = False
        next_current = {}
        for episode_id, sequence in current.items():
            merged_sequence: List[str] = []
            index = 0
            while index < len(sequence):
                if index < len(sequence) - 1 and sequence[index] == left and sequence[index + 1] == right:
                    merged_sequence.append(token_id)
                    index += 2
                    merged_any = True
                else:
                    merged_sequence.append(sequence[index])
                    index += 1
            next_current[episode_id] = merged_sequence

        if not merged_any:
            break

        current = next_current
        merges.append(
            {
                "token_id": token_id,
                "left": left,
                "right": right,
                "sequence": token_expansions[token_id],
                "length": len(token_expansions[token_id]),
                "occurrences": occurrences,
                "support": len(pair_support[best_pair]),
            }
        )

    return merges


def apply_bpe_tokens(sequences: Dict[str, List[str]], merges: Sequence[dict]) -> Dict[str, List[str]]:
    current = {episode_id: list(sequence) for episode_id, sequence in sequences.items()}
    for merge in merges:
        left = merge["left"]
        right = merge["right"]
        token_id = merge["token_id"]
        next_current = {}
        for episode_id, sequence in current.items():
            merged_sequence: List[str] = []
            index = 0
            while index < len(sequence):
                if index < len(sequence) - 1 and sequence[index] == left and sequence[index + 1] == right:
                    merged_sequence.append(token_id)
                    index += 2
                else:
                    merged_sequence.append(sequence[index])
                    index += 1
            next_current[episode_id] = merged_sequence
        current = next_current
    return current


def compress_sequence(sequence: Sequence[str], macros: Sequence[dict]) -> Tuple[List[str], Counter]:
    ordered_macros = sorted(
        macros,
        key=lambda macro: (-len(macro["sequence"]), -macro.get("support", 0), macro["macro_id"]),
    )
    compressed: List[str] = []
    hits: Counter = Counter()
    index = 0

    while index < len(sequence):
        matched = False
        for macro in ordered_macros:
            chunk = macro["sequence"]
            chunk_len = len(chunk)
            if list(sequence[index : index + chunk_len]) == list(chunk):
                compressed.append(f"MACRO:{macro['macro_id']}")
                hits[macro["macro_id"]] += 1
                index += chunk_len
                matched = True
                break
        if matched:
            continue
        compressed.append(sequence[index])
        index += 1

    return compressed, hits


def apply_macros(sequences: Dict[str, List[str]], macros: Sequence[dict]) -> Dict[str, List[str]]:
    return {
        episode_id: compress_sequence(sequence, macros)[0]
        for episode_id, sequence in sequences.items()
    }


def macro_has_binding(macro: dict) -> bool:
    return any("use=" in token or "def=" in token for token in macro.get("sequence", []))


def binding_ids_in_token(token: str, field: str) -> List[str]:
    prefix = f"{field}="
    for part in str(token).split("|"):
        if part.startswith(prefix):
            return [value for value in part[len(prefix) :].split(",") if value]
    return []


def macro_interface(macro: dict) -> dict:
    defined = set()
    input_bindings: List[str] = []
    local_bindings: List[str] = []

    for token in macro.get("sequence", []):
        for binding_id in binding_ids_in_token(token, "use"):
            if binding_id not in defined and binding_id not in input_bindings:
                input_bindings.append(binding_id)
        for binding_id in binding_ids_in_token(token, "def"):
            if binding_id not in defined:
                defined.add(binding_id)
                local_bindings.append(binding_id)

    return {
        "input_bindings": input_bindings,
        "local_bindings": local_bindings,
        "num_inputs": len(input_bindings),
        "num_local_bindings": len(local_bindings),
    }


def macro_usage_summary(sequences: Dict[str, List[str]], macros: Sequence[dict]) -> dict:
    macro_lookup = {macro["macro_id"]: macro for macro in macros}
    per_macro = {
        macro["macro_id"]: {
            "macro_id": macro["macro_id"],
            "length": len(macro.get("sequence", [])),
            "has_binding": macro_has_binding(macro),
            "macro_calls": 0,
            "episodes_with_hits": 0,
            "steps_saved": 0,
        }
        for macro in macros
    }

    for sequence in sequences.values():
        _, hits = compress_sequence(sequence, macros)
        for macro_id, count in hits.items():
            if macro_id not in per_macro:
                continue
            per_macro[macro_id]["macro_calls"] += count
            per_macro[macro_id]["episodes_with_hits"] += 1
            per_macro[macro_id]["steps_saved"] += (len(macro_lookup[macro_id]["sequence"]) - 1) * count

    items = sorted(
        per_macro.values(),
        key=lambda item: (-item["steps_saved"], -item["macro_calls"], item["macro_id"]),
    )
    return {
        "summary": {
            "macros_evaluated": len(items),
            "macro_calls": sum(item["macro_calls"] for item in items),
            "steps_saved": sum(item["steps_saved"] for item in items),
            "parameterized_macro_calls": sum(item["macro_calls"] for item in items if item["has_binding"]),
            "parameterized_steps_saved": sum(item["steps_saved"] for item in items if item["has_binding"]),
        },
        "macros": items,
    }


def compression_summary(sequences: Dict[str, List[str]], macros: Sequence[dict]) -> dict:
    episodes = []
    total_primitive = 0
    total_compressed = 0
    macro_hits: Counter = Counter()

    for episode_id, sequence in sorted(sequences.items()):
        compressed, hits = compress_sequence(sequence, macros)
        primitive_len = len(sequence)
        compressed_len = len(compressed)
        total_primitive += primitive_len
        total_compressed += compressed_len
        macro_hits.update(hits)
        episodes.append(
            {
                "episode_id": episode_id,
                "primitive_steps": primitive_len,
                "compressed_steps": compressed_len,
                "compression_ratio": round(compressed_len / primitive_len, 4) if primitive_len else 0.0,
                "macro_hits": dict(hits),
                "sequence": list(sequence),
                "compressed_sequence": compressed,
            }
        )

    return {
        "summary": {
            "episodes": len(episodes),
            "primitive_steps": total_primitive,
            "compressed_steps": total_compressed,
            "compression_ratio": round(total_compressed / total_primitive, 4) if total_primitive else 0.0,
            "episodes_with_macro_use": sum(1 for item in episodes if item["macro_hits"]),
        },
        "macro_hits": dict(macro_hits),
        "episodes": episodes,
    }


def summarize_macro_savings(
    sequences: Dict[str, List[str]],
    macros: Sequence[dict],
    decision_tokens_per_step: int = 50,
    decision_latency_ms: int = 1000,
) -> dict:
    compression = compression_summary(sequences, macros)
    macro_lookup = {macro["macro_id"]: macro for macro in macros}
    macro_hits = compression["macro_hits"]
    macro_calls = sum(macro_hits.values())
    weighted_span = sum(len(macro_lookup[macro_id]["sequence"]) * hits for macro_id, hits in macro_hits.items())
    parameterized_macro_calls = sum(
        hits for macro_id, hits in macro_hits.items() if macro_has_binding(macro_lookup[macro_id])
    )
    parameterized_steps_saved = sum(
        (len(macro_lookup[macro_id]["sequence"]) - 1) * hits
        for macro_id, hits in macro_hits.items()
        if macro_has_binding(macro_lookup[macro_id])
    )
    primitive_steps = compression["summary"]["primitive_steps"]
    compressed_steps = compression["summary"]["compressed_steps"]
    steps_saved = primitive_steps - compressed_steps

    return {
        "summary": {
            **compression["summary"],
            "macro_calls": macro_calls,
            "avg_macro_span": round(weighted_span / macro_calls, 4) if macro_calls else 0.0,
            "steps_saved": steps_saved,
            "decision_reduction_ratio": round(steps_saved / primitive_steps, 4) if primitive_steps else 0.0,
            "parameterized_macro_calls": parameterized_macro_calls,
            "parameterized_steps_saved": parameterized_steps_saved,
            "estimated_model_decisions_baseline": primitive_steps,
            "estimated_model_decisions_with_macros": compressed_steps,
            "estimated_model_decisions_saved": steps_saved,
            "estimated_output_tokens_saved": steps_saved * decision_tokens_per_step,
            "estimated_decision_latency_saved_ms": steps_saved * decision_latency_ms,
        },
        "macro_hits": macro_hits,
        "episodes": compression["episodes"],
    }


def bpe_summary(sequences: Dict[str, List[str]], merges: Sequence[dict]) -> dict:
    compressed_sequences = apply_bpe_tokens(sequences, merges)
    token_ids = {merge["token_id"] for merge in merges}
    token_hits: Counter = Counter()
    episodes = []
    total_primitive = 0
    total_compressed = 0

    for episode_id, sequence in sorted(sequences.items()):
        compressed = compressed_sequences.get(episode_id, [])
        hits = Counter(token for token in compressed if token in token_ids)
        token_hits.update(hits)
        primitive_len = len(sequence)
        compressed_len = len(compressed)
        total_primitive += primitive_len
        total_compressed += compressed_len
        episodes.append(
            {
                "episode_id": episode_id,
                "primitive_steps": primitive_len,
                "compressed_steps": compressed_len,
                "compression_ratio": round(compressed_len / primitive_len, 4) if primitive_len else 0.0,
                "token_hits": dict(hits),
                "sequence": list(sequence),
                "compressed_sequence": compressed,
            }
        )

    return {
        "summary": {
            "episodes": len(episodes),
            "primitive_steps": total_primitive,
            "compressed_steps": total_compressed,
            "compression_ratio": round(total_compressed / total_primitive, 4) if total_primitive else 0.0,
            "episodes_with_token_use": sum(1 for item in episodes if item["token_hits"]),
        },
        "token_hits": dict(token_hits),
        "episodes": episodes,
    }


def split_sequences(
    sequences: Dict[str, List[str]],
    train_ratio: float = 0.8,
    seed: int = 0,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    episode_ids = sorted(sequences)
    shuffled = list(episode_ids)
    random.Random(seed).shuffle(shuffled)
    if not shuffled:
        return {}, {}
    train_size = max(1, int(round(len(shuffled) * train_ratio)))
    if train_ratio < 1.0:
        train_size = min(train_size, len(shuffled) - 1) if len(shuffled) > 1 else 1
    train_ids = set(shuffled[:train_size])
    train = {episode_id: sequences[episode_id] for episode_id in episode_ids if episode_id in train_ids}
    test = {episode_id: sequences[episode_id] for episode_id in episode_ids if episode_id not in train_ids}
    return train, test


def build_next_token_cache(
    sequences: Dict[str, List[str]],
    context_len: int = 2,
) -> Dict[Tuple[str, ...], Counter]:
    cache: Dict[Tuple[str, ...], Counter] = defaultdict(Counter)
    for sequence in sequences.values():
        if len(sequence) <= context_len:
            continue
        for index in range(context_len, len(sequence)):
            context = tuple(sequence[index - context_len : index])
            next_token = sequence[index]
            cache[context][next_token] += 1
    return cache


def evaluate_next_token_cache(
    train_sequences: Dict[str, List[str]],
    eval_sequences: Dict[str, List[str]],
    context_len: int = 2,
) -> dict:
    cache = build_next_token_cache(train_sequences, context_len=context_len)
    total_positions = 0
    covered_positions = 0
    correct_positions = 0
    context_hits: Counter = Counter()
    context_correct: Counter = Counter()

    for sequence in eval_sequences.values():
        if len(sequence) <= context_len:
            continue
        for index in range(context_len, len(sequence)):
            total_positions += 1
            context = tuple(sequence[index - context_len : index])
            actual = sequence[index]
            if context not in cache:
                continue
            covered_positions += 1
            prediction = cache[context].most_common(1)[0][0]
            context_hits[context] += 1
            if prediction == actual:
                correct_positions += 1
                context_correct[context] += 1

    top_contexts = []
    for context, hits in context_hits.most_common(10):
        top_contexts.append(
            {
                "context": list(context),
                "hits": hits,
                "correct": context_correct[context],
            }
        )

    return {
        "context_len": context_len,
        "cached_contexts": len(cache),
        "total_positions": total_positions,
        "covered_positions": covered_positions,
        "correct_positions": correct_positions,
        "coverage": round(covered_positions / total_positions, 4) if total_positions else 0.0,
        "accuracy_on_covered": round(correct_positions / covered_positions, 4) if covered_positions else 0.0,
        "accuracy_overall": round(correct_positions / total_positions, 4) if total_positions else 0.0,
        "top_contexts": top_contexts,
    }


def evaluate_macro_replay(
    macros: Sequence[dict],
    eval_sequences: Dict[str, List[str]],
    trigger_prefix_len: int = 1,
) -> dict:
    per_macro = []
    exact_replay_episodes = set()
    parameterized_replay_episodes = set()
    total_candidates = 0
    total_exact = 0
    total_parameterized_candidates = 0
    total_parameterized_exact = 0

    for macro in macros:
        sequence = list(macro.get("sequence", []))
        if len(sequence) < 2:
            continue
        prefix_len = min(trigger_prefix_len, len(sequence) - 1)
        prefix = sequence[:prefix_len]
        has_binding = macro_has_binding(macro)
        candidate_triggers = 0
        exact_replays = 0
        replay_episodes = set()

        for episode_id, eval_sequence in eval_sequences.items():
            for index in range(len(eval_sequence) - prefix_len + 1):
                if eval_sequence[index : index + prefix_len] != prefix:
                    continue
                candidate_triggers += 1
                if eval_sequence[index : index + len(sequence)] == sequence:
                    exact_replays += 1
                    replay_episodes.add(episode_id)

        total_candidates += candidate_triggers
        total_exact += exact_replays
        if has_binding:
            total_parameterized_candidates += candidate_triggers
            total_parameterized_exact += exact_replays
            parameterized_replay_episodes.update(replay_episodes)
        exact_replay_episodes.update(replay_episodes)

        per_macro.append(
            {
                "macro_id": macro["macro_id"],
                "length": len(sequence),
                "support": macro.get("support", 0),
                "occurrences": macro.get("occurrences", 0),
                "has_binding": has_binding,
                "trigger_prefix_len": prefix_len,
                "candidate_triggers": candidate_triggers,
                "exact_replays": exact_replays,
                "replay_precision": round(exact_replays / candidate_triggers, 4) if candidate_triggers else 0.0,
                "episodes_with_exact_replay": len(replay_episodes),
                "sequence": sequence,
            }
        )

    per_macro.sort(
        key=lambda item: (
            -item["exact_replays"],
            -item["replay_precision"],
            -item["candidate_triggers"],
            item["macro_id"],
        )
    )

    parameterized_macros = [item for item in per_macro if item["has_binding"]]
    return {
        "summary": {
            "macros_evaluated": len(per_macro),
            "trigger_prefix_len": trigger_prefix_len,
            "candidate_triggers": total_candidates,
            "exact_replays": total_exact,
            "replay_precision": round(total_exact / total_candidates, 4) if total_candidates else 0.0,
            "episodes_with_exact_replay": len(exact_replay_episodes),
            "parameterized_macros_evaluated": len(parameterized_macros),
            "parameterized_candidate_triggers": total_parameterized_candidates,
            "parameterized_exact_replays": total_parameterized_exact,
            "parameterized_replay_precision": (
                round(total_parameterized_exact / total_parameterized_candidates, 4)
                if total_parameterized_candidates
                else 0.0
            ),
            "episodes_with_parameterized_exact_replay": len(parameterized_replay_episodes),
        },
        "macros": per_macro,
    }
