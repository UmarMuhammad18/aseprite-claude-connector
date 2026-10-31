"""Live backend — runs Lua inside the artist's *running* Aseprite via the relay.

Talks to the relay over localhost HTTP. If nothing answers, it starts the relay in
this process, so a server that outlives another session's relay takes over from it.
Operates on the editor's active document; ``file``/``save`` are ignored here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import ExecResult


class LiveBackend:
    name = "live"

    def __init__(self, relay_url: str, timeout: float, autostart: bool = False):
        self.relay_url = relay_url
        self.timeout = timeout
        self.autostart = autostart

    def _revive_relay(self, e: Exception) -> bool:
        """True if the relay was down and is worth trying again."""
        reason = getattr(e, "reason", e)
        if not self.autostart or not isinstance(reason, ConnectionError):
            return False
        from ..relay import ensure_running

        return ensure_running()

    def _post(self, lua: str) -> dict:
        req = urllib.request.Request(
            self.relay_url + "/exec",
            data=lua.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout + 15) as r:
            return json.loads(r.read().decode("utf-8"))

    def exec(self, lua: str, *, file: str | None = None, save: bool = False) -> ExecResult:
        try:
            try:
                payload = self._post(lua)
            except urllib.error.URLError as e:
                if not self._revive_relay(e):
                    raise
                payload = self._post(lua)
            return ExecResult(
                ok=bool(payload.get("ok")),
                result=payload.get("result") or "",
                error=payload.get("error") or "",
            )
        except urllib.error.URLError as e:
            return ExecResult(
                ok=False,
                error=(
                    f"relay unreachable at {self.relay_url} ({e.reason}). It normally "
                    "starts with this server; run python -m aseprite_claude_connector.relay "
                    "to see why it can't."
                ),
            )
        except Exception as e:  # pragma: no cover - defensive
            return ExecResult(ok=False, error=f"live exec failed: {e}")

    def _status(self) -> dict:
        with urllib.request.urlopen(self.relay_url + "/status", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def health(self) -> dict:
        try:
            try:
                info = self._status()
            except urllib.error.URLError as e:
                if not self._revive_relay(e):
                    raise
                info = self._status()
            info.setdefault("backend", "live")
            return info
        except Exception as e:
            return {"backend": "live", "connected": False, "error": str(e)}
