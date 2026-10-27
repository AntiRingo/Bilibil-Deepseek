"""Persistent original-persona life; dates are a local story clock, not canon dates."""
from datetime import datetime, date, timedelta, timezone
import json
import random
import re
from difflib import SequenceMatcher

from persona_storage import active_persona, load_json, save_json, state_lock

TZ = timezone(timedelta(hours=8))
FILE = "data/angelina_life.json"
DELIVERY = "data/angelina_delivery.json"
# These are opportunities to evaluate, never promises to publish.
POST_HOURS = {"驻舰": (9, 12, 18, 21), "送信": (12, 20),
              "去程": (12, 19), "返程": (12, 19), "休假": (10, 15, 20)}
LORE = """以原版安洁莉娜为准：叙拉古出身的沃尔珀、感染者、罗德岛信使与辅助干员，
源石技艺影响轻重，不是瞬间传送。温柔明快、认真送信，对博士有含蓄好感。
故事发生在泰拉。罗德岛本舰是移动陆行舰；龙门是移动城市；汐斯塔有海滨旅游背景。
这些行程是符合背景的原创日常，不是官方剧情或官方年表；现实日期只用于应用计时。
不引入异格未来经历、重大主线事件、现实地名交通或互联网热点。
未列出的原作人物不安排出场；不编造知名角色的职务、关系、行踪和对白。
不得把计划说成已经完成，不替博士答应邀请；人在外地时通过通讯联系，不能突然出现在博士办公室。
不编造特产专名、商业品牌或机密收件人；只能分享普通食品、明信片等生活小物。"""


def now_local():
    return datetime.now(TZ)


def local_time(now=None):
    now = now or now_local()
    return now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)


def enabled():
    return active_persona() == "angelina"


def _leg(start, days, kind, place, tasks):
    return {"start": start.isoformat(), "end": (start + timedelta(days=days - 1)).isoformat(),
            "kind": kind, "location": place, "tasks": tasks}


def timeline(now=None):
    if not enabled():
        return None
    today = local_time(now).date()
    with state_lock():
        state = load_json(FILE, {})
        legs = state.setdefault("legs", [])
        cursor = date.fromisoformat(legs[-1]["end"]) + timedelta(days=1) if legs else today
        # Commit whole trips so tomorrow's announced destination cannot be rerolled.
        while cursor <= today + timedelta(days=21):
            rng = random.Random(cursor.isoformat())
            destination = rng.choice(["龙门", "叙拉古"])
            route = [
                (rng.randint(4, 6), "驻舰", "罗德岛本舰", ["在舰内递送信件，核对签收记录", "整理下一批信件，检查信使背包", "完成源石技艺训练，按安排接受健康检查", "整理任务回执，去甲板透透气"]),
                (3, "去程", f"前往{destination}的途中", ["随运输队前行，在停靠点核对路线", "保护随身信袋，休息时检查封口"]),
                (rng.randint(4, 6), "送信", destination, ["按约定递送信件，仔细核对收件信息", "走访交接点，整理今天的签收回执", "完成当天递送后，在街边稍作休息"]),
                (3, "返程", "返回罗德岛本舰的途中", ["带着任务回执返航，在停靠点整理背包", "随运输队返回，检查剩余物资"]),
                (4, "驻舰", "罗德岛本舰", ["提交任务回执，整理旅途笔记", "在舰内递送信件，完成例行训练"]),
                (4, "去程", "前往汐斯塔的途中", ["按批准的休假行程出发，收好行李", "在中途停靠时写旅行笔记"]),
                (3, "休假", "汐斯塔", ["在海边散步，听了一会儿海浪", "逛街挑选普通明信片，写下旅途见闻", "在海边休息，整理这几天的小纪念品"]),
                (4, "返程", "返回罗德岛本舰的途中", ["结束休假，按行程返回本舰", "整理旅行笔记，仔细收好明信片"]),
            ]
            for days, kind, place, tasks in route:
                legs.append(_leg(cursor, days, kind, place, tasks))
                cursor += timedelta(days=days)
        save_json(FILE, state)
    current = next((leg for leg in legs if leg["start"] <= today.isoformat() <= leg["end"]), None)
    if current is None:
        return None
    day_index = (today - date.fromisoformat(current["start"])).days
    future = [leg for leg in legs if leg["start"] > today.isoformat()][:3]
    return {"date": today.isoformat(), "timezone": "Asia/Shanghai", "current": current,
            "activity": current["tasks"][day_index % len(current["tasks"])],
            "upcoming": future, "legs": [leg for leg in legs if leg["end"] >= (today - timedelta(days=7)).isoformat()][:10]}


