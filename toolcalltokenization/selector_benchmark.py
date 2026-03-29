from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlsplit
import random
import re

from .trace_utils import group_rows, group_sequences, represent_rows, split_sequences


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
GENERIC_LABELS = {"", "<text>", "field", "input", "item", "choice", "dropdown", "list", "submit"}
ROLE_ALIASES = {
    "a": "link",
    "button": "button",
    "checkbox": "choice",
    "combobox": "select",
    "input": "input",
    "label": "choice",
    "link": "link",
    "listitem": "choice",
    "option": "choice",
    "radio": "choice",
    "searchbox": "input",
    "select": "select",
    "span": "text",
    "tab": "tab",
    "textarea": "input",
    "textbox": "input",
}


def normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text)


def normalize_role(value: object) -> str:
    role = normalize_text(value)
    return ROLE_ALIASES.get(role, role)


def normalize_url_path(value: object) -> str:
    parsed = urlsplit(str(value or ""))
    path = parsed.path or "/"
    return re.sub(r"\d+", "<num>", path.lower())


def text_tokens(text: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(text).lower())
        if token and token not in TOKEN_STOPWORDS
    }


def label_tokens(value: object) -> set[str]:
    label = normalize_text(value)
    if label in GENERIC_LABELS:
        return set()
    return {token for token in re.findall(r"[a-z0-9]+", label) if token}


def macro_runtime_id(macro: dict) -> str:
    suggested_name = str(macro.get("suggested_name", "")).strip()
    if suggested_name:
        return suggested_name
    group_key = str(macro.get("group_key", "<all>")).strip() or "<all>"
    macro_id = str(macro.get("macro_id", "macro")).strip() or "macro"
    return f"{group_key}::{macro_id}"


def primitive_action_name(row: dict) -> str:
    action = normalize_text(row.get("action_name") or row.get("action_type") or "action") or "action"
    label = normalize_text(row.get("target_label"))
    role = normalize_role(row.get("target_role"))
    target = label or role or "element"
    target = re.sub(r"[^a-z0-9]+", "_", target).strip("_") or "element"
    return f"{action}_{target}"


def primitive_action_description(row: dict) -> str:
    action = normalize_text(row.get("action_name") or row.get("action_type") or "act")
    label = normalize_text(row.get("target_label"))
    role = normalize_role(row.get("target_role"))
    target = label or role or "element"
    if action in {"type", "fill", "paste"}:
        return f"Type the requested value into the {target}."
    if action == "select":
        return f"Choose the requested value from the {target}."
    if action == "goto":
        return "Navigate to the requested page."
    return f"Click the {target}."


def row_context_text(row: dict, previous_actions: Sequence[str]) -> str:
    parts = [
        str(row.get("task") or row.get("confirmed_task") or ""),
        str(row.get("target_role") or ""),
        str(row.get("target_label") or ""),
        str(row.get("raw_action_repr") or ""),
        normalize_url_path(row.get("url")),
        " ".join(previous_actions[-2:]),
    ]
    return " ".join(part for part in parts if part)


def step_phrase(template: dict) -> str:
    kind = normalize_text(template.get("kind"))
    role = normalize_role(template.get("target_role"))
    label = normalize_text(template.get("target_label"))
    target = label or role or "element"
    if kind in {"fill", "type", "paste"}:
        return f"type {target}"
    if kind == "select":
        return f"choose {target}"
    if kind == "goto":
        return "navigate"
    return f"click {target}"


def macro_text(macro: dict) -> str:
    pieces = [
        str(macro.get("suggested_name", "")),
        str(macro.get("suggested_description", "")),
        " ".join(step_phrase(template) for template in macro.get("step_templates", [])[:3]),
        " ".join(str(token) for token in macro.get("sequence", [])[:3]),
    ]
    return " ".join(part for part in pieces if part)


def macro_start_compatible(row: dict, macro: dict) -> bool:
    templates = list(macro.get("step_templates", []))
    if not templates:
        return False
    start = templates[0]
    row_kind = normalize_text(row.get("action_name") or row.get("action_type"))
    step_kind = normalize_text(start.get("kind"))
    if row_kind and step_kind and row_kind != step_kind:
        return False

    row_role = normalize_role(row.get("target_role"))
    step_role = normalize_role(start.get("target_role"))
    if row_role and step_role and row_role != step_role:
        return False

    row_label = label_tokens(row.get("target_label"))
    step_label = label_tokens(start.get("target_label"))
    if row_label and step_label and not (row_label & step_label):
        return False
    return True


