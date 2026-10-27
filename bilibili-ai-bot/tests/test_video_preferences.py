import random
import unittest

from video_preferences import interest_weight, order_videos


class VideoPreferenceTests(unittest.TestCase):
    def test_topic_matching(self):
        for title in ['DeepSeek 新版本', 'deepseek AI', '深度求索']:
            self.assertEqual(interest_weight({'title': title}), 1.5)
        for title in ['AI绘画', '大模型入门', 'ChatGPT体验']:
            self.assertEqual(interest_weight({'title': title}), 1.3)
        for title in ['游戏日常', 'Minecraft railway', '日常vlog']:
            self.assertEqual(interest_weight({'title': title}), 1.0)
        self.assertEqual(interest_weight({'desc': '人工智能'}), 1.3)
        self.assertEqual(interest_weight({'title': None}), 1.0)

    def test_priority_and_no_loss_or_mutation(self):
        videos = [{'bvid': 'a'}, {'bvid': 'b', '_special': True},
                  {'bvid': 'c', 'title': 'DeepSeek'}]
        ordered = order_videos(videos, random.Random(1))
        self.assertEqual(ordered[0]['bvid'], 'b')
        self.assertCountEqual(ordered, videos)
        self.assertEqual(videos[0]['bvid'], 'a')
        self.assertEqual(order_videos([]), [])

    def test_preference_stays_mild_and_other_topics_remain(self):
        videos = [{'title': 'DeepSeek'}, {'title': 'AI'}, {'title': '美食'}]
        counts = {v['title']: 0 for v in videos}
        rng = random.Random(42)
        for _ in range(12000):
            counts[order_videos(videos, rng)[0]['title']] += 1
        self.assertGreater(counts['DeepSeek'], counts['AI'])
        self.assertGreater(counts['AI'], counts['美食'])
        self.assertGreater(counts['美食'] / 12000, 0.23)
        self.assertLess(counts['DeepSeek'] / 12000, 0.43)

    def test_angelina_themes_keep_life_and_persona_isolation(self):
        profile = {"kind": "送信"}
        weight = lambda title: interest_weight({"title": title}, profile)
        self.assertGreater(weight("安洁莉娜同人手书"), weight("明日方舟攻略"))
        self.assertGreater(weight("安洁莉娜同人音乐"), weight("明日方舟攻略"))
        self.assertGreater(weight("明日方舟攻略"), weight("普通游戏攻略"))
        self.assertGreater(weight("AI鲸鱼娘拟人化"), weight("AI技术介绍"))
        self.assertGreater(weight("AIGC可爱动物拟人"), weight("大模型新闻"))
        self.assertGreater(weight("AI生成风景"), weight("大模型新闻"))
        self.assertGreater(weight("美妆穿搭"), weight("无关新闻"))
        self.assertGreater(weight("书信背包收纳"), weight("美妆穿搭"))
        self.assertEqual(weight("railway"), .5)
        self.assertEqual(interest_weight({"title": "安洁莉娜同人手书"}), 1.0)
        self.assertGreater(interest_weight({"title": "海浪摄影"}, {"kind":"休假"}), weight("海浪摄影"))

    def test_mixed_pool_retains_daily_life_share(self):
        videos = [{"title": title} for title in ["安洁莉娜同人手书", "明日方舟二创", "AI鲸鱼娘拟人化", "美妆穿搭", "书信收纳", "温暖日常", "手写信件", "背包整理"]]
        rng = random.Random(9)
        lifestyle = {v["title"] for v in videos[4:]}
        count = sum(order_videos(videos, rng, {"kind":"送信"})[0]["title"] in lifestyle for _ in range(2000))
        self.assertGreater(count, 600)
        self.assertLess(count, 1100)
