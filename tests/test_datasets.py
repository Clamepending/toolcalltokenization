import json
import tempfile
import unittest
from pathlib import Path

from toolcalltokenization.datasets import (
    convert_mind2web,
    convert_weblinx_chat,
    convert_weblinx_replay,
    convert_wonderbread_trace,
)


class DatasetConvertersTest(unittest.TestCase):
    def test_convert_mind2web(self) -> None:
        payload = [
            {
                "annotation_id": "ann-1",
                "website": "example",
                "domain": "travel",
                "subdomain": "search",
                "confirmed_task": "Search for flights",
                "action_reprs": ["Click search"],
                "actions": [
                    {
                        "operation": {"op": "CLICK", "original_op": "CLICK"},
                        "pos_candidates": [
                            {
                                "tag": "button",
                                "is_original_target": True,
                                "backend_node_id": "42",
                                "attributes": json.dumps({"aria-label": "Search"}),
                            }
                        ],
                    }
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            rows = convert_mind2web(str(path))

        self.assertEqual(rows[0]["episode_id"], "ann-1")
        self.assertEqual(rows[0]["action_type"], "click")
        self.assertEqual(rows[0]["target_label"], "Search")

    def test_convert_weblinx_replay(self) -> None:
        payload = {
            "data": [
                {
                    "type": "browser",
                    "action": {
                        "intent": "textInput",
                        "arguments": {
                            "text": "hello",
                            "metadata": {"url": "https://example.com"},
                            "element": {
                                "tagName": "input",
                                "textContent": "",
                                "xpath": "/html/body/input",
                                "attributes": {"placeholder": "Search"},
                            },
                        },
                    },
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            demo_dir = Path(temp_dir) / "demo-1"
            demo_dir.mkdir()
            path = demo_dir / "replay.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            rows = convert_weblinx_replay(str(demo_dir))

        self.assertEqual(rows[0]["episode_id"], "demo-1")
        self.assertEqual(rows[0]["action_type"], "type")
        self.assertEqual(rows[0]["url"], "https://example.com")
        self.assertEqual(rows[0]["target_label"], "Search")
        self.assertEqual(rows[0]["selector"], "/html/body/input")

    def test_convert_wonderbread_trace(self) -> None:
        payload = {
            "trace": [
                {"type": "state", "data": {"url": "https://example.com/search", "step": 0}},
                {
                    "type": "action",
                    "data": {
                        "type": "mouseup",
                        "x": 10,
                        "y": 20,
                        "element_attributes": {
                            "element": {"tag": "button", "text": "Search", "xpath": "/html/body/button"}
                        },
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            demo_dir = Path(temp_dir) / "demo-2"
            demo_dir.mkdir()
            path = demo_dir / "trace.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            rows = convert_wonderbread_trace(str(demo_dir))

        self.assertEqual(rows[0]["episode_id"], "demo-2")
        self.assertEqual(rows[0]["action_type"], "click")
        self.assertEqual(rows[0]["url"], "https://example.com/search")

    def test_convert_weblinx_chat(self) -> None:
        lines = [
            {
                "demo": "demo-chat",
                "turn": 2,
                "action": 'load(url="https://example.com")',
                "candidates": "",
            },
            {
                "demo": "demo-chat",
                "turn": 4,
                "action": 'text_input(text="hello", uid="abc")',
                "candidates": "(uid = abc) [[tag]] input [[xpath]] /html/body/input [[attributes]] name='Email' value=''",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "valid.json.gz"
            import gzip

            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for row in lines:
                    handle.write(json.dumps(row) + "\n")
            rows = convert_weblinx_chat(str(path))

        self.assertEqual([row["action_type"] for row in rows], ["goto", "type"])
        self.assertEqual(rows[1]["selector"], "abc")
        self.assertEqual(rows[1]["target_role"], "input")
        self.assertEqual(rows[1]["target_label"], "Email")


if __name__ == "__main__":
    unittest.main()
