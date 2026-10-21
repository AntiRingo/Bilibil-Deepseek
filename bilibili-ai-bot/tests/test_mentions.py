import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mentions import MentionClient, inspect_video, normalize_mention
from model_options import short_response_options


def entry(number=1, root=0):
    return {"id": number, "user": {"mid": 20, "nickname": "观众"}, "item": {
        "type": "reply", "business_id": 1, "source_id": number + 100,
        "subject_id": 200, "root_id": root, "source_content": "@小鲸 这段画面是什么？",
    }}


class MentionTests(unittest.TestCase):
    def test_short_response_options(self):
        self.assertEqual(short_response_options("deepseek-flash"),
                         {"extra_body": {"thinking": {"type": "disabled"}}})
        self.assertEqual(short_response_options("other-model"), {})

    def test_normalization_and_nonvideo_filter(self):
        self.assertEqual(normalize_mention(entry(), 99)["thread_id"], 101)
        self.assertEqual(normalize_mention(entry(root=80), 99)["thread_id"], 80)
        self.assertIsNone(normalize_mention(entry(), 20))
        dynamic = entry()
        dynamic["item"]["business_id"] = 11
        self.assertIsNone(normalize_mention(dynamic, 99))
        self.assertIsNone(normalize_mention({}, 99))

    def test_baseline_pending_restart_and_claim(self):
        http = Mock()
        def serve(items):
            http.get.return_value.json.return_value = {
                "code": 0, "data": {"items": items, "cursor": {"is_end": True}}
            }
        with tempfile.TemporaryDirectory() as directory:
            client = MentionClient(directory, http)
            serve([entry()])
            self.assertEqual(client.poll({}, 99), [])
            serve([entry(2), entry()])
            self.assertEqual([m["rpid"] for m in client.poll({}, 99)], [102])
            client = MentionClient(directory, http)
            self.assertEqual(len(client.poll({}, 99)), 1)
            client.claim(102)
            client = MentionClient(directory, http)
            self.assertEqual(client.poll({}, 99), [])

    def test_failed_initial_request_does_not_establish_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            http = Mock()
            http.get.return_value.json.return_value = {"code": -101}
            client = MentionClient(directory, http)
            with self.assertRaises(RuntimeError):
                client.poll({}, 99)
            self.assertFalse(client.state["initialized"])
            self.assertFalse(client.path.exists())

    def test_account_change_skips_history_and_old_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            http = Mock()
            http.get.return_value.json.return_value = {
                "code": 0, "data": {"items": [entry()], "cursor": {"is_end": True}}
            }
            client = MentionClient(directory, http)
            client.state.update({"initialized": True, "own_mid": "98", "pending": {"old": entry()}})
            self.assertEqual(client.poll({}, 99), [])
            self.assertEqual(client.state["own_mid"], "99")

    def test_cursor_pagination(self):
        with tempfile.TemporaryDirectory() as directory:
            http = Mock()
            client = MentionClient(directory, http)
            client.state["initialized"] = True
            http.get.side_effect = [
                Mock(json=lambda: {"code": 0, "data": {"items": [entry(3)],
                    "cursor": {"id": 3, "time": 456, "is_end": False}}}),
                Mock(json=lambda: {"code": 0, "data": {"items": [entry(2)],
                    "cursor": {"is_end": True}}}),
            ]
            self.assertEqual([m["rpid"] for m in client.poll({}, 99)], [102, 103])
            self.assertEqual(http.get.call_args.kwargs["params"], {"id": 3, "at_time": 456})

    @patch("mentions.subprocess.run", side_effect=FileNotFoundError)
    def test_failed_download_is_explicit(self, run):
        context = inspect_video({"bvid": "BVtest", "title": "标题"}, {}, "问题")
        self.assertIn("视频读取失败", context)
        self.assertIn("不得编造", context)
        cookie = Path(run.call_args.args[0][run.call_args.args[0].index("--cookies") + 1])
        self.assertFalse(cookie.parent.exists())

    @patch("mentions.OpenAI")
    @patch("mentions.subprocess.run")
    def test_real_frame_pipeline_and_question(self, run, client):
        folders = []
        def fake_run(command, **kwargs):
            if command[0] == "yt-dlp":
                self.assertTrue(command[command.index("-f") + 1].endswith("/worstvideo/worst"))
                output = command[command.index("-o") + 1].replace("%(ext)s", "mp4")
                Path(output).write_bytes(b"video")
                folders.append(Path(output).parent)
            elif command[0] == "ffprobe":
                return SimpleNamespace(stdout="80")
            else:
                Path(command[-1]).write_bytes(b"jpeg")
            return SimpleNamespace(returncode=0)
        run.side_effect = fake_run
        client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="画面里有一只鲸鱼"))])
        context = inspect_video({"bvid": "BVtest", "title": "标题"}, {
            "OR_VISION_KEY": "vision-key", "OR_VISION_URL": "https://vision.example/v1",
            "OR_VISION_MODEL": "vision",
        }, "鲸鱼在做什么？")
        self.assertIn("鲸鱼", context)
        self.assertIn("无音频", context)
        self.assertEqual(client.call_args.kwargs["api_key"], "vision-key")
        content = client.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(sum(c["type"] == "image_url" for c in content), 8)
        self.assertIn("鲸鱼在做什么", content[-1]["text"])
        self.assertFalse(folders[0].exists())

    def test_send_reply_preserves_root_and_parent(self):
        # Load only this function: importing ai.py initializes live config/schedules.
        source = Path(__file__).resolve().parents[1] / "ai.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "send_reply")
        http = Mock()
        http.post.return_value.json.return_value = {"code": 0}
        namespace = {"requests": http, "headers": {}, "BILI_JCT": "test"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.assertTrue(namespace["send_reply"](200, 102, 1, "回答", root_id=80))
        self.assertEqual(http.post.call_args.kwargs["data"]["root"], 80)
        self.assertEqual(http.post.call_args.kwargs["data"]["parent"], 102)


if __name__ == "__main__":
    unittest.main()
