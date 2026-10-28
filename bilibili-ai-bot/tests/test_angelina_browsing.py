"""Offline checks: never use account credentials or send real comments."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import angelina_browsing as browsing
import angelina_life as life
from persona_storage import bind_persona, release_persona, load_json, save_json
from video_preferences import interest_weight


class BrowsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, BILI_STATE_DIR=self.temp.name)
        self.env.start()
        self.token = bind_persona("angelina")
        self.now = datetime(2026, 10, 27, 12, tzinfo=life.TZ)
        self.kind = "驻舰"
        self.timeline = patch.object(life, "timeline", side_effect=lambda now=None: {
            "date": life.local_time(now).date().isoformat(),
            "current": {"kind": self.kind, "location": "罗德岛本舰"}, "activity": "休息"})
        self.timeline.start()
        self.clock = patch.object(life, "now_local", side_effect=lambda: self.now)
        self.clock.start()
        self.cfg = {"PROACTIVE_VIDEO_COUNT": 3, "PROACTIVE_TIMES_COUNT": 2,
                    "PROACTIVE_COMMENT_COUNT": 2, "OWNER_MID": 42, "OWNER_BILI_NAME": "博士账号"}

    def tearDown(self):
        self.clock.stop()
        self.timeline.stop()
        release_persona(self.token)
        self.env.stop()
        self.temp.cleanup()

    def profile_at_slot(self, index=0):
        profile = browsing.plan(self.cfg)
        h, m = map(int, profile["proactive_times"][index].split(":"))
        self.now = self.now.replace(hour=h, minute=m)
        return profile

    def test_work_leave_and_zero_limits(self):
        for kind, count, sessions in [("送信", 5, 1), ("去程", 5, 1), ("返程", 5, 1), ("驻舰", 10, 2), ("休假", 20, 3)]:
            self.kind = kind
            p = browsing.plan(self.cfg)
            self.assertEqual((p["daily_limit"], len(p["proactive_times"])), (count, sessions))
            self.assertEqual(p, browsing.plan(self.cfg, self.now.astimezone(timezone.utc)))
            self.assertNotIn(36, p["tids"])
            self.assertEqual(p["comment_limit"], 10 if kind == "休假" else 5 if kind == "驻舰" else 3)
            self.assertEqual(p["share_limit"], 5 if kind == "休假" else 3)
        self.assertEqual(browsing.plan({**self.cfg, "PROACTIVE_COMMENT_COUNT": 0})["comment_limit"], 0)
        self.assertEqual(browsing.plan({**self.cfg, "PROACTIVE_VIDEO_COUNT": 0})["proactive_times"], [])
        self.assertEqual(browsing.plan({**self.cfg, "PROACTIVE_TIMES_COUNT": 0})["proactive_times"], [])

    def test_slots_restart_and_no_catchup(self):
        p = self.profile_at_slot()
        self.assertFalse(browsing.claim_session(p, self.now - timedelta(minutes=1)))
        self.assertTrue(browsing.claim_session(p))
        self.assertFalse(browsing.claim_session(browsing.plan(self.cfg)))
        self.assertIsNone(browsing.current_slot(p, self.now + timedelta(minutes=45)))
        self.assertIsNone(browsing.current_slot(p, self.now + timedelta(days=1)))
        other = bind_persona("default")
        try:
            self.assertEqual(load_json(browsing.SESSIONS, {}), {})
            self.assertEqual(browsing.prompt_context(), "")
        finally:
            release_persona(other)

    def test_preferences_and_full_lore(self):
        self.kind = "休假"
        p = browsing.plan(self.cfg)
        self.assertGreater(interest_weight({"title": "海边摄影"}, p), interest_weight({"title": "DeepSeek"}, p))
        text = browsing.prompt_context(p)
        for word in ["博士", "信使", "轻重", "不是你亲历", "海边", "recommend_owner"]:
            self.assertIn(word, text)

    def test_share_budget_and_unknown_delivery(self):
        p = browsing.plan(self.cfg)
        evaluation = {"score": 9, "recommend_owner": True, "recommend_reason": "手写信的细节很温暖"}
        self.assertFalse(browsing.claim_share(p, "a", {**evaluation, "score": 6}))
        self.assertFalse(browsing.claim_share(p, "a", {**evaluation, "recommend_reason": ""}))
        self.assertTrue(browsing.claim_share(p, "a", evaluation))
        browsing.finish_share(p, "a", False)
        self.assertFalse(browsing.claim_share(p, "a", evaluation))
        self.assertTrue(browsing.claim_share(p, "b", evaluation))
        self.assertTrue(browsing.claim_share(p, "c", evaluation))
        self.assertFalse(browsing.claim_share(p, "d", evaluation))
        self.assertEqual(load_json(browsing.SHARES, {})[p["date"]]["a"], "unconfirmed")

    def load_worker(self):
        fake = ModuleType("config")
        for k, v in dict(SESSDATA="", BILI_JCT="", DEDE_USER_ID="7", OR_API_KEY="offline",
                         OR_BASE_URL="https://example.invalid", OR_CHAT_MODEL="offline", OR_VISION_MODEL="offline",
                         STATE_DIR=self.temp.name, OWNER_MID=42, PROACTIVE_VIDEO_COUNT=3, PROACTIVE_COMMENT_COUNT=2,
                         PROACTIVE_LIKE=False, PROACTIVE_COIN=False, PROACTIVE_FAV=False,
                         PROACTIVE_FOLLOW=False, PROACTIVE_COMMENT=False).items():
            setattr(fake, k, v)
        fake.get_raw_config = lambda: self.cfg
        self.fake_config = patch.dict(sys.modules, config=fake)
        self.fake_config.start()
        self.addCleanup(self.fake_config.stop)
        spec = importlib.util.spec_from_file_location("offline_proactive", Path(__file__).resolve().parents[1] / "Proactive.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_worker_remaining_daily_quota_and_real_mention_payload(self):
        worker = self.load_worker()
        self.profile_at_slot(1)
        save_json("data/watch_log.json", [{"time": "2026-10-27 12:00", "bvid": str(i)} for i in range(9)])
        video = {"bvid": "BVtest", "title": "手帐日常", "up_name": "up", "up_mid": 8, "pubdate": 1793000000}
        with patch.multiple(worker, generate_cookies_file=Mock(), get_followings=Mock(return_value=[]),
                            get_hot_videos_by_tid=Mock(return_value=[video]), get_search_videos=Mock(return_value=[]), download_video=Mock(return_value="dummy"),
                            compress_video=Mock(return_value="dummy"), analyze_video=Mock(return_value="手写信"),
                            delete_video=Mock(), get_video_oid=Mock(return_value=9),
                            send_comment=Mock(return_value=True),
                            evaluate_video=Mock(return_value={"score": 9, "recommend_owner": True, "recommend_reason": "这封手写信很温暖"})), patch.object(worker.time, "sleep"), patch.object(worker.requests, "post", side_effect=AssertionError("network forbidden")), patch.object(worker.or_client.chat.completions, "create", return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="这封手写信，想和你一起看看"))])):
            worker._run_for_persona()
            self.assertEqual(len(load_json("data/watch_log.json", [])), 10)
            worker._run_for_persona()
            worker.download_video.assert_called_once()
            worker.send_comment.assert_called_once_with(9, "@博士账号 这封手写信，想和你一起看看", mention=("博士账号", "42"))
            self.assertEqual(load_json(browsing.SHARES, {})["2026-10-27"]["BVtest"], "published")
        with patch("comment_memes.prepare_comment_pictures", return_value=None), patch.object(worker.requests, "post") as post:
            post.return_value.json.return_value = {"code": 0}
            self.assertTrue(worker.send_comment(9, "@博士账号 来看看", mention=("博士账号", "42")))
            self.assertIn('42', post.call_args.kwargs["data"]["at_name_to_mid"])

    def test_discovery_queries_and_search_normalization(self):
        p = self.profile_at_slot()
        queries = browsing.discovery_queries(p)
        self.assertEqual(queries, browsing.discovery_queries(p))
        self.assertEqual(len(queries), 4)
        self.assertTrue(any("安洁莉娜" in q for q in queries))
        self.assertTrue(any("AI" in q for q in queries))
        worker = self.load_worker()
        worker._search_headers = worker.headers
        response = Mock()
        response.json.return_value = {"code": 0, "data": {"result": [
            {"bvid": "BV123", "title": '<em class="keyword">安洁莉娜</em>手书 &amp; 音乐',
             "description": "<b>同人</b>", "mid": 42, "pubdate": 1793000000},
            {"bvid": "invalid"}]}}
        with patch.object(worker.requests, "get", return_value=response), patch.object(worker, "sign_wbi_params", side_effect=lambda p:p):
            videos = worker.get_search_videos(queries[0])
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0]["title"], "安洁莉娜手书 & 音乐")
            self.assertEqual(videos[0]["desc"], "同人")
            response.json.return_value = {"code": -412}
            self.assertEqual(worker.get_search_videos(queries[0]), [])

    def test_evaluation_uses_persona_even_with_custom_prompt_and_rejects_bad_json(self):
        worker = self.load_worker()
        self.cfg["PROMPT_VIDEO_EVALUATE"] = "评价{title}"
        completion = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"score":"九分"}'))]))
        with patch.object(worker.or_client.chat.completions, "create", completion):
            self.assertIsNone(worker.evaluate_video({"title": "音乐"}, "钢琴演奏"))
        messages = completion.call_args.kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("安洁莉娜", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
