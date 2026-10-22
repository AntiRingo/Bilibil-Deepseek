"""Offline deployment checks: always use temporary state, never real credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def run_isolated(self, code, state, production=False, secret="test-secret-" * 4):
        env = os.environ.copy()
        env.update(PYTHONPATH=str(APP), BILI_STATE_DIR=str(state),
                   BILI_PRODUCTION="1" if production else "0", SECRET_KEY=secret,
                   CHAT_PASSWORD="test-password-long-enough", PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                cwd=state, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_config_boots_and_private_paths_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_isolated('''
from pathlib import Path
from unittest.mock import patch
with patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")):
    from wsgi import app
    import config
    assert Path(config.CONFIG_FILE).parent == Path.cwd()
    assert Path("data/images").is_dir()
    Path("data/images/private.png").write_bytes(b"private image")
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json["ok"] is True
    for path in ["/config.json", "/config.py", "/data/memory.json", "/.git/config", "/cookies.txt"]:
        assert client.get(path).status_code == 404, path
    assert client.get("/api/config/raw").status_code == 401
    assert client.get("/data/images/private.png").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 403
    assert client.post("/api/login", json={"password": "test-password-long-enough"}).json["ok"]
    assert client.get("/data/images/private.png").data == b"private image"
    assert client.get("/data/images/../config.json").status_code == 404
    assert client.post("/api/config/update", json={"BOT_NAME": "test"}).json["ok"]
    assert client.post("/api/config/update", json={"CHAT_PASSWORD": "bad"}).status_code == 400
    assert client.post("/api/change_password", json={"old": "test-password-long-enough", "new": "short"}).status_code == 400
''', tmp, production=True)

    def test_state_survives_fresh_process_and_new_defaults_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            original = {"BOT_NAME": "server-name", "SESSDATA": "fake-cookie", "CUSTOM_SETTING": 42}
            (state / "config.json").write_text(json.dumps(original), encoding="utf-8")
            (state / "data").mkdir()
            (state / "data/memory.json").write_text('["keep-me"]', encoding="utf-8")
            before = (state / "config.json").read_bytes()
            for _ in range(2):
                self.run_isolated('''
import config
from wsgi import app
assert config.get_raw_config()["BOT_NAME"] == "server-name"
assert config.get_raw_config()["CUSTOM_SETTING"] == 42
assert "ENABLE_PRIVATE_MESSAGES" in config.get_raw_config()
''', tmp)
            self.assertEqual((state / "config.json").read_bytes(), before)
            self.assertEqual((state / "data/memory.json").read_text(), '["keep-me"]')

    def test_production_rejects_weak_secret_and_saved_default_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_isolated('''
try:
    import wsgi
except RuntimeError as e:
    assert "SECRET_KEY" in str(e)
else:
    raise AssertionError("weak secret accepted")
''', tmp, production=True, secret="weak")
            Path(tmp, "config.json").write_text('{"CHAT_PASSWORD":"admin()"}')
            self.run_isolated('''
try:
    import wsgi
except RuntimeError as e:
    assert "password" in str(e)
else:
    raise AssertionError("default password accepted")
''', tmp, production=True)


if __name__ == "__main__":
    unittest.main()
