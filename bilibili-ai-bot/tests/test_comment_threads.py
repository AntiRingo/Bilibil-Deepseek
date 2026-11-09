"""Offline continuity checks; imports no live bot config and never posts a comment."""
import ast
from datetime import datetime
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from comment_threads import merge_notifications, normalize_reply, read_thread_context
from conversation import CONVERSATION_PROMPT, COMMENT_CONTINUATION_PROMPT
import angelina_browsing


def comment(rpid, mid, text, parent=80, timestamp=1, root=80, oid=200):
    return {"rpid": rpid, "oid": oid, "root": root, "parent": parent, "ctime": timestamp,
            "member": {"mid": str(mid)}, "content": {"message": text}}


def load_functions(*names, **namespace):
    source = Path(__file__).resolve().parents[1] / "ai.py"
    nodes = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


class CommentThreadTests(unittest.TestCase):
    def setUp(self):
        self.reply = {"rpid": 104, "oid": 200, "thread_id": 80, "type": 1, "mid": "42",
                      "username": "博士", "content": "好呀，水下那段颜色好漂亮", "timestamp": 10,
                      "target_id": 102, "target_content": "要一起看看水下那段吗？",
                      "root_content": "@博士 蓝色的画面好漂亮，一起来看呀！"}
        self.root = comment(80, 99, self.reply["root_content"], root=0)
        self.root["replies"] = [comment(101, 42, "想看蓝色那段", timestamp=2),
                                comment(102, 99, self.reply["target_content"], timestamp=3),
                                comment(103, 88, "另一个观众的话", timestamp=4),
                                comment(104, 42, self.reply["content"], timestamp=10),
                                comment(105, 99, "这句来自未来", timestamp=11),
                                comment(106, 99, "别的视频评论", oid=999),
                                comment(107, 99, "别的楼层", root=900)]
        self.http = Mock()
        self.http.get.return_value.json.return_value = {"code": 0, "data": {"root": self.root}}

    def test_reply_normalization_and_merge_keep_quoted_parent(self):
        entry = {"reply_time": 10, "user": {"mid": 42, "nickname": "博士"}, "item": {
            "source_id": 104, "subject_id": 200, "root_id": 80, "target_id": 102,
            "business_id": 1, "source_content": self.reply["content"],
            "root_reply_content": self.reply["root_content"],
            "target_reply_content": self.reply["target_content"]}}
        reply = normalize_reply(entry)
        self.assertEqual(reply["target_content"], self.reply["target_content"])
        mention = {"rpid": 104, "thread_id": 104, "is_mention": True}
        merged = merge_notifications([mention], [reply, {**reply, "rpid": 110}])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["thread_id"], 80)
        self.assertEqual(merged[0]["root_content"], self.reply["root_content"])
        self.assertEqual(merged[0]["target_id"], 102)
        self.assertTrue(merged[0]["is_mention"])
        self.assertIsNone(normalize_reply({}))

    def test_context_keeps_real_root_parent_and_only_relevant_prior_turns(self):
        root, context = read_thread_context(self.reply, {}, 99, self.http)
        self.assertEqual(root, 80)
        for text in (self.reply["root_content"], self.reply["target_content"], "想看蓝色那段", "安洁莉娜"):
            self.assertIn(text, context)
        for text in ("另一个观众的话", "这句来自未来", "别的视频评论", "别的楼层", self.reply["content"]):
            self.assertNotIn(text, context)
        self.assertEqual(self.http.get.call_args.kwargs["params"]["root"], 80)

    def test_missing_thread_falls_back_to_notification_without_inventing_context(self):
        self.http.get.side_effect = requests.Timeout
        root, context = read_thread_context(self.reply, {}, 99, self.http)
        self.assertEqual(root, 80)
        self.assertIn(self.reply["target_content"], context)
        self.assertIn(self.reply["root_content"], context)
        self.assertIn("缺失的上下文不要补造", context)
        self.http.get.assert_called_once()

    def test_wrong_video_is_not_used_and_missing_root_is_resolved(self):
        self.root["oid"] = 999
        self.root["content"]["message"] = "不能串到这个视频"
        _, context = read_thread_context(self.reply, {}, 99, self.http)
        self.assertNotIn("不能串到这个视频", context)
        self.root["oid"] = 200
        self.http.get.side_effect = [
            Mock(json=lambda: {"code": 0, "data": {"root": comment(104, 42, "当前回复", root=80)}}),
            Mock(json=lambda: {"code": 0, "data": {"root": self.root}}),
        ]
        root, _ = read_thread_context({**self.reply, "thread_id": 104}, {}, 99, self.http)
        self.assertEqual(root, 80)
        self.assertEqual([call.kwargs["params"]["root"] for call in self.http.get.call_args_list[-2:]], [104, 80])

    def test_context_is_bounded(self):
        self.root["replies"] = [comment(200 + i, 42, f"第{i}轮", timestamp=2) for i in range(30)]
        _, context = read_thread_context(self.reply, {}, 99, self.http)
        data = json.loads(context.split("\n", 1)[1])
        self.assertEqual(len(data["同楼近期对话"]), 6)
        self.assertIn("第29轮", context)
        self.assertNotIn("第0轮", context)

    def prepare_namespace(self):
        state = {"data/video_memory.json": {}, "data/external_memory.json": {}}
        ns = load_functions("prepare_comment_context", get_raw_config=lambda: {"DEDE_USER_ID":99},
            read_thread_context=lambda *args: read_thread_context(*args, http=self.http), headers={},
            get_video_info=Mock(return_value={"bvid":"BVtest", "title":"蓝色水下", "desc":"人鱼相救"}),
            load_json=lambda path, default: state.get(path, default),
            save_json=lambda path, data: state.__setitem__(path, data),
            inspect_video=Mock(return_value="【实际视频抽帧分析，无音频】水中有人鱼和蓝色光影"),
            VIDEO_MEMORY_FILE="data/video_memory.json", datetime=datetime, json=json)
        return ns, state

    def test_first_reply_reads_video_and_followup_reuses_it_with_new_parent(self):
        ns, state = self.prepare_namespace()
        root, first = ns["prepare_comment_context"](self.reply)
        self.assertIn("水中有人鱼和蓝色光影", first)
        self.assertIn(self.reply["root_content"], first)
        self.root["replies"].append(comment(108, 99, "欸，你也挑中了蓝色那幕！", timestamp=9))
        followup = {**self.reply, "rpid":109, "target_id":108, "target_content":"欸，你也挑中了蓝色那幕！"}
        root, second = ns["prepare_comment_context"](followup)
        self.assertEqual(root, 80)
        self.assertIn("欸，你也挑中了蓝色那幕！", second)
        ns["inspect_video"].assert_called_once()
        self.assertEqual(state["data/video_memory.json"]["BVtest"]["source"], "frames")

    def test_shared_video_evidence_is_reused_but_cover_only_cache_is_not(self):
        ns, state = self.prepare_namespace()
        state["data/video_memory.json"]["BVtest"] = {"analysis":"封面猜测", "source":"metadata", "reaction":{"mood":"开心"}}
        state["data/external_memory.json"]["BVtest"] = {"description":"视频标题：蓝色水下。简介：人鱼相救"}
        ns["prepare_comment_context"](self.reply)
        ns["inspect_video"].assert_called_once()
        self.assertEqual(state["data/video_memory.json"]["BVtest"]["reaction"], {"mood":"开心"})
        ns["inspect_video"].reset_mock()
        state["data/video_memory.json"]["BVtest"] = {
            "source":"watched_excerpt", "analysis":"【无音轨】蓝色水下相救", "reaction":{"mood":"开心"}}
        _, context = ns["prepare_comment_context"](self.reply)
        self.assertIn("蓝色水下相救", context)
        self.assertIn("开心", context)
        self.assertNotIn("封面猜测", context)
        ns["inspect_video"].assert_not_called()

    def test_reply_generation_receives_full_context_and_lively_style(self):
        ns, _ = self.prepare_namespace()
        _, context = ns["prepare_comment_context"](self.reply)
        fake_config = ModuleType("config")
        fake_config.ENABLE_WEB_SEARCH = False
        chat = Mock(return_value=(json.dumps({"reply":"欸，你也挑中了蓝色那幕！水下的光一散开，确实很抓眼呀。"}), 1, 1))
        generation = load_functions("generate_reply_and_score", datetime=datetime, json=json,
            _get_level_prompts=lambda: {"special":"这是博士"}, get_today_mood=lambda: ("开心", ""),
            get_festival_prompt=lambda: "", _get_bot_info=lambda: {"bot_name":"安洁莉娜", "owner_name":"博士", "owner_bili":"博士账号"},
            _get_active_persona=lambda: {}, get_raw_config=lambda: {},
            angelina_life=SimpleNamespace(enabled=lambda:True, context=lambda:""),
            angelina_browsing=angelina_browsing, get_personality_prompt=lambda:"",
            CONVERSATION_PROMPT=CONVERSATION_PROMPT, COMMENT_CONTINUATION_PROMPT=COMMENT_CONTINUATION_PROMPT,
            claude_chat=chat, log_cost=Mock())
        with patch.dict("sys.modules", config=fake_config), patch.object(angelina_browsing.life, "enabled", return_value=True):
            result = generation["generate_reply_and_score"](self.reply["content"], "博士", "special", context)
        prompt = chat.call_args.args[0]
        self.assertIn(self.reply["root_content"], prompt)
        self.assertIn(self.reply["target_content"], prompt)
        self.assertIn(self.reply["content"], prompt)
        self.assertIn("活泼、开朗", prompt)
        self.assertIn("别再从头介绍视频", prompt)
        self.assertTrue(result[1].startswith("欸"))

    def test_continuation_sends_to_current_reply_in_original_thread(self):
        http = Mock()
        http.post.return_value.json.return_value = {"code":0}
        ns = load_functions("send_reply", requests=http, headers={}, BILI_JCT="offline")
        root, _ = read_thread_context(self.reply, {}, 99, self.http)
        self.assertTrue(ns["send_reply"](200, 104, 1, "欸，你也喜欢这一幕呀！", root_id=root))
        data = http.post.call_args.kwargs["data"]
        self.assertEqual((data["root"], data["parent"]), (80, 104))
        http.post.reset_mock()
        self.assertFalse(ns["send_reply"](200, 104, 1, "  ", root_id=root))
        http.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
