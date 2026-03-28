#!/usr/bin/env python3

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

try:
    from huggingface_hub import hf_hub_download
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "huggingface_hub is required. Install it with: python3 -m pip install --user huggingface_hub"
    ) from exc


WEBLINX_VALID_DEMO_IDS_30 = [
    "alxehej",
    "aopjpga",
    "aoxxcdg",
    "apfyesq",
    "aqahzgs",
    "ausjykw",
    "bapevgx",
    "bdfglfk",
    "bdhiwrz",
    "bessdxh",
    "bexvmyx",
    "bonfxww",
    "cdfkxtv",
    "cxtzcfw",
    "dpftfrs",
    "dvjohpf",
    "dvzglkv",
    "eaozdtr",
    "eiblold",
    "eivbwev",
    "ejryoez",
    "emwxcyh",
    "erjwhjk",
    "feupcgi",
    "fgauuld",
    "fquqaqa",
    "friuisw",
    "fxhsqxo",
    "fzcutlb",
    "gmhajlo",
]
MIND2WEB_TRAIN_FILES = [f"data/train/train_{index}.json" for index in range(11)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch the small public dataset slices used in this repo.")
    parser.add_argument("--all", action="store_true", help="Fetch the standard local bundle used by the current experiments.")
    parser.add_argument("--mind2web-train10", action="store_true", help="Fetch Mind2Web data/train/train_10.json.")
    parser.add_argument("--mind2web-all-train", action="store_true", help="Fetch all public Mind2Web training shards (train_0.json through train_10.json).")
    parser.add_argument("--weblinx-valid-chat", action="store_true", help="Fetch WebLINX data/chat/valid.json.gz.")
    parser.add_argument("--weblinx-browsergym-replays", type=int, default=0, help="Fetch replay.json, metadata.json, and form.json for the first N demo ids in the bundled replay list.")
    parser.add_argument("--weblinx-browsergym-full-demo", default="", help="Fetch and unzip one full BrowserGym demo zip by id, e.g. apfyesq.")
    return parser.parse_args()


def download_file(repo_id: str, filename: str, local_dir: str) -> str:
    path = hf_hub_download(
        repo_id=repo_id,
        repo_type="dataset",
        filename=filename,
        local_dir=local_dir,
    )
    print(path)
    return path


def fetch_mind2web_train10() -> None:
    download_file("osunlp/Mind2Web", "data/train/train_10.json", "data/local/mind2web")


def fetch_mind2web_all_train() -> None:
    for filename in MIND2WEB_TRAIN_FILES:
        download_file("osunlp/Mind2Web", filename, "data/local/mind2web")


def fetch_weblinx_valid_chat() -> None:
    download_file("McGill-NLP/WebLINX", "data/chat/valid.json.gz", "data/local")


def fetch_weblinx_browsergym_replays(count: int) -> None:
    demo_ids = WEBLINX_VALID_DEMO_IDS_30[:count]
    for demo_id in demo_ids:
        for filename in ("replay.json", "metadata.json", "form.json"):
            download_file(
                "McGill-NLP/weblinx-browsergym",
                f"demonstrations/{demo_id}/{filename}",
                "data/local/weblinx-browsergym",
            )


def fetch_weblinx_browsergym_full_demo(demo_id: str) -> None:
    zip_path = Path(
        download_file(
            "McGill-NLP/weblinx-browsergym",
            f"demonstrations_zip/{demo_id}.zip",
            "data/local/weblinx-browsergym",
        )
    )
    output_dir = Path("data/local/weblinx-browsergym") / f"full_demo_{demo_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(output_dir)
    print(output_dir)


def main() -> None:
    args = parse_args()

    if args.all:
        args.mind2web_train10 = True
        args.weblinx_valid_chat = True
        args.weblinx_browsergym_replays = max(args.weblinx_browsergym_replays, 30)
        if not args.weblinx_browsergym_full_demo:
            args.weblinx_browsergym_full_demo = "apfyesq"

    if args.mind2web_train10:
        fetch_mind2web_train10()
    if args.mind2web_all_train:
        fetch_mind2web_all_train()
    if args.weblinx_valid_chat:
        fetch_weblinx_valid_chat()
    if args.weblinx_browsergym_replays:
        fetch_weblinx_browsergym_replays(args.weblinx_browsergym_replays)
    if args.weblinx_browsergym_full_demo:
        fetch_weblinx_browsergym_full_demo(args.weblinx_browsergym_full_demo)


if __name__ == "__main__":
    main()
