# Data Notes

Tracked in git:

- `data/demo/` for tiny synthetic smoke-test traces

Ignored from git:

- `data/local/` for downloaded public datasets and local experiments

## Current public slices used by the repo

The current experiments use these local public slices:

- `Mind2Web` public training shards: `data/train/train_0.json` through `data/train/train_10.json`
- `WebLINX` processed validation chat split: `data/chat/valid.json.gz`
- `weblinx-browsergym` replay sample: 30 demos with `replay.json`, `metadata.json`, and `form.json`
- one full `weblinx-browsergym` demo zip unpacked locally for richer artifacts such as screenshots, DOM snapshots, and AX trees

## Fetch helper

Use:

```bash
python3 scripts/fetch_public_data.py --all
```

Or fetch pieces selectively:

```bash
python3 scripts/fetch_public_data.py --mind2web-train10
python3 scripts/fetch_public_data.py --mind2web-all-train
python3 scripts/fetch_public_data.py --weblinx-valid-chat
python3 scripts/fetch_public_data.py --weblinx-browsergym-replays 30
python3 scripts/fetch_public_data.py --weblinx-browsergym-full-demo apfyesq
```
