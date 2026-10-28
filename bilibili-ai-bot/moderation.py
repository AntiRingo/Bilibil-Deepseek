"""Persistent warning-first moderation shared by comments and private messages."""
import re
import time
import unicodedata
from difflib import SequenceMatcher

from private_messages import assess_private_message, is_protected_sender


def normalize_repetition(content):
    text = unicodedata.normalize("NFKC", content).casefold()
    return "".join(c for c in text if not c.isspace()
                   and unicodedata.category(c)[0] != "P"
                   and unicodedata.category(c) != "Cf")


def similar_content(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    # Short replies are too ambiguous for fuzzy matching; bound comparison cost.
    if min(len(left), len(right)) < 6 or max(len(left), len(right)) > 2000:
        return False
    if min(len(left), len(right)) / max(len(left), len(right)) < 0.8:
        return False
    return SequenceMatcher(None, left, right, autojunk=False).ratio() >= 0.85


def harmful_reason(content, config):
    text = unicodedata.normalize("NFKC", content)
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff\s]", "", text)
    if re.search(r"(你|你们|您).{0,6}(去死|该死|傻逼|煞笔|废物)|杀了你|弄死你|人肉你|曝光你.{0,6}(住址|手机号)", text):
        return "疑似定向辱骂、威胁或隐私攻击"
    decision = assess_private_message(content, config.get("PRIVATE_MESSAGE_TRUSTED_DOMAINS") or None)
    return decision.reason if decision.should_block else ""


class Moderation:
    def __init__(self, load, save, block, now=time.time):
        self.load, self.save, self.block, self.now = load, save, block, now

    def handle(self, mid, username, content, source, timestamp, event_id,
               config, warn):
        """Return True when the message must be quarantined (never sent to an LLM)."""
        mid = str(mid)
        if is_protected_sender(mid, config):
            return bool(harmful_reason(content, config))
        state = self.load("data/moderation.json", {})
        user = state.setdefault(mid, {"events": []})
        now = self.now()
        if user.get("blocked"):
            return True
        stamp = float(timestamp or 0)
        if stamp > 10_000_000_000:
            stamp /= 1000
        # Missing timestamps cannot establish either a burst or post-warning conduct.
        window = max(1, int(config.get("MODERATION_SPAM_WINDOW", 30)))
        threshold = max(2, int(config.get("MODERATION_SPAM_THRESHOLD", 6)))
        user["events"] = [e for e in user["events"] if e["timestamp"] >= now - window]
        if any(e["id"] == event_id for e in user["events"]):
            return bool(user.get("warned_at"))
        normalized = normalize_repetition(content)
        event = {"id": event_id, "timestamp": stamp, "source": source,
                 "content": content[:500], "comparison_text": normalized}
        if now - window <= stamp <= now:
            user["events"].append(event)
        reason = harmful_reason(content, config)
        repeat_threshold = max(2, int(config.get("MODERATION_REPEAT_THRESHOLD", 3)))
        similar_events = [e for e in user["events"] if similar_content(
            normalized, e.get("comparison_text", normalize_repetition(e["content"])))]
        if now - window <= stamp <= now and len(similar_events) >= repeat_threshold:
            reason = reason or f"{window}秒内重复发送至少{repeat_threshold}条相同或相似内容，疑似刷屏"
        if len(user["events"]) >= threshold:
            reason = reason or f"{window}秒内发送至少{threshold}条消息，疑似刷屏"
        if not reason:
            self.save("data/moderation.json", state)
            return False
        enabled = config.get("ENABLE_AUTO_BLOCK", True) and (
            source != "private_message" or config.get("PRIVATE_MESSAGE_AUTO_BLOCK", True))
        warned_at = user.get("warned_at", 0)
        ttl = max(1, int(config.get("MODERATION_WARNING_TTL", 86400)))
        expired = not warned_at or now - warned_at > ttl
        # Existing one-warning records migrate as stage one, never stage two.
        warning_count = 0 if expired else user.get("warning_count", 1)
        if warning_count < 2 and (expired or warned_at < stamp <= now):
            if warning_count == 0:
                warning = (
                    "一下发这么多消息，小鲸脑子晕乎乎的处理不过来了啦！哼，慢一点嘛，让小鲸喘口气～"
                    if "疑似刷屏" in reason else
                    "哼，这样说话小鲸有点生气啦！请停止攻击或发送有害内容，好好和小鲸聊天嘛～"
                )
            else:
                warning = "这是第二次警告，小鲸这次真的生气了！再这样下去，小鲸就要告主人，不理你了。"
            if warn(warning):
                history = [] if expired else user.get("warnings", [{
                    "time": warned_at, "reason": user.get("warning_reason"),
                    "evidence": user.get("warning_evidence"),
                }])
                sent_at = self.now()
                history.append({"time": sent_at, "reason": reason, "text": warning, "evidence": event})
                user.update(warned_at=sent_at, warning_count=warning_count + 1,
                            warning_reason=reason, warning_evidence=event, warnings=history)
        elif warning_count >= 2 and enabled and warned_at < stamp <= now:
            blocked = bool(self.block(mid, config))
            log = self.load("data/block_log.json", {})
            record = {
                "username": username, "reason": reason, "source": source,
                "last_comment": content[:500], "api_blocked": blocked,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "warned_at": warned_at, "warning_reason": user.get("warning_reason"),
                "warning_count": warning_count, "warnings": user.get("warnings", []),
                "evidence": [w.get("evidence") for w in user.get("warnings", [])] + [event],
                "owner_notified": False,
            }
            log[mid] = record
            self.save("data/block_log.json", log)
            user["blocked"] = blocked
        self.save("data/moderation.json", state)
        return True

    def notify_owner(self, config, send):
        owner = str(config.get("OWNER_MID", "") or "")
        if not owner or owner == "0":
            return
        log = self.load("data/block_log.json", {})
        for mid, entry in log.items():
            if entry.get("owner_notified") is not False:
                continue
            status = "已拉黑" if entry.get("api_blocked") else "拉黑失败，违规内容已隔离"
            evidence = entry.get("evidence") or []
            detail = "\n".join(f"{e['source']}：{e['content'][:200]}" for e in evidence if e)
            text = (f"【主动防护日志】{status}\n用户：{entry['username']}（UID {mid}）"
                    f"\n时间：{entry['time']}\n原因：{entry['reason']}"
                    f"\n警告时间：{entry['warned_at']}\n证据摘要：\n{detail}")
            if send(config, owner, text):
                entry["owner_notified"] = True
                self.save("data/block_log.json", log)
