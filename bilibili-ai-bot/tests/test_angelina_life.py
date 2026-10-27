"""Offline lifecycle tests: no real model or Bilibili requests."""
from datetime import datetime, timedelta, timezone
import os
import importlib.util
import json
from types import ModuleType, SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import angelina_life as life
from persona_storage import bind_persona, release_persona, load_json, save_json


class AngelinaLifeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, BILI_STATE_DIR=self.temp.name)
        self.env.start()
        self.token = bind_persona("angelina")
        self.now = datetime(2026, 10, 26, 21, 30, tzinfo=life.TZ)

    def tearDown(self):
        release_persona(self.token)
        self.env.stop()
        self.temp.cleanup()

    def test_itinerary_survives_reload_and_extends_without_changing_promises(self):
        first = life.timeline(self.now)
        initial = load_json(life.FILE, {})["legs"]
        self.assertEqual(first, life.timeline(self.now))
        later = life.timeline(self.now + timedelta(days=80))
        extended = load_json(life.FILE, {})["legs"]
        self.assertEqual(initial, extended[:len(initial)])
        self.assertTrue(later["current"]["start"] <= later["date"] <= later["current"]["end"])
        for previous, following in zip(extended, extended[1:]):
            self.assertEqual(datetime.fromisoformat(previous["end"]) + timedelta(days=1), datetime.fromisoformat(following["start"]))
        self.assertEqual({leg["kind"] for leg in extended}, {"驻舰", "去程", "送信", "返程", "休假"})

    def test_publish_time_zone_restart_and_duplicate_claim(self):
        sender = Mock(return_value=True)
        self.assertFalse(life.publish_once(sender, lambda _: "信袋上的绳结有点松，重新系好以后，忽然觉得心里也踏实了。", self.now.replace(hour=3)))
        # UTC host still observes Beijing 21:30.
        self.assertTrue(life.publish_once(sender, lambda _: "信袋上的绳结有点松，重新系好以后，忽然觉得心里也踏实了。", self.now.astimezone(timezone.utc)))
        self.assertFalse(life.publish_once(sender, lambda _: "信袋上的绳结有点松，重新系好以后，忽然觉得心里也踏实了。", self.now + timedelta(minutes=2)))
        sender.assert_called_once()
        post = load_json("data/dynamic_log.json", [])[0]
        self.assertEqual(post["location"], life.timeline(self.now)["current"]["location"])
        self.assertEqual(post["story_date"], "2026-10-26")
        self.assertIn(post["text"], life.context(self.now))

    def test_unknown_result_is_visible_and_not_retried(self):
        sender = Mock(side_effect=TimeoutError)
        self.assertFalse(life.publish_once(sender, lambda _: "信袋上的绳结有点松，重新系好以后，忽然觉得心里也踏实了。", self.now))
        self.assertFalse(life.publish_once(sender, lambda _: "信袋上的绳结有点松，重新系好以后，忽然觉得心里也踏实了。", self.now))
        sender.assert_called_once()
        self.assertEqual(load_json(life.DELIVERY, {})["2026-10-26"]["status"], "unconfirmed")
        self.assertEqual(load_json("data/dynamic_log.json", []), [])

    def test_existing_post_and_persona_isolation(self):
        save_json("data/dynamic_log.json", [{"time":"2026-10-26 12:00", "text":"已有动态"}])
        self.assertFalse(life.due(self.now))
        other = bind_persona("default")
        try:
            self.assertIsNone(life.timeline(self.now))
            self.assertEqual(life.context(self.now), "")
            self.assertFalse(life.due(self.now))
            self.assertEqual(load_json(life.FILE, {}), {})
        finally:
            release_persona(other)

    def test_skip_allows_next_opportunity_but_no_repeat_in_same_hour(self):
        sender = Mock(return_value=True)
        generator = Mock(return_value=None)
        self.assertFalse(life.publish_once(sender, generator, self.now.replace(hour=9)))
        self.assertFalse(life.publish_once(sender, generator, self.now.replace(hour=9, minute=59)))
        generator.assert_called_once()
        self.assertTrue(life.due(self.now.replace(hour=12)))
        self.assertFalse(life.due(self.now.replace(hour=11)))
        sender.assert_not_called()

    def test_generation_error_skips_but_does_not_consume_daily_publication(self):
        sender = Mock()
        self.assertFalse(life.publish_once(sender, Mock(side_effect=ValueError), self.now.replace(hour=9)))
        self.assertEqual(load_json(life.DELIVERY, {})["2026-10-26"]["status"], "skipped")
        self.assertTrue(life.due(self.now.replace(hour=12)))
        sender.assert_not_called()

    def test_duplicate_is_blocked_even_if_generator_approves(self):
        old = "今天把信封的边角抚平，又仔细系好了背包。等到休息时再翻开笔记，记下路上那些小小的心情。"
        save_json("data/dynamic_log.json", [{"time": "2026-10-25 12:00", "text": old}])
        sender = Mock()
        self.assertTrue(life.repeated(old.replace("今天", "刚才").replace("心情", "感受")))
        self.assertFalse(life.publish_once(sender, lambda _: old, self.now))
        sender.assert_not_called()
        self.assertFalse(life.repeated("海浪在沙滩上留下一串泡沫，刚想数清楚，下一阵浪又轻轻盖了上来。"))

    def test_generator_receives_current_time_and_recent_messages(self):
        save_json("data/memory.json", [
            {"time": (self.now - timedelta(hours=2)).isoformat(), "text": "最近聊天", "thread_id": "local_chat"},
            {"time": (self.now - timedelta(days=3)).isoformat(), "text": "旧聊天"},
            {"time": self.now.isoformat(), "text": "动态不是消息", "thread_id": "dynamic"},
            {"time": "bad", "text": "错误日期"}])
        generator = Mock(return_value=None)
        life.publish_once(Mock(), generator, self.now)
        context = generator.call_args.args[0]
        self.assertEqual(context["now"], self.now.isoformat())
        self.assertEqual([m["text"] for m in context["recent_messages"]], ["最近聊天"])

    def test_travel_and_vacation_have_different_opportunities(self):
        with patch.object(life, "timeline", return_value={"current": {"kind": "去程"}}):
            self.assertFalse(life.due(self.now.replace(hour=9)))
            self.assertTrue(life.due(self.now.replace(hour=19)))
        with patch.object(life, "timeline", return_value={"current": {"kind": "休假"}}):
            self.assertTrue(life.due(self.now.replace(hour=15)))
            self.assertFalse(life.due(self.now.replace(hour=21)))

    def test_inflight_claim_blocks_another_worker(self):
        second_sender = Mock()
        def generate(context):
            self.assertFalse(life.publish_once(second_sender, Mock(), self.now))
            return "今天的小事情"
        sender = Mock(return_value=True)
        self.assertTrue(life.publish_once(sender, generate, self.now))
        second_sender.assert_not_called()
        sender.assert_called_once()

    def test_model_decision_review_and_failures_never_use_canned_posts(self):
        fake = ModuleType("config")
        for key, value in dict(SESSDATA="", BILI_JCT="", DEDE_USER_ID="", OR_API_KEY="",
                               OR_CHAT_MODEL="offline").items():
            setattr(fake, key, value)
        with patch.dict(sys.modules, config=fake):
            spec = importlib.util.spec_from_file_location("offline_dynamic", Path(__file__).resolve().parents[1] / "dynamic.py")
            worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(worker)
        client = Mock()
        worker.or_client = Mock()
        worker.or_client.with_options.return_value = client
        create = client.chat.completions.create
        response = lambda value: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
        context = {**life.timeline(self.now), "now": self.now.isoformat(), "recent_messages": [{"text": "聊到一首歌"}]}
        candidate = "刚刚把背包侧袋的小扣子缝牢了，针脚有点歪，倒是比原来结实。认真看了好一会儿，还是决定先不拆掉重来啦。下次取笔记的时候，再也不用担心它掉出来了。"
        create.return_value = response({"publish": False})
        self.assertIsNone(worker.generate_angelina_diary(context))
        self.assertEqual(create.call_count, 1)
        for approved in (False, True):
            create.reset_mock()
            create.side_effect = [response({"publish": True, "text": candidate}), response({"approved": approved})]
            self.assertEqual(worker.generate_angelina_diary(context), candidate if approved else None)
            prompt = create.call_args_list[0].kwargs["messages"][0]["content"]
            self.assertIn(context["now"], prompt)
            self.assertIn("聊到一首歌", prompt)
            self.assertIn("安洁莉娜", prompt)
        create.side_effect = TimeoutError
        self.assertIsNone(worker.generate_angelina_diary(context))
        save_json("data/dynamic_log.json", [{"text": candidate}])
        create.reset_mock()
        create.side_effect = None
        create.return_value = response({"publish": True, "text": candidate})
        self.assertIsNone(worker.generate_angelina_diary(context))
        self.assertEqual(create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
