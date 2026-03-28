#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolcalltokenization.playwright_harness import (
    PlaywrightHarness,
    PlaywrightHarnessError,
    file_url,
    require_playwright,
    stringify_args,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one primitive or macro action from the exported action space inside Playwright."
    )
    parser.add_argument("--action-space", required=True, help="Path to the exported action-space JSON file.")
    parser.add_argument("--action", required=True, help="Action name to execute.")
    parser.add_argument("--start-url", default="", help="Optional page URL to open before executing the action.")
    parser.add_argument("--start-file", default="", help="Optional local HTML file to open before executing the action.")
    parser.add_argument("--arg", action="append", default=[], help="Action argument in KEY=VALUE form. Repeat as needed.")
    parser.add_argument("--trace", default="", help="Optional Playwright trace output path.")
    parser.add_argument("--headless", action="store_true", help="Run the browser headlessly.")
    parser.add_argument("--enforce-scope", action="store_true", help="Enforce the macro site precondition before execution.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sync_playwright = require_playwright()
    harness = PlaywrightHarness(args.action_space)
    arg_values = stringify_args(args.arg)
    start_url = args.start_url or (file_url(args.start_file) if args.start_file else "")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless)
        context = browser.new_context()
        if args.trace:
            context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        if start_url:
            page.goto(start_url)

        result = harness.execute_action(
            page,
            args.action,
            arg_values=arg_values,
            enforce_scope=args.enforce_scope,
        )

        if args.trace:
            context.tracing.stop(path=args.trace)
        browser.close()

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except PlaywrightHarnessError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