def context(now=None):
    life = timeline(now)
    if not life:
        return ""
    posts = load_json("data/dynamic_log.json", [])[-3:]
    return ("\n【安洁莉娜的连续生活约束】\n" + LORE + "\n当前行程（优先于旧聊天中的地点）：\n"
            + json.dumps({k: v for k, v in life.items() if k != "legs"}, ensure_ascii=False)
            + "\n当天活动白天为安排、晚间才可回顾，不提前声称完成。近期已发布动态：\n"
            + json.dumps([p.get("text", "") for p in posts], ensure_ascii=False))


def recent_messages(now=None):
    """Bound context to actual recent interactions, excluding generated summaries/posts."""
    now = local_time(now)
    result = []
    for item in load_json("data/memory.json", []):
        if item.get("thread_id") in ("summary", "dynamic") or str(item.get("rpid", "")).startswith("compressed_"):
            continue
        try:
            # Legacy memory writers use host-local wall time; explicit offsets are respected.
            stamp = datetime.fromisoformat(item.get("time", ""))
            stamp = stamp.astimezone(TZ)
        except (TypeError, ValueError):
            continue
        if timedelta(0) <= now - stamp <= timedelta(hours=48) and item.get("text"):
            result.append({"time": stamp.isoformat(), "text": str(item["text"])[:1000]})
    return sorted(result, key=lambda item: item["time"])[-12:]


def repeated(text, posts=None):
    """Ignore punctuation and catch close rewrites before any outbound request."""
    normalize = lambda value: re.sub(r"[\W_]+", "", value).casefold()
    candidate = normalize(text)
    if not candidate:
        return True
    posts = load_json("data/dynamic_log.json", [])[-100:] if posts is None else posts
    for post in posts:
        previous = normalize(post.get("text", ""))
        if not previous:
            continue
        if candidate in previous or previous in candidate:
            return True
        if SequenceMatcher(None, candidate, previous, autojunk=False).ratio() >= 0.65:
            return True
        grams = lambda value: {value[i:i + 3] for i in range(len(value) - 2)}
        left, right = grams(candidate), grams(previous)
        if left and right and len(left & right) / min(len(left), len(right)) >= 0.55:
            return True
    return False


def due(now=None, life=None):
    now = local_time(now)
    if not enabled():
        return False
    life = life or timeline(now)
    if not life or now.hour not in POST_HOURS.get(life["current"]["kind"], ()):
        return False
    day = now.date().isoformat()
    if any(p.get("time", "").startswith(day) for p in load_json("data/dynamic_log.json", [])):
        return False
    delivery = load_json(DELIVERY, {}).get(day, {})
    if not delivery:
        return True
    # Legacy pending/unconfirmed records still block automatic resends.
    return delivery.get("status") == "skipped" and delivery.get("slot") != now.strftime("%Y-%m-%dT%H")


def publish_once(publisher, generator, now=None):
    """Evaluate once per opportunity; claim before I/O and never retry unknown sends."""
    now = local_time(now)
    life = timeline(now)
    if not life:
        return False
    day = now.date().isoformat()
    with state_lock():
        if not due(now, life):
            return False
        deliveries = load_json(DELIVERY, {})
        deliveries[day] = {"status": "pending", "time": now.isoformat(),
                           "slot": now.strftime("%Y-%m-%dT%H")}
        save_json(DELIVERY, deliveries)
    life = {**life, "now": now.isoformat(), "recent_messages": recent_messages(now)}
    success = False
    status = "skipped"
    try:
        text = generator(life)
        if isinstance(text, str) and text.strip() and not repeated(text):
            status = "unconfirmed"  # Set before contacting Bilibili, even if it raises.
            success = bool(publisher(text))
            if success:
                status = "published"
    except Exception:
        pass
    with state_lock():
        deliveries = load_json(DELIVERY, {})
        deliveries[day]["status"] = status
        if success:
            log = load_json("data/dynamic_log.json", [])
            log.append({"time": now.strftime("%Y-%m-%d %H:%M"), "text": text, "has_image": False,
                        "location": life["current"]["location"], "activity": life["activity"], "story_date": day})
            save_json("data/dynamic_log.json", log[-100:])
        save_json(DELIVERY, deliveries)
    return success
