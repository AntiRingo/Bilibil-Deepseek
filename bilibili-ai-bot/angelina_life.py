"""Persistent original-persona life; dates are a local story clock, not canon dates."""
from datetime import datetime, date, timedelta, timezone
import json
import random

from persona_storage import active_persona, load_json, save_json, state_lock

TZ = timezone(timedelta(hours=8))
FILE = "data/angelina_life.json"
DELIVERY = "data/angelina_delivery.json"
NIGHT_TIME = "21:30"
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


def fallback(life):
    leg = life["current"]
    moments = {
        "驻舰": [
            "忙完手里的事情，捧着杯子发了一小会儿呆。原来什么都不赶的时候，热气慢慢散掉也能看很久呀。今天没有特别了不起的事，不过这样安稳的一天，我也很喜欢。",
            "今天整理东西时，发现背包里还夹着一张没写完的小纸条。原本想记下一件有趣的事，结果只写了一半……现在反倒想不起后半句了。下次还是一想到就告诉博士好了。",
            "今天给自己留了一点发呆的时间，连背包都好好放到了旁边。总觉得还有什么要忙，坐了一会儿才反应过来：今天的事情已经做完啦。这样的小空闲，也想分给博士一点。"],
        "送信": [
            "今天递出信的时候，不自觉地又把信封的边角抚平了一遍。路上一直小心护着，真交到对方手里，才终于松了口气。回去的脚步都有点轻了。嘿嘿，一封信平安到达，真的会让人开心很久。",
            "送完今天的信，才发现自己把背包带攥得有点紧。松开手，慢慢走了一小段路，街上的声音好像也一下清楚了。原来忙起来的时候，会漏掉这么多小小的热闹呀。",
            "今天核对完回执，认真把它们收在了不会折到的地方。背包轻了一些，心里却像多装了点什么。大概是终于把惦记着的事做好了吧。博士，你今天有没有这样松一口气的时候？"],
        "去程": [
            "今天趁停靠的空当翻了翻笔记，想把路上的见闻记下来。结果第一句写得太认真，后面反倒不知道怎么接了。还是先记几个小词吧，等回来慢慢讲给你听。现在有一点想念舰上的日常了。",
            "今天休息时重新整理了一遍背包，把常用的东西放到伸手就能拿到的位置。每次出门都觉得自己准备得更熟练了一点，真的上路以后，心里还是会悄悄期待遇见些什么。"],
        "返程": [
            "今天整理背包，才发现一路上舍不得扔的小纸片已经攒了好几张。明明没什么特别的，看到它们却能想起当时的心情。先收好吧，回去的时候，想挑几件有趣的小事讲给你听。",
            "今天在笔记末尾留了一页空白，本来准备回来再补上。看着看着，就开始想回到舰上以后先做什么了。好像只要想到熟悉的地方，路上的一点疲惫就没那么难熬了。"],
        "休假": [
            "今天在海边待得比自己想的久一点。原本只是想散散步，听着浪声，就不太舍得马上走了。平时总想着下一件要做的事，今天终于可以慢慢来。这样的声音，要是也能带回去给你听就好了。",
            "今天挑明信片时犹豫了好久，觉得这张好看，另一张也想留下。最后才发现，比起挑选，我好像更期待在背面写些什么。先不告诉博士，等我想好一句满意的再说。",
            "今天整理小纪念品，把它们摆开又收好，忍不住笑了。出门前明明还想把行李带得轻一点呀。不过每一样都能让我想起一个小瞬间，多一点重量也没关系。"],
    }
    index = date.fromisoformat(life["date"]).toordinal()
    moment = moments[leg["kind"]][index % len(moments[leg["kind"]])]
    extra = ""
    if leg["kind"] == "送信" and index % 5 == 0:
        extra = "博士，要不要我回去时带点当地的小点心？有合适的我就留意一下。"
    elif leg["kind"] == "休假" and index % 3 == 0:
        extra = "下次休假，博士如果也有空，要不要一起出来走走？"
    return f"{moment}{extra}"


def due(now=None):
    now = local_time(now)
    if not enabled() or now.strftime("%H:%M") < NIGHT_TIME:
        return False
    day = now.date().isoformat()
    if any(p.get("time", "").startswith(day) for p in load_json("data/dynamic_log.json", [])):
        return False
    return day not in load_json(DELIVERY, {})


def publish_once(publisher, generator, now=None):
    """Claim before network I/O. Unknown outcomes are never resent automatically."""
    now = local_time(now)
    day = now.date().isoformat()
    with state_lock():
        if not due(now):
            return False
        deliveries = load_json(DELIVERY, {})
        deliveries[day] = {"status": "pending", "time": now.isoformat()}
        save_json(DELIVERY, deliveries)
    life = timeline(now)
    try:
        text = generator(life)
        success = publisher(text)
    except Exception:
        success = False
    with state_lock():
        deliveries = load_json(DELIVERY, {})
        deliveries[day]["status"] = "published" if success else "unconfirmed"
        if success:
            log = load_json("data/dynamic_log.json", [])
            log.append({"time": now.strftime("%Y-%m-%d %H:%M"), "text": text, "has_image": False,
                        "location": life["current"]["location"], "activity": life["activity"], "story_date": day})
            save_json("data/dynamic_log.json", log[-100:])
        save_json(DELIVERY, deliveries)
    return success
