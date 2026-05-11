"""Environment-driven configuration for the BG3 audio pipeline."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()  # optional .env loader
except ModuleNotFoundError:
    pass


def env_path(key: str) -> Path | None:
    """Return a path from environment variable *key*, or ``None`` if unset."""
    value = os.getenv(key)
    if not value:
        return None
    return Path(value).expanduser()


def require_env_path(key: str, value: Path | None) -> Path:
    """Return *value* or abort with a clear env error."""
    if value is None:
        sys.exit(f"[env-error] Define {key} in .env (see .env.example).")
    return value


WWISER_PY = env_path("WWISER_PY")
VGMSTREAM_DIR = env_path("VGMSTREAM_DIR")
UNPACKED_DATA = env_path("UNPACKED_DATA")
AUDIO_CONVERTED = env_path("AUDIO_CONVERTED")
AUDIO_LABELED = env_path("AUDIO_LABELED")
SIDS_WIKI = env_path("SIDS_WIKI")

# progress-bar preference: "auto" | "alive" | "basic"
PROGRESS_BAR_MODE = os.getenv("PROGRESS_BAR_MODE", "auto").lower()
