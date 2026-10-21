"""Options for short replies with a small completion token budget."""


def short_response_options(model):
    # DeepSeek defaults to thinking: it can exhaust our 400/600 token budget
    # before producing any content. Disable thinking for short bot responses.
    # https://api-docs.deepseek.com/guides/thinking_mode/
    name = str(model or "").rsplit("/", 1)[-1].lower()
    if name in {"deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash"}:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}
