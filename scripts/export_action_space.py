#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.action_space import (
    build_action_space,
    dump_action_space,
    load_registry,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a combined primitive-plus-macro browser action space from a promoted macro registry."
    )
    parser.add_argument("--registry", required=True, help="Path to a promoted macro registry JSON file.")
    parser.add_argument("--output", required=True, help="Path to the action-space JSON output.")
    parser.add_argument(
        "--omit-primitives",
        action="store_true",
        help="Only export promoted macros, without the primitive baseline actions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    registry_payload = load_registry(args.registry)
    action_space = build_action_space(
        registry_payload,
        include_primitives=not args.omit_primitives,
    )
    dump_action_space(args.output, action_space)


if __name__ == "__main__":
    main()
