"""Gunicorn entry point. Importing this module never starts the Bilibili bot."""
import importlib.util
import os
from pathlib import Path

if os.environ.get("BILI_PRODUCTION") == "1":
    if len(os.environ.get("SECRET_KEY", "")) < 32:
        raise RuntimeError("Production requires a persistent SECRET_KEY of at least 32 characters")

spec = importlib.util.spec_from_file_location("local_chat", Path(__file__).with_name("local-chat.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = module.app

if os.environ.get("BILI_PRODUCTION") == "1":
    if module.AUTH_PASSWORD == "admin()" or len(module.AUTH_PASSWORD) < 12:
        raise RuntimeError("Set a panel password of at least 12 characters before production startup")
