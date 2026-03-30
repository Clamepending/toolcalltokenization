import json
import tempfile
import unittest
from pathlib import Path

from toolcalltokenization.datasets import (
    convert_mind2web,
    convert_ottoauth_traces,
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

    def test_convert_ottoauth_traces(self) -> None:
        task_payload = {
            "schemaVersion": 1,
            "goal": "Go to https://www.amazon.com/ and search for MX Master 3S.",
            "sessionId": "session_1",
            "serverUrl": "http://localhost:3000",
            "deviceId": "browser-agent-1",
            "task": {
                "id": "mock_1",
                "type": "start_local_agent_goal",
                "url": None,
                "goal": "Go to https://www.amazon.com/ and search for MX Master 3S.",
                "taskPrompt": "Go to https://www.amazon.com/ and search for MX Master 3S.",
                "deviceId": "browser-agent-1",
                "createdAt": "2026-03-30T00:00:00Z",
            },
        }
        trace_payload = {
            "schemaVersion": 1,
            "taskId": "mock_1",
            "taskType": "start_local_agent_goal",
            "status": "completed",
            "events": [
                {
                    "timestamp": 1,
                    "type": "tool_use",
                    "payload": {
                        "toolUseId": "tool_1",
                        "name": "navigate",
                        "input": {"url": "https://www.amazon.com/", "tabId": 5},
                    },
                },
                {
                    "timestamp": 2,
                    "type": "tool_result",
                    "payload": {
                        "toolUseId": "tool_1",
                        "name": "navigate",
                        "durationMs": 123,
                        "text": "",
                        "imageCount": 1,
                    },
                },
                {
                    "timestamp": 3,
                    "type": "tool_use",
                    "payload": {
                        "toolUseId": "tool_2",
                        "name": "find",
                        "input": {"query": "search box", "tabId": 5},
                    },
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "2026-03-30" / "amazon.com" / "run_1"
            run_dir.mkdir(parents=True)
            (run_dir / "task.json").write_text(json.dumps(task_payload), encoding="utf-8")
            (run_dir / "trace.json").write_text(json.dumps(trace_payload), encoding="utf-8")
            rows = convert_ottoauth_traces(temp_dir)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["episode_id"], "mock_1")
        self.assertEqual(rows[0]["website"], "amazon.com")
        self.assertEqual(rows[0]["action_type"], "navigate")
        self.assertEqual(rows[0]["duration_ms"], 123)
        self.assertEqual(rows[1]["action_type"], "find")
        self.assertEqual(rows[1]["query"], "search box")


if __name__ == "__main__":
    unittest.main()
