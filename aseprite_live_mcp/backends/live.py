"""Live backend — runs Lua inside the artist's *running* Aseprite via the relay.

Talks to bridge/relay_server.py over localhost HTTP (stdlib only, no extra deps).
Operates on the editor's active document; ``file``/``save`` are ignored here.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import ExecResult


class LiveBackend:
    name = "live"

    def __init__(self, relay_url: str, timeout: float):
        self.relay_url = relay_url
        self.timeout = timeout

    def exec(self, lua: str, *, file: str | None = None, save: bool = False) -> ExecResult:
        try:
            req = urllib.request.Request(
                self.relay_url + "/exec",
                data=lua.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout + 15) as r:
                payload = json.loads(r.read().decode("utf-8"))
            return ExecResult(
                ok=bool(payload.get("ok")),
                result=payload.get("result") or "",
                error=payload.get("error") or "",
            )
        except urllib.error.URLError as e:
            return ExecResult(
                ok=False,
                error=(
                    f"relay unreachable at {self.relay_url} ({e.reason}). Start "
                    "bridge/relay_server.py, then in Aseprite run File > Scripts > "
                    "claude-bridge."
                ),
            )
        except Exception as e:  # pragma: no cover - defensive
            return ExecResult(ok=False, error=f"live exec failed: {e}")

    def health(self) -> dict:
        try:
            with urllib.request.urlopen(self.relay_url + "/status", timeout=5) as r:
                info = json.loads(r.read().decode("utf-8"))
            info.setdefault("backend", "live")
            return info
        except Exception as e:
            return {"backend": "live", "connected": False, "error": str(e)}