def semantic_score(
    *,
    goal_tokens: set[str],
    context_tokens: set[str],
    action_tokens: set[str],
    is_macro: bool,
    length: int,
) -> float:
    score = 3.0 * len(goal_tokens & action_tokens)
    score += 1.25 * len(context_tokens & action_tokens)
    if is_macro:
        score += 0.35 * max(length - 1, 0)
    return score


def candidate_set(
    *,
    row: dict,
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    use_start_step_guard: bool,
) -> List[dict]:
    action_name = primitive_action_name(row)
    action_description = primitive_action_description(row)
    candidates = [
        {
            "kind": "primitive",
            "id": "__primitive__",
            "name": action_name,
            "description": action_description,
            "length": 1,
            "tokens": text_tokens(f"{action_name} {action_description} {row.get('target_role', '')} {row.get('target_label', '')}"),
        }
    ]
    blocked_ids = {str(macro_id) for macro_id in blocked_macro_ids}
    for macro in macros:
        macro_id = macro_runtime_id(macro)
        if macro_id in blocked_ids:
            continue
        if use_start_step_guard and not macro_start_compatible(row, macro):
            continue
        candidates.append(
            {
                "kind": "macro",
                "id": macro_id,
                "name": str(macro.get("suggested_name", "")),
                "description": str(macro.get("suggested_description", "")),
                "length": len(macro.get("sequence", [])),
                "tokens": text_tokens(macro_text(macro)),
                "macro": macro,
            }
        )
    return candidates


