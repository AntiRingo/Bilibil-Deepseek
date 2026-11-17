"""Offline identity filtering and reply pipeline checks."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock

from identity_policy import should_ignore_identity, identity_instruction
from persona_storage import bind_persona, release_persona
from test_conversation import ConversationTests


class IdentityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.token = bind_persona("angelina")

    def tearDown(self):
        release_persona(self.token)

    def test_identity_variants(self):
        for text in ("你是不是AI？", "是不是AI", "你是机器人吗", "你的真实身份是什么？",
                     "真实身份是什么", "你到底是谁", "你是真人吗", "你用的是什么模型",
                     "@安洁莉娜 你是ＡＩ吗", "你是a\u200bi吗", "Are you an AI?",
                     "What is your real identity?", "今天好吗？\n你是AI吗？"):
            with self.subTest(text=text):
                self.assertTrue(should_ignore_identity(text))

    def test_regular_conversations_and_other_personas(self):
        for text in ("AI绘画是什么？", "你觉得AI绘画怎么样？", "这个视频是AI生成的吗？",
                     "安洁莉娜的源石技艺是什么？", "你今天送信了吗？"):
            self.assertFalse(should_ignore_identity(text), text)
        other = bind_persona("default")
        try:
            self.assertFalse(should_ignore_identity("你是不是AI？"))
            self.assertEqual(identity_instruction(), "")
        finally:
            release_persona(other)

    def test_identity_question_never_calls_model(self):
        source = Path(__file__).resolve().parents[1] / "ai.py"
        function = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body
                        if isinstance(n, ast.FunctionDef) and n.name == "generate_reply_and_score")
        model = Mock(side_effect=AssertionError("Model must not be called"))
        namespace = dict(should_ignore_identity=should_ignore_identity, claude_chat=model)
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        for channel in ("comment", "mention", "private"):
            self.assertEqual(namespace["generate_reply_and_score"](
                "你是不是AI？", "用户", "normal", "", channel), (0, "", "", "", []))
        model.assert_not_called()

    def test_silent_private_reply_does_not_send_or_write_memory(self):
        helper = ConversationTests()
        ns, client, _ = helper.process([], [])
        ns["generate_reply_and_score"].return_value = (0, "", "", "", [])
        client.poll.return_value = [helper.message(1, "你是AI吗", 1)]
        affection = {}
        self.assertEqual(ns["process_private_messages"](client, affection, []), ([], 0))
        client.send_text.assert_not_called()
        ns["save_memory_record"].assert_not_called()
        self.assertEqual(affection, {})
