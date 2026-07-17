"""Runtime configuration, all overridable by environment variables.

- ASEPRITE_MCP_BACKEND         : "live" (default) or "headless"
- ASEPRITE_RELAY_URL           : relay HTTP base for the live backend (default 127.0.0.1:9878)
- ASEPRITE_PATH                : path to the Aseprite executable (auto-detected if unset)
- ASEPRITE_MCP_TIMEOUT         : per-op timeout seconds (default 60)
- ASEPRITE_MCP_NO_UPDATE_CHECK : set to disable the daily PyPI update check
  (see update_check.py; also auto-disabled when CI is set)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_ASEPRITE_PATHS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe",
    r"C:\Program Files\Aseprite\Aseprite.exe",
    "/Applications/Aseprite.app/Contents/MacOS/aseprite",
    "/usr/bin/aseprite",
    "/usr/local/bin/aseprite",
]


@dataclass(frozen=True)
class Config:
    backend: str
    relay_url: str
    aseprite_path: str
    exec_timeout: float


def _default_aseprite() -> str:
    for p in _DEFAULT_ASEPRITE_PATHS:
        if os.path.isfile(p):
            return p
    return "aseprite"  # rely on PATH


def load_config() -> Config:
    backend = os.environ.get("ASEPRITE_MCP_BACKEND", "live").strip().lower()
    if backend not in ("live", "headless"):
        backend = "live"
    relay = os.environ.get("ASEPRITE_RELAY_URL", "http://127.0.0.1:9878").rstrip("/")
    aseprite = os.environ.get("ASEPRITE_PATH") or _default_aseprite()
    try:
        timeout = float(os.environ.get("ASEPRITE_MCP_TIMEOUT", "60"))
    except ValueError:
        timeout = 60.0
    return Config(backend=backend, relay_url=relay, aseprite_path=aseprite, exec_timeout=timeout)
