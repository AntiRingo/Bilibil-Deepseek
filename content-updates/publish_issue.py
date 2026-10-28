"""Publish the explicitly approved issue once; keep a durable receipt."""
import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

root = Path('/var/lib/bilibili-bot')
folder = root / 'content-updates'
cfg = json.loads((root / 'config.json').read_text())
keys = ['BOT_NAME', 'DEDE_USER_ID', 'ACTIVE_PERSONA', 'ENABLE_COMMENT_MEMES', 'ENABLE_PRIVATE_MESSAGES', 'ENABLE_MENTION_REPLIES', 'ENABLE_PROACTIVE', 'ENABLE_DYNAMIC', 'ENABLE_WEB_SEARCH']
headers = {'Cookie': f"SESSDATA={cfg['SESSDATA']}; bili_jct={cfg['BILI_JCT']}; DedeUserID={cfg['DEDE_USER_ID']}", 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com'}
if sys.argv[1] == 'check':
    print(json.dumps({k: cfg.get(k) for k in keys}, ensure_ascii=False))
    r = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers, timeout=30).json()
    d = r.get('data', {})
    print(json.dumps({'code': r.get('code'), 'isLogin': d.get('isLogin'), 'mid': d.get('mid'), 'uname': d.get('uname')}, ensure_ascii=False))
elif sys.argv[1] == 'refresh':
    import os
    import io
    import contextlib
    os.environ['BILI_STATE_DIR'] = str(root)
    sys.path.insert(0, '/opt/bilibili-bot/current/bilibili-ai-bot')
    import config
    with contextlib.redirect_stdout(io.StringIO()):
        ok, message = config.refresh_bili_cookie()
    print(json.dumps({'success': ok, 'message': message}, ensure_ascii=False))
elif sys.argv[1] == 'publish':
    content = (folder / '2026-10-23-publish.txt').read_text(encoding='utf-8-sig').strip()
    receipt = folder / 'vol001-receipt.json'
    record = {'title': content.splitlines()[0], 'sha256': hashlib.sha256(content.encode()).hexdigest(), 'started_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'status': 'sending', 'text': content}
    with receipt.open('x', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    data = {'dynamic_id': 0, 'type': 4, 'rid': 0, 'content': content, 'up_choose_comment': 0, 'up_close_comment': 0, 'extension': '{"emoji_type":1,"from":{"emoji_type":1},"flag_cfg":{}}', 'at_uids': '', 'ctrl': '[]', 'csrf_token': cfg['BILI_JCT'], 'csrf': cfg['BILI_JCT']}
    try:
        result = requests.post('https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/create', headers=headers, data=data, timeout=60).json()
        record['response'] = result
        record['status'] = 'published' if result.get('code') == 0 else 'rejected'
        record['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        d = result.get('data', {})
        dynamic_id = d.get('dynamic_id_str') or d.get('dynamic_id')
        if dynamic_id:
            record['url'] = f'https://t.bilibili.com/{dynamic_id}'
    except Exception as exc:
        record['status'] = 'uncertain'
        record['error'] = type(exc).__name__
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k != 'text'}, ensure_ascii=False))
