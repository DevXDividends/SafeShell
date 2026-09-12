"""
settings.py — Persistent user settings for SafeShell's AI backends.

Design principle (explicit opt-in, not auto-detection):
- Fresh install / first run = groq_enabled=False, local_llm_enabled=False.
  No API key, no local model use, EVER, until the user explicitly turns it on
  via `safeshell settings`.
- Heuristic (rule-based) fallback can NEVER be disabled — it's the safety net.
- Settings persist in ~/.safeshell/settings.json across runs.

This replaces the old "ask for consent mid-run" flow — now everything is
configured ahead of time, once, through an explicit menu.
"""

import json
import os

from .config import BASE_DIR

SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "groq_enabled": False,
    "groq_api_key": None,
    "local_llm_enabled": False,
    "local_llm_model": None,  # None = use the built-in default (gemma3:4b)
}


def load_settings() -> dict:
    """Settings file se load karo; missing keys defaults se fill ho jaate hain."""
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
            settings.update(saved)
        except (json.JSONDecodeError, OSError):
            pass  # corrupt file — fall back to defaults silently
    return settings


def save_settings(settings: dict):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def reset_settings():
    """Sab kuch wapas heuristic-only default state pe le aao."""
    save_settings(dict(DEFAULT_SETTINGS))