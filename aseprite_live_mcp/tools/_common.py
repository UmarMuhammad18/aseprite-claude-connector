"""Shared helpers for tool modules: run a Lua body and parse its result."""

from __future__ import annotations

import json

from ..backends import get_backend
from ..lua import build_lua


class ToolError(Exception):
    """Raised when Aseprite reports an error; surfaced to the model as isError."""


def run(
    body: str,
    *,
    mutates: bool = False,
    undo_label: str = "AI edit",
    file: str | None = None,
    save: bool | None = None,
):
    """Compose + execute a Lua tool body and return its parsed result.

    ``body`` must ``return`` a value (usually ``J({...})``). Mutating bodies are
    wrapped in ``app.transaction`` (one undo step). For the headless backend,
    ``file`` is the target sprite and ``save`` defaults to ``mutates``.
    """
    backend = get_backend()
    lua = build_lua(body, mutates=mutates, undo_label=undo_label)
    do_save = mutates if save is None else save
    res = backend.exec(lua, file=file, save=do_save)
    if not res.ok:
        raise ToolError(res.error or "unknown Aseprite error")
    return _parse(res.result)


def _parse(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def parse_color(c: str) -> tuple[int, int, int, int]:
    """Parse ``#rrggbb`` or ``#rrggbbaa`` into an (r, g, b, a) tuple 0-255."""
    h = c.strip().lstrip("#")
    if len(h) == 6:
        h += "ff"
    if len(h) != 8:
        raise ToolError(f"bad color '{c}', expected #rrggbb or #rrggbbaa")
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    except ValueError:
        raise ToolError(f"bad color '{c}', expected hex digits") from None
