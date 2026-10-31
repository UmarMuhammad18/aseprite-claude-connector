"""Runtime configuration, all overridable by environment variables.

- ASEPRITE_MCP_BACKEND         : "live" (default) or "headless"
- ASEPRITE_RELAY_URL           : relay HTTP base for the live backend (default 127.0.0.1:9878)
- ASEPRITE_MCP_NO_RELAY        : set to stop the server starting the relay itself
  (also off when ASEPRITE_RELAY_URL points somewhere else)
- ASEPRITE_PATH                : path to the Aseprite executable (auto-detected if unset)
- ASEPRITE_MCP_TIMEOUT         : per-op timeout seconds (default 60)
- ASEPRITE_MCP_MAX_PIXELS      : most pixels one call may change (default 250000, 0 = no cap)
- ASEPRITE_MCP_NO_UPDATE_CHECK : set to disable the daily PyPI update check
  (see update_check.py; also auto-disabled when CI is set)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_RELAY_URL = "http://127.0.0.1:9878"
_DEFAULT_MAX_PIXELS = 250_000

_DEFAULT_ASEPRITE_PATHS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Aseprite\Aseprite.exe",
    r"C:\Program Files\Aseprite\Aseprite.exe",
    r"C:\Program Files (x86)\Aseprite\Aseprite.exe",
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
    relay_autostart: bool = False
    max_pixels: int = _DEFAULT_MAX_PIXELS


def _default_aseprite() -> str:
    for p in _DEFAULT_ASEPRITE_PATHS:
        if os.path.isfile(p):
            return p
    return "aseprite"  # rely on PATH


def load_config() -> Config:
    backend = os.environ.get("ASEPRITE_MCP_BACKEND", "live").strip().lower()
    if backend not in ("live", "headless"):
        backend = "live"
    relay = os.environ.get("ASEPRITE_RELAY_URL", _DEFAULT_RELAY_URL).rstrip("/")
    autostart = (
        backend == "live"
        and relay == _DEFAULT_RELAY_URL
        and not os.environ.get("ASEPRITE_MCP_NO_RELAY")
    )
    aseprite = os.environ.get("ASEPRITE_PATH") or _default_aseprite()
    try:
        timeout = float(os.environ.get("ASEPRITE_MCP_TIMEOUT", "60"))
    except ValueError:
        timeout = 60.0
    try:
        max_pixels = max(0, int(os.environ.get("ASEPRITE_MCP_MAX_PIXELS", _DEFAULT_MAX_PIXELS)))
    except ValueError:
        max_pixels = _DEFAULT_MAX_PIXELS
    return Config(
        backend=backend,
        relay_url=relay,
        aseprite_path=aseprite,
        exec_timeout=timeout,
        relay_autostart=autostart,
        max_pixels=max_pixels,
    )
