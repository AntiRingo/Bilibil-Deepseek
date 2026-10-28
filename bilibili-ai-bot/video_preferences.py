"""主动浏览的轻量兴趣偏好，不把其他内容排除在外。"""

import random
import re


def interest_weight(video, profile=None):
    text = f"{video.get('title') or ''} {video.get('desc') or ''}"
    if profile:
        interests = {
            "驻舰": r"音乐|吉他|手帐|手账|绘画|点心|甜点|收纳|日常|书信",
            "送信": r"书信|手写|信件|背包|收纳|温暖|日常",
            "去程": r"风景|音乐|旅行|收纳|摄影",
            "返程": r"旅行|照片|整理|音乐|风景",
            "休假": r"海边|海浪|海滩|风景|摄影|音乐|甜点|美食|日常",
        }
        daily = bool(re.search(interests[profile['kind']], text))
        arknights = bool(re.search(r"明日方舟|安洁莉娜|安洁丽娜|安心院|罗德岛|arknights", text, re.I))
        angelina = bool(re.search(r"安洁莉娜|安洁丽娜|安心院|angelina", text, re.I))
        fanwork = bool(re.search(r"同人|手书|手绘|音乐|歌曲|翻唱|演奏|印象曲|原创曲|mmd|mad|pv", text, re.I))
        generated = bool(re.search(r"(?<![a-z0-9])(?:ai|aigc)(?![a-z0-9])|人工智能生成|生成式|文生视频|图生视频", text, re.I))
        cute = bool(re.search(r"可爱|萌|治愈|拟人|鲸鱼娘|兽耳|猫娘|动物娘", text))
        fashion = bool(re.search(r"美妆|化妆|妆容|彩妆|穿搭|时尚|服饰|发型|美甲|配饰", text))
        theme = max(8.0 if angelina and fanwork else 4.0 if arknights or angelina else .5,
                    6.0 if generated and cute else 3.0 if generated else .5,
                    3.5 if fashion else .5)
        return max(4.0 if daily else .5, theme) + (1.0 if daily and theme > .5 else 0)
    if re.search(r"deep[\s_-]*seek|深度求索", text, re.I):
        return 1.5
    if re.search(r"(?<![a-z0-9])(?:ai|aigc|llm|chatgpt|gpt)(?![a-z0-9])|人工智能|大模型|机器学习|深度学习|生成式", text, re.I):
        return 1.3
    return 1.0


def order_videos(videos, rng=random, profile=None):
    """特别关心优先；其余按权重无放回随机排序，所有视频都有机会。"""
    special = [v for v in videos if v.get('_special')]
    remaining = [v for v in videos if not v.get('_special')]
    ordered = []
    while remaining:
        index = rng.choices(range(len(remaining)),
                            weights=[interest_weight(v, profile) for v in remaining], k=1)[0]
        ordered.append(remaining.pop(index))
    return special + ordered
