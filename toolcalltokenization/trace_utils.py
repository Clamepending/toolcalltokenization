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
CANONICALIZATION_MODES = (
    "name_only",
    "value_slots",
    "coarse_signature",
    "target_signature",
    "signature",
)
TEXT_KEYS = ("value", "text", "query", "search", "input")
LABEL_KEYS = ("target_text", "target_label", "label", "name")
ROLE_KEYS = ("target_role", "role")
SELECTOR_KEYS = ("selector", "target_selector")
SLOT_KEYS = ("slot", "value_slot")
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


def canonicalize_event(row: dict, mode: str = "signature") -> dict:
    event = dict(row)
    mode = normalize_canonicalization_mode(mode)
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
