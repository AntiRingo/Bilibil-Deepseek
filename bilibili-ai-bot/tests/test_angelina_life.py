"""Offline lifecycle tests: no real model or Bilibili requests."""
from datetime import datetime, timedelta, timezone
import os
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
        self.assertFalse(life.publish_once(sender, life.fallback, self.now - timedelta(minutes=1)))
        # UTC host still observes Beijing 21:30.
        self.assertTrue(life.publish_once(sender, life.fallback, self.now.astimezone(timezone.utc)))
        self.assertFalse(life.publish_once(sender, life.fallback, self.now + timedelta(minutes=2)))
        sender.assert_called_once()
        post = load_json("data/dynamic_log.json", [])[0]
        self.assertEqual(post["location"], life.timeline(self.now)["current"]["location"])
        self.assertEqual(post["story_date"], "2026-10-26")
        self.assertIn(post["text"], life.context(self.now))

    def test_unknown_result_is_visible_and_not_retried(self):
        sender = Mock(side_effect=TimeoutError)
        self.assertFalse(life.publish_once(sender, life.fallback, self.now))
        self.assertFalse(life.publish_once(sender, life.fallback, self.now))
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

    def test_diary_is_a_small_moment_not_itinerary_dump(self):
        for offset in range(65):
            today = life.timeline(self.now + timedelta(days=offset))
            text = life.fallback(today)
            self.assertNotIn(today["date"], text)
            self.assertNotIn("接下来从", text)
            self.assertGreater(len(text), 50)


if __name__ == "__main__":
    unittest.main()
