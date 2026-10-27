"""Shared conversation pacing and paragraph handling."""
import re


CONVERSATION_PROMPT = """【对话节奏】
先结合上下文理解对方整段话的重点、情绪和意图，再组织一次连贯的回应。
不要对方说一句就机械地对应回答一句，不逐句复述，不逐项接话；明确提出的问题仍需回答。
可以自然补充自己的感受或相关想法，但不要每次都追问，也不要为了延长聊天硬找话题。
短回复一段即可；内容有自然转折或补充时，可以分成2–3个简短段落，用空行分隔。
每段表达一个完整意思，不要把每句话、语气词拆成单独一段，不加段落编号。"""


def split_reply(text):
    """Keep semantic paragraphs, bounding outgoing bubbles without losing text."""
    parts = [part.strip() for part in re.split(r"\n\s*\n", str(text or "").strip()) if part.strip()]
    return parts[:2] + ["\n\n".join(parts[2:])] if len(parts) > 3 else parts


def group_messages(messages):
    """Group only messages in the same sender/session, preserving receive order."""
    groups = {}
    for message in messages:
        key = (str(message["sender_uid"]), message["session_type"], message["talker_id"])
        groups.setdefault(key, []).append(message)
    result = []
    for items in groups.values():
        merged = dict(items[-1])
        merged["content"] = "\n\n".join(item["content"] for item in items)
        result.append(merged)
    return result
