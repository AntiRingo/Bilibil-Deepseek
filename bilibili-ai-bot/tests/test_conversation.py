"""Offline conversation behavior checks; never load live bot credentials."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from conversation import group_messages, split_reply


class ConversationTests(unittest.TestCase):
    def message(self, uid, text, key):
        return dict(sender_uid=uid, talker_id=uid, session_type=1,
                    username=str(uid), content=text, msg_key=key)

    def test_group_keeps_users_separate_and_ordered(self):
        messages = [self.message(1, '今天好累', 1), self.message(2, '你好', 2),
                    self.message(1, '忙到现在才吃饭', 3)]
        grouped = group_messages(messages)
        self.assertEqual([m['content'] for m in grouped], ['今天好累\n\n忙到现在才吃饭', '你好'])
        self.assertEqual(grouped[0]['msg_key'], 3)
        self.assertEqual(messages[0]['content'], '今天好累')

    def test_split_preserves_content_and_limits_bubbles(self):
        self.assertEqual(split_reply('你好。今天好吗？'), ['你好。今天好吗？'])
        self.assertEqual(split_reply('  '), [])
        self.assertEqual(split_reply('一\r\n\r\n二\n\n三\n\n四'), ['一', '二', '三\n\n四'])

    def process(self, messages, send_results, blocked=False):
        source = Path(__file__).resolve().parents[1] / 'ai.py'
        function = next(node for node in ast.parse(source.read_text(encoding='utf-8')).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'process_private_messages')
        config = dict(ENABLE_PRIVATE_MESSAGES=True)
        moderation = Mock()
        moderation.handle.side_effect = lambda *args: blocked and args[2] == '危险'
        namespace = dict(group_messages=group_messages, split_reply=split_reply,
                         get_raw_config=lambda: config, Moderation=Mock(return_value=moderation), print=Mock(),
                         reply_scope_allows=lambda *args: True, get_level=lambda *args: 'normal',
                         LEVEL_NAMES={'normal': '普通'}, AFFECTION_FILE='unused',
                         time=SimpleNamespace(sleep=Mock()),
                         compress_user_memory=lambda memory, *args: memory)
        for name in ['load_json', 'save_json', 'block_user', 'build_memory_context',
                     'log_security_event', 'update_user_profile', '_save_permanent_memory', 'save_memory_record']:
            namespace[name] = Mock()
        namespace['generate_reply_and_score'] = Mock(return_value=(1, '第一段\n\n第二段\n\n第三段', '', '', []))
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        client = Mock()
        client.poll.return_value = messages
        client.send_text.side_effect = send_results
        result = namespace['process_private_messages'](client, {}, [])
        return namespace, client, result

    def test_one_generation_for_batch_and_partial_delivery_memory(self):
        ns, client, result = self.process([self.message(1, '你好', 1), self.message(1, '在忙吗', 2)], [True, False])
        ns['generate_reply_and_score'].assert_called_once()
        self.assertEqual(ns['generate_reply_and_score'].call_args.args[0], '你好\n\n在忙吗')
        self.assertEqual(client.send_text.call_count, 2)
        self.assertEqual(ns['save_memory_record'].call_args.args[-1], '第一段')
        self.assertEqual(result[1], 1)

    def test_moderated_sender_does_not_reach_model(self):
        ns, client, _ = self.process([self.message(1, '你好', 1), self.message(1, '危险', 2)], [], blocked=True)
        ns['generate_reply_and_score'].assert_not_called()
        client.send_text.assert_not_called()


if __name__ == '__main__':
    unittest.main()
