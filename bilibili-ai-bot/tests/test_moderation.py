import copy
import unittest

from moderation import Moderation


class ModerationTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        self.clock = 1000
        self.warnings = []
        self.blocks = []
        self.config = {"OWNER_MID": 1}
        self.engine = Moderation(
            lambda name, default: copy.deepcopy(self.files.get(name, default)),
            lambda name, data: self.files.update({name: copy.deepcopy(data)}),
            lambda mid, cfg: self.blocks.append(mid) or True,
            lambda: self.clock,
        )

    def message(self, text="你去死", stamp=None, uid=2, key=None, warn_ok=True):
        return self.engine.handle(uid, "用户", text, "private_message",
                                  self.clock if stamp is None else stamp,
                                  key or str(self.clock), self.config,
                                  lambda text: self.warnings.append(text) or warn_ok)

    def test_warning_then_block_and_report_retry(self):
        self.assertTrue(self.message())
        self.assertEqual(self.blocks, [])
        self.clock += 2
        self.assertTrue(self.message())
        self.assertEqual(self.blocks, [])
        self.assertEqual(len(self.warnings), 2)
        self.clock += 2
        self.message("你去死", key="third")
        self.assertEqual(self.blocks, ["2"])
        self.engine.notify_owner(self.config, lambda *args: False)
        self.assertFalse(self.files["data/block_log.json"]["2"]["owner_notified"])
        reports = []
        self.engine.notify_owner(self.config, lambda *args: reports.append(args) or True)
        self.engine.notify_owner(self.config, lambda *args: reports.append(args) or True)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0][1], "1")

    def test_queued_messages_and_missing_times_cannot_escalate(self):
        self.message()
        self.clock += 10
        self.message(stamp=999, key="old")
        self.message(stamp=0, key="missing")
        self.assertEqual(self.blocks, [])
        self.assertEqual(len(self.warnings), 1)

    def test_failed_warning_cannot_block(self):
        self.message(warn_ok=False)
        self.clock += 1
        self.message()
        self.assertEqual(self.blocks, [])
        self.assertEqual(len(self.warnings), 2)

    def test_spam_and_deduplication(self):
        self.config["MODERATION_REPEAT_THRESHOLD"] = 99
        for i in range(5):
            self.assertFalse(self.message("你好", key=str(i)))
        self.assertTrue(self.message("你好", key="5"))
        self.assertEqual(len(self.warnings), 1)
        self.message("你好", key="5")
        self.assertEqual(self.blocks, [])
        self.clock += 2
        self.message("你好", key="6")
        self.assertEqual(self.blocks, [])
        self.assertEqual(len(self.warnings), 2)
        self.clock += 2
        self.message("你去死", key="third")
        self.assertEqual(self.blocks, ["2"])

    def test_old_messages_do_not_form_burst(self):
        for i in range(10):
            self.assertFalse(self.message("你好", stamp=100+i, key=str(i)))
        self.assertEqual(self.warnings, [])

    def test_repetition_normalization_and_two_warnings(self):
        self.assertFalse(self.message("快回复我", key="1"))
        self.assertFalse(self.message("快 回 复 我！！", key="2"))
        self.assertTrue(self.message("快\u200b回复我。", key="3"))
        self.assertIn("脑子晕乎乎", self.warnings[0])
        self.clock += 2
        self.message("快回复我", key="4")
        self.assertIn("告主人，不理你了", self.warnings[1])
        self.assertNotIn("拉黑", self.warnings[1])
        self.assertNotIn("日志", self.warnings[1])
        self.assertEqual(self.blocks, [])
        self.clock += 2
        self.message("快回复我", key="5")
        self.assertEqual(self.blocks, ["2"])

    def test_similar_content_and_normal_reply(self):
        self.message("小鲸快来看看我刚发的消息呀", key="1")
        self.message("小鲸快来看看我刚发的消息啊", key="2")
        self.assertTrue(self.message("小鲸快来看看我刚发的消息嘛", key="3"))
        self.assertIn("相似", self.files["data/moderation.json"]["2"]["warning_reason"])
        self.clock += 2
        self.assertFalse(self.message("好的，我等你回复", key="4"))
        self.assertEqual(len(self.warnings), 1)

    def test_repetition_does_not_count_duplicate_ids_other_users_or_expired_text(self):
        self.message("快回复我", key="same")
        self.message("快回复我", key="same")
        self.message("快回复我", key="same", uid=3)
        self.message("快回复我", key="other")
        self.assertEqual(self.warnings, [])
        self.clock += 31
        self.assertFalse(self.message("快回复我", key="fresh"))

    def test_short_distinct_messages_are_not_fuzzy_duplicates(self):
        for i, text in enumerate(["好的", "好啊", "好吧", "好呀", "好嘛"]):
            self.assertFalse(self.message(text, key=str(i)))
        self.assertEqual(self.warnings, [])

    def test_thirty_second_window_and_warning_tones(self):
        for i in range(6):
            self.message("你好", stamp=969, key=f"old{i}")
        self.assertEqual(self.warnings, [])
        for i in range(6):
            self.message("你好", stamp=970, key=f"new{i}")
        self.assertIn("脑子晕乎乎", self.warnings[0])
        self.clock += 1
        for i in range(6):
            self.message("你好", key=f"continued{i}")
        self.assertIn("第二次警告", self.warnings[1])
        self.assertEqual(self.blocks, [])
        self.clock += 1
        self.message("你好", key="third")
        self.assertEqual(self.blocks, ["2"])
        self.assertEqual(len(self.files["data/block_log.json"]["2"]["warnings"]), 2)

    def test_second_warning_failure_and_backlog(self):
        self.message()
        self.clock += 2
        self.message(warn_ok=False)
        self.assertEqual(self.files["data/moderation.json"]["2"]["warning_count"], 1)
        self.clock += 2
        self.message()
        self.assertEqual(self.blocks, [])
        self.clock += 2
        self.message(stamp=1003, key="before_second_warning")
        self.assertEqual(self.blocks, [])
        self.message(key="after_second_warning")
        self.assertEqual(self.blocks, ["2"])

    def test_legacy_warning_gets_second_warning(self):
        self.files["data/moderation.json"] = {"2": {
            "events": [], "warned_at": 999, "warning_reason": "旧警告",
        }}
        self.message()
        self.assertIn("第二次警告", self.warnings[0])
        self.assertEqual(self.blocks, [])

    def test_protected_and_disabled(self):
        self.message(uid=1)
        self.assertEqual(self.warnings, [])
        self.config["PRIVATE_MESSAGE_AUTO_BLOCK"] = False
        self.message()
        self.clock += 2
        self.message()
        self.assertEqual(self.blocks, [])

    def test_warning_expiry_and_normal_recovery(self):
        self.message()
        self.clock += 1
        self.assertFalse(self.message("谢谢提醒"))
        self.clock += 86401
        self.message()
        self.assertEqual(len(self.warnings), 2)
        self.assertEqual(self.blocks, [])

    def test_block_failure_logged_honestly(self):
        self.engine.block = lambda *args: False
        self.message()
        self.clock += 2
        self.message()
        self.clock += 2
        self.message()
        self.assertFalse(self.files["data/block_log.json"]["2"]["api_blocked"])
        self.assertFalse(self.files["data/moderation.json"]["2"]["blocked"])


if __name__ == "__main__":
    unittest.main()
