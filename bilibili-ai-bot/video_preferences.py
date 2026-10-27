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
        if re.search(interests[profile['kind']], text):
            return 4.0
        if re.search(r"明日方舟|安洁莉娜|罗德岛", text):
            return 1.5
        return .5
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
