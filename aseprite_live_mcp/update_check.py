"""Polite update awareness: know when a newer release exists.

Design constraints (in order):
- NEVER blocks or delays server startup or any tool call — the network fetch runs
  on a daemon thread and results land whenever they land.
- Offline-safe and failure-silent: no network, no PyPI, bad JSON → no noise.
- At most one network check per 24h, cached on disk.
- Opt-out: set ``ASEPRITE_MCP_NO_UPDATE_CHECK=1`` (any non-empty value). Also
  auto-disabled under CI (the conventional ``CI`` env var).
- Dependency-free: stdlib urllib + a 3-part numeric version compare (our releases
  are plain X.Y.Z; anything unparseable compares as "no update").

Surfaces: the ``status`` tool (first call every agent makes), the
``aseprite://update`` resource, and a single stderr line at startup-check time
(stderr is the MCP-safe log channel; stdout belongs to the protocol).
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request

from . import __version__

_PYPI_URL = "https://pypi.org/pypi/aseprite-live-mcp/json"
_CACHE_TTL = 24 * 60 * 60  # one network check per day, tops
_FETCH_TIMEOUT = 4.0

# Filled in by the background thread (or from a fresh cache) — read by status().
_LOCK = threading.Lock()
_LATEST: str | None = None


def enabled() -> bool:
    return not (os.environ.get("ASEPRITE_MCP_NO_UPDATE_CHECK") or os.environ.get("CI"))


def _cache_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "aseprite-live-mcp", "update_check.json")


def _read_cache() -> dict | None:
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            data = json.load(f)
        if (
            isinstance(data, dict)
            and isinstance(data.get("latest"), str)
            and isinstance(data.get("checked_at"), (int, float))
        ):
            return data
    except Exception:
        pass
    return None


def _write_cache(latest: str) -> None:
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"checked_at": time.time(), "latest": latest}, f)
    except Exception:
        pass


def _ver_tuple(v: str) -> tuple[int, ...] | None:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v.strip())
    return tuple(int(p) for p in m.groups()) if m else None


def is_newer(latest: str, current: str = __version__) -> bool:
    lt, ct = _ver_tuple(latest), _ver_tuple(current)
    return lt is not None and ct is not None and lt > ct


def _set_latest(latest: str, announce: bool) -> None:
    global _LATEST
    with _LOCK:
        _LATEST = latest
    if announce and is_newer(latest):
        print(
            f"[aseprite-live-mcp] update available: {__version__} -> {latest} "
            f"(pip install -U aseprite-live-mcp / uvx aseprite-live-mcp@latest). "
            f"Set ASEPRITE_MCP_NO_UPDATE_CHECK=1 to silence this check.",
            file=sys.stderr,
        )


def _fetch_and_store() -> None:
    try:
        req = urllib.request.Request(
            _PYPI_URL, headers={"User-Agent": f"aseprite-live-mcp/{__version__} update-check"}
        )
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            data = json.load(resp)
        latest = data["info"]["version"]
        if isinstance(latest, str) and latest:
            _write_cache(latest)
            _set_latest(latest, announce=True)
    except Exception:
        pass  # offline / PyPI down / weird JSON — stay quiet


def start_background_check() -> None:
    """Kick off the (at most daily) update check without ever blocking startup."""
    if not enabled():
        return
    cached = _read_cache()
    if cached and (time.time() - float(cached.get("checked_at", 0))) < _CACHE_TTL:
        _set_latest(cached["latest"], announce=True)
        return
    threading.Thread(target=_fetch_and_store, name="update-check", daemon=True).start()


def get_update_info() -> dict:
    """The ``update`` block for the status tool / resource."""
    if not enabled():
        return {"current": __version__, "check": "disabled"}
    with _LOCK:
        latest = _LATEST
    if latest is None:
        return {"current": __version__, "check": "pending"}
    info: dict = {"current": __version__, "latest": latest, "update_available": is_newer(latest)}
    if info["update_available"]:
        info["how"] = (
            "pip install -U aseprite-live-mcp (uvx users: run uvx aseprite-live-mcp@latest "
            "once — uvx reuses its cached version otherwise)"
        )
    return info
