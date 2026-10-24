"""Persona-owned state, with a stable context for each request/background job."""
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import shutil
import tempfile
import threading

_persona = ContextVar("persona", default=None)
_lock = threading.RLock()
# Account delivery cursors/scheduling stay shared to avoid sending old messages again.
SHARED = {"personas.json", "installed_presets.json", "replied.json", "commented_videos.json",
          "private_message_state.json", "mentions.json", "schedule_today.json"}
PERSONAL_KEYS = {"BOT_NAME", "BOT_AVATAR", "USER_AVATAR", "BOT_WELCOME",
                 "BOT_SUBTITLE", "OWNER_NAME", "DYNAMIC_TOPICS", "PREFERRED_TIDS",
                 "PROACTIVE_FOLLOW_UIDS"}


def personal_key(key):
    return key in PERSONAL_KEYS or key.startswith("PROMPT_") or key.startswith("LEVEL_PROMPT_")


def root():
    return Path(os.environ.get("BILI_STATE_DIR") or Path(__file__).resolve().parent)


def valid_name(name):
    return isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9_]+", name) is not None


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def state_lock():
    """Cross-process lock for migration and configuration read/modify/write."""
    with _lock:
        root().mkdir(parents=True, exist_ok=True)
        with open(root() / ".persona-state.lock", "a+b") as stream:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                if not stream.read(1):
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def active_persona():
    pinned = _persona.get()
    if pinned is not None:
        return pinned
    name = read_json(root() / "config.json", {}).get("ACTIVE_PERSONA", "default")
    return name if valid_name(name) else "default"


def bind_persona(name=None):
    name = name or active_persona()
    if not valid_name(name):
        raise ValueError("Invalid persona name")
    return _persona.set(name)


def release_persona(token):
    _persona.reset(token)


def persona_dir(name=None):
    name = name or active_persona()
    if not valid_name(name):
        raise ValueError("Invalid persona name")
    directory = root() / "data" / "persona_data" / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def data_path(path):
    """Route legacy data/... callers through the current persona."""
    path = Path(path)
    if path.is_absolute() or not path.parts or path.parts[0] != "data":
        return path
    if len(path.parts) < 2 or path.parts[1] in SHARED:
        return root() / path
    return persona_dir().joinpath(*path.parts[1:])


def load_json(path, default):
    return read_json(data_path(path), default)


def save_json(path, value):
    write_json(data_path(path), value)


def initialize(cfg):
    """Copy old state to the previously active persona once; keep originals intact."""
    marker = root() / "data" / "persona_migration.json"
    with state_lock():
        if marker.exists():
            return
        name = cfg.get("ACTIVE_PERSONA", "default")
        if not valid_name(name):
            name = "default"
        target = persona_dir(name)
        for source in (root() / "data").iterdir():
            if source.name in SHARED | {"persona_data", marker.name}:
                continue
            destination = target / source.name
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            elif source.is_file():
                shutil.copy2(source, destination)
        write_json(target / "settings.json", {k: v for k, v in cfg.items() if personal_key(k)})
        write_json(marker, {"version": 1, "legacy_owner": name})


def effective_config(cfg, defaults):
    result = dict(cfg)
    for key in list(result):
        if personal_key(key):
            result[key] = defaults.get(key, "")
    name = active_persona()
    personas = read_json(root() / "data" / "personas.json", [])
    current = next((p for p in personas if p.get("name") == name), {})
    result["BOT_NAME"] = current.get("display_name") or defaults.get("BOT_NAME", "Bot")
    result.update(read_json(persona_dir(name) / "settings.json", {}))
    result["ACTIVE_PERSONA"] = name
    return result
