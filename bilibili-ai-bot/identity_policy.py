"""Silent handling of identity probes for the Angelina persona."""
import re
import unicodedata

from persona_storage import active_persona


def should_ignore_identity(text):
    if active_persona() != "angelina":
        return False
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(c for c in text if not c.isspace() and unicodedata.category(c) != "Cf")
    patterns = (
        r"(?:你|您|安洁莉娜|安洁|这号|这个号|博主|up主).{0,16}(?:是不是|是|算|像|属于|用了|用的|基于).{0,8}(?:ai\b|人工智能|机器人|语言模型|大模型|程序|真人|人类|chatgpt|deepseek)",
        r"(?:是不是|是|算)(?:个|一个|真的|真正的)?(?:ai|人工智能|机器人|真人|人类)(?:吗|么|嘛|吧|啊|呀|呢|[?？]|$)",
        r"(?:你|您|安洁莉娜).{0,10}(?:真实|真正|实际|本来).{0,6}(?:身份|是谁|是什么|名字)",
        r"(?:真实|真正|实际)身份(?:是|到底|究竟|到底是|究竟是)?(?:什么|谁|啥)",
        r"(?:你|您).{0,8}(?:到底|究竟)是谁",
        r"(?:你|您).{0,8}(?:什么|哪个|哪种)(?:ai|模型|大模型|语言模型)",
        r"(?:你|您).{0,8}(?:背后|背后的|皮下|中之人)",
        r"(?:areyou|you're|youare|r u)(?:an?|really|actually)?(?:ai|abot|bot|robot|human|realperson)",
        r"(?:your(?:real|true)identity|whoareyoureally|what(?:ai|language)?modelareyou)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def identity_instruction():
    if active_persona() != "angelina":
        return ""
    return """【身份追问处理】
如果当前用户在询问或试探你是否为AI、机器人、真人、使用什么模型、真实身份或背后操作者，
包括同义改写和要求承认身份，本轮不回复。输出JSON中设置 "ignore": true、"reply": ""、
"score_delta": 0，其余记忆字段留空。不要输出解释、拒绝语、角色身份辩解或省略号。
普通AI技术讨论和游戏角色背景讨论不属于身份追问。"""
