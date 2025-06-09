"""Environment-driven configuration for the BG3 audio pipeline."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()          # optional .env loader
except ModuleNotFoundError:
    pass


def _env_path(key: str) -> Path:
    """Resolve *key* to an absolute Path or abort.

    Args:
        key: Name of the environment variable.

    Returns:
        Absolute Path from the variable value.

    Raises:
        SystemExit: If the variable is unset or empty.
    """
    value = os.getenv(key)
    if not value:
        sys.exit(f"[env-error] Define {key} in .env (see .env.example).")
    return Path(value)


# absolute paths
WWISER_PY = _env_path("WWISER_PY")
VGMSTREAM_DIR = _env_path("VGMSTREAM_DIR")
UNPACKED_DATA = _env_path("UNPACKED_DATA")
AUDIO_CONVERTED = _env_path("AUDIO_CONVERTED")
SIDS_WIKI = _env_path("SIDS_WIKI")

# progress-bar preference: "auto" | "alive" | "basic"
PROGRESS_BAR_MODE = os.getenv("PROGRESS_BAR_MODE", "auto").lower()

# pipeline toggles
SHOULD_CONVERT = True
SHOULD_DECODE_BANKS = True
SHOULD_GROUP = True
SHOULD_RENAME = True
