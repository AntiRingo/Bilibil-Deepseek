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
