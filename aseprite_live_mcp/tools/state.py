"""In-process cache of the most recent results, surfaced as MCP resources.

The QA and Unity-export tools stash their last result here; ``tools/resources.py``
reads it so a client can poll ``aseprite://qa/last`` / ``aseprite://export/last``
without spending a fresh tool call. Process-local and best-effort — it resets when
the server restarts.
"""
from __future__ import annotations

from typing import Any

_LAST: dict[str, Any] = {"qa": None, "export": None}


def set_last(kind: str, value: Any) -> None:
    _LAST[kind] = value


def get_last(kind: str) -> Any:
    return _LAST.get(kind)
