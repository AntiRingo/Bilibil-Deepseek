"""Offline integration checks. Never import live config or contact an external API."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1]


class PersonaIsolationTests(unittest.TestCase):
    def test_switch_migration_files_settings_and_inflight_request(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, BILI_STATE_DIR=directory, PYTHONPATH=str(APP),
                       CHAT_PASSWORD="persona-test-password", PYTHONIOENCODING="utf-8",
                       BILI_PRODUCTION="0")
            result = subprocess.run([sys.executable, "-c", r'''
import io
import json
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

Path("data/images").mkdir(parents=True)
Path("config.json").write_text(json.dumps({"ACTIVE_PERSONA":"legacy", "BOT_NAME":"Old name"}))
Path("data/personas.json").write_text(json.dumps([{"name":"legacy", "display_name":"Legacy"}]))
Path("data/memory.json").write_text('[{"text":"old memory"}]')
Path("data/local_chat.json").write_text('[{"role":"user","content":"old chat"}]')
Path("data/images/old.png").write_bytes(b"old image")
with patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")):
    from wsgi import app, module
    import config
    from persona_storage import load_json, save_json, data_path, active_persona, initialize

    # Hold an actual Flask request open while another client switches personas.
    started, finish = Event(), Event()
    @app.route('/api/test_slow', methods=['POST'])
    def slow():
        old = active_persona()
        started.set()
        assert finish.wait(10)
        assert config.get_raw_config()['ACTIVE_PERSONA'] == old
        save_json('data/inflight.json', {'owner': old})
        return {'ok':True}

    client = app.test_client()
    client.post('/api/login', json={"password":"persona-test-password"})
    presets = client.get('/api/personas').json['personas']
    angelina = next(p for p in presets if p['name'] == 'angelina')
    assert '博士' in angelina['owner_prompt'] and '尚未明确说出口' in angelina['system_prompt']
    assert client.post('/api/personas/switch', json={'name':'angelina'}).json['ok']
    assert client.get('/api/chat/history').json['history'] == []
    assert client.get('/api/branding').json['bot_name'] == '安洁莉娜'
    assert client.get('/api/life').json['life']['current']['location'] == '罗德岛本舰'
    schedule = client.get('/api/schedule/today').json
    assert schedule['dynamic_time'] == '21:30' and schedule['timezone'] == 'Asia/Shanghai'
    import dynamic
    import angelina_life
    from types import SimpleNamespace
    from unittest.mock import Mock
    life = angelina_life.timeline()
    candidate = '今天忙完以后，捧着杯子看热气一点点散掉，忽然觉得这样发一小会儿呆也很好。刚才还惦记着背包里的东西有没有收好，坐下来才终于松了口气。博士，你今天有没有遇到一点让自己开心的小事？'
    def completion(text):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    fake = Mock()
    fake.with_options.return_value = fake
    fake.chat.completions.create.side_effect = [completion(json.dumps({'text':candidate})), completion('{"approved":true}')]
    with patch.object(dynamic, 'or_client', fake):
        assert dynamic.generate_angelina_diary(life) == candidate
    fake.chat.completions.create.side_effect = [completion(json.dumps({'text':candidate})), completion('{"approved":false}')]
    with patch.object(dynamic, 'or_client', fake):
        assert dynamic.generate_angelina_diary(life) == angelina_life.fallback(life)
    fake.chat.completions.create.side_effect = TimeoutError
    with patch.object(dynamic, 'or_client', fake):
        assert dynamic.generate_angelina_diary(life) == angelina_life.fallback(life)
    with patch.object(dynamic, 'post_dynamic_text') as publish:
        config.update_config({'ENABLE_DYNAMIC':False})
        assert dynamic._run_for_persona() is False
        publish.assert_not_called()
        config.update_config({'ENABLE_DYNAMIC':True})
    assert config.get_raw_config()['OWNER_NAME'] == '博士'
    assert client.get('/api/permanent/list').json['items'] == []
    assert client.post('/api/personas/switch', json={'name':'legacy'}).json['ok']
    assert client.get('/api/branding').json['bot_name'] == 'Old name'
    assert client.get('/api/life').json['life'] is None
    assert client.get('/api/chat/history').json['history'][0]['content'] == 'old chat'
    assert client.get('/data/images/old.png').data == b'old image'
    assert Path('data/memory.json').exists()  # migration preserves source
    for filename, value in [('affection.json', {'1':80}), ('mood.json', {'mood':'happy'}),
                            ('user_profiles.json', {'1':{'facts':['private fact']}}),
                            ('personality_evolution.json', {'evolved_traits':[]})]:
        save_json('data/' + filename, value)
    client.post('/api/permanent/add', json={'text':'only legacy'})
    created = client.post('/api/personas/create', json={'name':'test_angelina', 'display_name':'安洁莉娜'})
    assert created.json['ok'], created.json
    assert client.post('/api/personas/switch', json={'name':'../../escape'}).status_code == 404

    replies = []
    def worker():
        worker_client = app.test_client()
        worker_client.post('/api/login', json={'password':'persona-test-password'})
        replies.append(worker_client.post('/api/test_slow').status_code)
    thread = Thread(target=worker)
    thread.start()
    assert started.wait(5)
    assert client.post('/api/personas/switch', json={'name':'test_angelina'}).json['ok']
    finish.set()
    thread.join(10)
    assert replies == [200]
    assert load_json('data/inflight.json', {}) == {}
    assert client.get('/api/branding').json['bot_name'] == '安洁莉娜'
    assert client.get('/api/chat/history').json['history'] == []
    assert client.get('/api/permanent/list').json['items'] == []
    for filename in ['memory.json', 'affection.json', 'mood.json', 'user_profiles.json', 'personality_evolution.json']:
        assert not data_path('data/' + filename).exists(), filename
    assert client.get('/data/images/old.png').status_code == 404
    assert client.get('/data/persona-images/legacy/old.png').status_code == 404
    assert client.post('/api/permanent/add', headers={'X-Persona':'legacy'}, json={'text':'stale'}).status_code == 409
    assert client.post('/api/config/update', json={'ACTIVE_PERSONA':'legacy'}).status_code == 400
    assert client.post('/api/config/update', json={'BOT_NAME':'Angel', 'BOT_AVATAR':'🌸', 'OR_API_KEY':'fake-shared-key', 'PROMPT_IMAGINE':'new persona prompt'}).json['ok']
    image = client.post('/api/upload_image', data={'image':(io.BytesIO(b'new image'), 'new.png')}).json
    assert client.get(image['url']).data == b'new image'
    save_json('data/local_chat.json', [{'role':'assistant', 'content':'new chat'}])
    save_json('data/mood.json', {'mood':'calm'})
    client.post('/api/permanent/add', json={'text':'only test_angelina'})
    assert client.post('/api/personas/switch', json={'name':'legacy'}).json['ok']
    assert client.get(image['url']).status_code == 404
    assert client.get('/api/branding').json['bot_name'] == 'Old name'
    assert config.get_raw_config()['OR_API_KEY'] == 'fake-shared-key'
    assert config.get_raw_config()['PROMPT_IMAGINE'] == ''
    assert load_json('data/inflight.json', {})['owner'] == 'legacy'
    assert load_json('data/mood.json', {})['mood'] == 'happy'
    assert client.get('/api/permanent/list').json['items'][0]['text'] == 'only legacy'
    initialize(config.get_raw_config())  # never re-import stale legacy files
    assert client.post('/api/personas/switch', json={'name':'test_angelina'}).json['ok']
    assert client.get('/api/branding').json['bot_name'] == 'Angel'
    assert client.get('/api/chat/history').json['history'][0]['content'] == 'new chat'
    assert load_json('data/mood.json', {})['mood'] == 'calm'
    assert client.get('/api/permanent/list').json['items'][0]['text'] == 'only test_angelina'
    page = client.get('/').get_data(as_text=True)
    assert 'id="personaQuickSwitch"' in page and 'const PAGE_PERSONA = "test_angelina"' in page
    assert client.post('/api/personas/delete', json={'name':'test_angelina'}).json['ok']
    assert config.get_raw_config()['ACTIVE_PERSONA'] == 'default'
    assert not client.post('/api/personas/create', json={'name':'test_angelina'}).json.get('ok')
    from persona_presets import ensure_builtin_personas
    assert client.post('/api/personas/update', json={'name':'angelina','style_prompt':'custom style'}).json['ok']
    ensure_builtin_personas()
    assert next(p for p in client.get('/api/personas').json['personas'] if p['name']=='angelina')['style_prompt'] == 'custom style'
    client.post('/api/personas/delete', json={'name':'angelina'})
    ensure_builtin_personas()
    assert not any(p['name']=='angelina' for p in client.get('/api/personas').json['personas'])

'''], env=env, cwd=directory, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
