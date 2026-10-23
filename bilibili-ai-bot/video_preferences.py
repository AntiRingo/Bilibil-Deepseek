"""主动浏览的轻量兴趣偏好，不把其他内容排除在外。"""

import random
import re


def interest_weight(video):
    text = f"{video.get('title') or ''} {video.get('desc') or ''}"
    if re.search(r"deep[\s_-]*seek|深度求索", text, re.I):
        return 1.5
    if re.search(r"(?<![a-z0-9])(?:ai|aigc|llm|chatgpt|gpt)(?![a-z0-9])|人工智能|大模型|机器学习|深度学习|生成式", text, re.I):
        return 1.3
    return 1.0


def order_videos(videos, rng=random):
    """特别关心优先；其余按权重无放回随机排序，所有视频都有机会。"""
    special = [v for v in videos if v.get('_special')]
    remaining = [v for v in videos if not v.get('_special')]
    ordered = []
    while remaining:
        index = rng.choices(range(len(remaining)),
                            weights=[interest_weight(v) for v in remaining], k=1)[0]
        ordered.append(remaining.pop(index))
    return special + ordered