def candidate_features(
    *,
    goal_tokens: set[str],
    context_tokens: set[str],
    row: dict,
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
    for token in sorted(context_tokens & action_tokens):
        features[f"context_overlap:{token}"] = 1.0
    for token in sorted(action_tokens):
        features[f"action_token:{token}"] = features.get(f"action_token:{token}", 0.0) + 0.15

    row_kind = normalize_text(row.get("action_name") or row.get("action_type")) or "action"
    row_role = normalize_role(row.get("target_role")) or "element"
    row_label = normalize_text(row.get("target_label")) or row_role
    features[f"row_kind:{row_kind}"] = 1.0
    features[f"row_role:{row_role}"] = 1.0
    features[f"row_label:{row_label}"] = 1.0

    if candidate["kind"] == "primitive":
        features["primitive_bias"] = 1.0
        return features

    macro = dict(candidate["macro"])
    features["macro_bias"] = 1.0
    features["macro_length"] = float(candidate["length"])
    features[f"macro_name:{candidate['name']}"] = 1.0
    features["macro_replay_precision"] = float(macro.get("replay_precision", 0.0))
    start = list(macro.get("step_templates", []))
    if not start:
        return features
    first = start[0]
    step_kind = normalize_text(first.get("kind"))
    step_role = normalize_role(first.get("target_role"))
    if row_kind and step_kind and row_kind == step_kind:
        features["start_kind_match"] = 1.0
    if row_role and step_role and row_role == step_role:
        features[f"start_role_match:{step_role}"] = 1.0
    for token in sorted(label_tokens(row.get("target_label")) & label_tokens(first.get("target_label"))):
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


def macro_sort_key(macro: dict) -> Tuple:
    return (
        -float(macro.get("replay_precision", 0.0)),
        -len(macro.get("sequence", [])),
        -int(macro.get("support", 0)),
        str(macro_runtime_id(macro)),
    )


def choose_oracle_macro(
    remaining_sequence: Sequence[str],
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
) -> dict | None:
    blocked_ids = {str(macro_id) for macro_id in blocked_macro_ids}
    candidates = []
    for macro in macros:
        if macro_runtime_id(macro) in blocked_ids:
            continue
        sequence = list(macro.get("sequence", []))
        if not sequence:
            continue
        if list(remaining_sequence[: len(sequence)]) != sequence:
            continue
        candidates.append(macro)
    if not candidates:
        return None
    candidates.sort(key=macro_sort_key)
    return candidates[0]


def replay_rows_by_episode(rows: Sequence[dict], canonicalization_mode: str) -> Dict[str, List[dict]]:
    represented = represent_rows(rows, mode=canonicalization_mode)
    original_by_episode: Dict[str, List[dict]] = defaultdict(list)
    represented_by_episode: Dict[str, List[dict]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (str(item.get("episode_id", "")), int(item.get("step_index", 0)))):
        original_by_episode[str(row.get("episode_id", "unknown"))].append(dict(row))
    for row in sorted(represented, key=lambda item: (str(item.get("episode_id", "")), int(item.get("step_index", 0)))):
        represented_by_episode[str(row.get("episode_id", "unknown"))].append(dict(row))
    merged: Dict[str, List[dict]] = {}
    for episode_id, originals in original_by_episode.items():
        represented_rows = represented_by_episode.get(episode_id, [])
        merged_rows: List[dict] = []
        for index, row in enumerate(originals):
            merged_row = dict(row)
            if index < len(represented_rows):
                represented_row = represented_rows[index]
                merged_row["canonical_action"] = represented_row.get("canonical_action", "")
            else:
                merged_row["canonical_action"] = ""
            merged_rows.append(merged_row)
        merged[episode_id] = merged_rows
    return merged


def split_train_eval_episode_ids(
    rows: Sequence[dict],
    *,
    group_by: str,
    canonicalization_mode: str,
    train_ratio: float,
    split_seed: int,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    grouped_rows = group_rows(rows, group_by)
    train_ids: Dict[str, List[str]] = {}
    eval_ids: Dict[str, List[str]] = {}
    for group_key, group in grouped_rows.items():
        represented_rows = represent_rows(group, mode=canonicalization_mode)
        sequences = group_sequences(represented_rows)
        train_sequences, eval_sequences = split_sequences(sequences, train_ratio=train_ratio, seed=split_seed)
        if not train_sequences:
            train_sequences = sequences
        if not eval_sequences:
            eval_sequences = sequences
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


def gold_choice_id(
    *,
    remaining_sequence: Sequence[str],
    macros: Sequence[dict],
) -> str:
    macro = choose_oracle_macro(remaining_sequence, macros, ())
    if macro is None:
        return "__primitive__"
    return macro_runtime_id(macro)


def collect_selector_examples(
    rows: Sequence[dict],
    registry_payload: dict,
    *,
    episode_ids_by_group: Dict[str, List[str]],
    group_by: str,
    canonicalization_mode: str,
    action_scope: str,
    use_start_step_guard: bool,
) -> List[dict]:
    replay_by_episode = replay_rows_by_episode(rows, canonicalization_mode)
    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)

    examples: List[dict] = []
    for group_key, episode_ids in sorted(episode_ids_by_group.items()):
        macros = action_space_macros(
            group_key=group_key,
            registry_by_group=registry_by_group,
            all_macros=all_macros,
            action_scope=action_scope,
        )
        for episode_id in episode_ids:
            rows_for_episode = replay_by_episode.get(episode_id, [])
            sequence = [str(row.get("canonical_action", "")) for row in rows_for_episode]
            previous_actions: List[str] = []
            for index, row in enumerate(rows_for_episode):
                candidates = candidate_set(
                    row=row,
                    macros=macros,
                    blocked_macro_ids=[],
                    use_start_step_guard=use_start_step_guard,
                )
                candidate_ids = {candidate["id"] for candidate in candidates}
                gold_id = gold_choice_id(
                    remaining_sequence=sequence[index:],
                    macros=[candidate["macro"] for candidate in candidates if candidate["kind"] == "macro"],
                )
                if gold_id not in candidate_ids:
                    gold_id = "__primitive__"
                examples.append(
                    {
                        "episode_id": str(episode_id),
                        "group_key": str(group_key),
                        "goal": str(row.get("task") or row.get("confirmed_task") or ""),
                        "context_text": row_context_text(row, previous_actions),
                        "row": dict(row),
                        "candidates": candidates,
                        "gold_id": gold_id,
                    }
                )
                previous_actions.append(sequence[index])
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
            goal_tokens = text_tokens(example["goal"])
            context_tokens = text_tokens(example["context_text"])
            feature_map = {
                candidate["id"]: candidate_features(
                    goal_tokens=goal_tokens,
                    context_tokens=context_tokens,
                    row=dict(example["row"]),
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


def semantic_choice(
    *,
    row: dict,
    previous_actions: Sequence[str],
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    margin: float,
    use_start_step_guard: bool,
) -> dict:
    candidates = candidate_set(
        row=row,
        macros=macros,
        blocked_macro_ids=blocked_macro_ids,
        use_start_step_guard=use_start_step_guard,
    )
    goal_tokens = text_tokens(row.get("task") or row.get("confirmed_task") or "")
    context_tokens = text_tokens(row_context_text(row, previous_actions))
    scored: List[Tuple[float, dict]] = []
    for candidate in candidates:
        score = semantic_score(
            goal_tokens=goal_tokens,
            context_tokens=context_tokens,
            action_tokens=set(candidate.get("tokens", set())),
            is_macro=candidate["kind"] == "macro",
            length=int(candidate["length"]),
        )
        scored.append((score, candidate))
    scored.sort(key=lambda item: (item[0], item[1]["kind"] == "macro", item[1]["id"]), reverse=True)
    primitive_score = next(score for score, candidate in scored if candidate["kind"] == "primitive")
    best_score, best = scored[0]
    if best["kind"] == "primitive" or best_score < primitive_score + margin:
        return {"kind": "primitive", "score": primitive_score}
    return {"kind": "macro", "score": best_score, "macro": best["macro"], "macro_id": best["id"], "primitive_score": primitive_score}


def learned_choice(
    *,
    model: dict,
    row: dict,
    previous_actions: Sequence[str],
    macros: Sequence[dict],
    blocked_macro_ids: Sequence[str],
    use_start_step_guard: bool,
) -> dict:
    candidates = candidate_set(
        row=row,
        macros=macros,
        blocked_macro_ids=blocked_macro_ids,
        use_start_step_guard=use_start_step_guard,
    )
    goal_tokens = text_tokens(row.get("task") or row.get("confirmed_task") or "")
    context_tokens = text_tokens(row_context_text(row, previous_actions))
    weights = dict(model.get("weights", {}))
    scored: List[Tuple[float, dict]] = []
    for candidate in candidates:
        features = candidate_features(
            goal_tokens=goal_tokens,
            context_tokens=context_tokens,
            row=row,
            candidate=candidate,
        )
        scored.append((score_linear(weights, features), candidate))
    scored.sort(key=lambda item: (item[0], item[1]["kind"] == "macro", item[1]["id"]), reverse=True)
    best_score, best = scored[0]
    if best["kind"] == "primitive":
        return {"kind": "primitive", "score": best_score}
    return {"kind": "macro", "score": best_score, "macro": best["macro"], "macro_id": best["id"]}


def evaluate_selector_replay(
    rows: Sequence[dict],
    registry_payload: dict,
    *,
    group_by: str,
    canonicalization_mode: str,
    train_ratio: float = 0.8,
    split_seed: int = 0,
    action_scope: str = "task",
    policy_mode: str = "semantic",
    margin: float = 0.0,
    use_start_step_guard: bool = True,
    training_epochs: int = 8,
    training_seed: int = 0,
) -> dict:
    train_ids_by_group, eval_ids_by_group = split_train_eval_episode_ids(
        rows,
        group_by=group_by,
        canonicalization_mode=canonicalization_mode,
        train_ratio=train_ratio,
        split_seed=split_seed,
    )
    replay_by_episode = replay_rows_by_episode(rows, canonicalization_mode)
    registry_by_group: Dict[str, List[dict]] = defaultdict(list)
    for entry in registry_payload.get("registry", []):
        registry_by_group[str(entry.get("group_key", "<all>"))].append(entry)
    all_macros = sorted(list(registry_payload.get("registry", [])), key=macro_sort_key)

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

    total_primitive_steps = 0
    total_agent_decisions = 0
    total_attempted_macro_calls = 0
    total_successful_macro_calls = 0
    total_failed_macro_calls = 0
    total_covered_steps = 0
    total_episodes = 0
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
            rows_for_episode = replay_by_episode.get(episode_id, [])
            if not rows_for_episode:
                continue
            sequence = [str(row.get("canonical_action", "")) for row in rows_for_episode]
            if macros:
                total_covered_steps += len(sequence)
            index = 0
            agent_decisions = 0
            attempted_macro_calls = 0
            successful_macro_calls = 0
            failed_macro_calls = 0
            episode_macro_hits: Counter = Counter()
            blocked_macros_by_index: Dict[int, set[str]] = defaultdict(set)
            previous_actions: List[str] = []
            choice_trace: List[dict] = []

            while index < len(rows_for_episode):
                row = rows_for_episode[index]
                if policy_mode == "oracle":
                    macro = choose_oracle_macro(sequence[index:], macros, blocked_macros_by_index[index])
                    choice = {"kind": "macro", "macro": macro, "macro_id": macro_runtime_id(macro)} if macro else {"kind": "primitive"}
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
                else:
                    raise ValueError(f"Unsupported policy_mode: {policy_mode!r}")

                if choice["kind"] == "macro":
                    macro = dict(choice["macro"])
                    macro_id = str(choice["macro_id"])
                    span = len(macro.get("sequence", []))
                    attempted_macro_calls += 1
                    agent_decisions += 1
                    current_sequence = list(sequence[index : index + span])
                    choice_trace.append(
                        {
                            "index": index,
                            "choice": "macro",
                            "macro_id": macro_id,
                            "score": round(float(choice.get("score", 0.0)), 3),
                        }
                    )
                    if current_sequence != list(macro.get("sequence", [])):
                        failed_macro_calls += 1
                        blocked_macros_by_index[index].add(macro_id)
                        continue
                    successful_macro_calls += 1
                    episode_macro_hits[macro_id] += 1
                    previous_actions.extend(sequence[index : index + span])
                    index += span
                    continue

                agent_decisions += 1
                choice_trace.append({"index": index, "choice": "primitive"})
                previous_actions.append(sequence[index])
                index += 1

            primitive_steps = len(rows_for_episode)
            total_primitive_steps += primitive_steps
            total_agent_decisions += agent_decisions
            total_attempted_macro_calls += attempted_macro_calls
            total_successful_macro_calls += successful_macro_calls
            total_failed_macro_calls += failed_macro_calls
            total_episodes += 1
            macro_hits.update(episode_macro_hits)
            group_reports.append(
                {
                    "episode_id": episode_id,
                    "primitive_steps": primitive_steps,
                    "agent_decisions": agent_decisions,
                    "steps_saved": primitive_steps - agent_decisions,
                    "attempted_macro_calls": attempted_macro_calls,
                    "successful_macro_calls": successful_macro_calls,
                    "failed_macro_calls": failed_macro_calls,
                    "macro_hits": dict(episode_macro_hits),
                    "choice_trace": choice_trace,
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
                    "primitive_steps": primitive_group_steps,
                    "agent_decisions": agent_group_steps,
                    "steps_saved": primitive_group_steps - agent_group_steps,
                    "decision_reduction_ratio": round((primitive_group_steps - agent_group_steps) / primitive_group_steps, 4)
                    if primitive_group_steps
                    else 0.0,
                    "attempted_macro_calls": sum(item["attempted_macro_calls"] for item in group_reports),
                    "successful_macro_calls": sum(item["successful_macro_calls"] for item in group_reports),
                    "failed_macro_calls": sum(item["failed_macro_calls"] for item in group_reports),
                },
            }
        )

    coverage_ratio = round(total_covered_steps / total_primitive_steps, 4) if total_primitive_steps else 0.0
    summary = {
        "policy_mode": policy_mode,
        "action_scope": action_scope,
        "episodes": total_episodes,
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
        "covered_primitive_steps": total_covered_steps,
        "coverage_ratio": coverage_ratio,
        "macro_hits": dict(macro_hits),
    }
    if model is not None:
        summary["model"] = {
            "model_type": model.get("model_type"),
            "epochs": model.get("epochs"),
            "training_examples": model.get("examples"),
            "updates": model.get("updates"),
            "nonzero_weights": len(model.get("weights", {})),
        }
    return {"summary": summary, "groups": groups}
