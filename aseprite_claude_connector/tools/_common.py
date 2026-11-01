"""Shared helpers for tool modules: run a Lua body and parse its result."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..backends import get_backend
from ..config import load_config
from ..lua import CHANGES_MARK, build_lua


class ToolError(Exception):
    """Raised when Aseprite reports an error; surfaced to the model as isError."""


class Captured(Exception):
    """Raised instead of running a mutating body while ``edit_batch`` collects steps."""

    def __init__(self, body: str):
        self.body = body


@dataclass
class Rails:
    """Safety rails for this server process, set with ``set_safety_rails``."""

    dry_run: bool = False
    max_pixels: int | None = None  # None until first use: the config default
    capturing: bool = False

    def cap(self) -> int:
        if self.max_pixels is None:
            self.max_pixels = load_config().max_pixels
        return self.max_pixels


rails = Rails()

JOURNAL_LIMIT = 500

# Every edit this server process made, oldest first, for change_summary and
# explain_changes. It's kept here rather than in Aseprite so it survives the headless
# backend, where each call is its own process.
journal: list[dict] = []
# Called with the sprite file after each edit; the session recorder hangs off this.
after_edit: list[Callable[[str | None], None]] = []

# Effects a rolled-back transaction can't undo: files, and which documents are open.
_OUTSIDE_THE_SPRITE = re.compile(
    r"saveAs|saveCopyAs|SaveFile|ExportSpriteSheet|ExportTileset|app\.open\("
    r"|\bs:close\(\)|Sprite\(W|app\.command\.(Undo|Redo)"
)


def refuse_in_dry_run(what: str = "this tool") -> None:
    if rails.dry_run:
        raise ToolError(f"dry run: {what} can't be rehearsed, so it was not run.")


def run(
    body: str,
    *,
    mutates: bool = False,
    undo_label: str = "AI edit",
    file: str | None = None,
    save: bool | None = None,
    batchable: bool = False,
    capped: bool = True,
):
    """Compose + execute a Lua tool body and return its parsed result.

    ``body`` must ``return`` a value (usually ``J({...})``). Mutating bodies are
    wrapped in ``app.transaction`` (one undo step). For the headless backend,
    ``file`` is the target sprite and ``save`` defaults to ``mutates``. ``batchable``
    lets a tool that edits nothing still take part in ``edit_batch``. ``capped=False``
    skips the pixel cap for an edit that can't lose pixels.
    """
    if _OUTSIDE_THE_SPRITE.search(body):
        if rails.capturing:
            raise ToolError("this tool does more than edit the sprite, so it can't be batched")
        refuse_in_dry_run()
    if rails.capturing and (mutates or batchable):
        raise Captured(body)
    backend = get_backend()
    lua = build_lua(
        body,
        mutates=mutates,
        undo_label=undo_label,
        dry_run=rails.dry_run,
        max_pixels=rails.cap() if capped else 0,
    )
    do_save = (mutates if save is None else save) and not rails.dry_run
    res = backend.exec(lua, file=file, save=do_save)
    if not res.ok:
        raise ToolError(res.error or "unknown Aseprite error")
    changes, result = _split_changes(res.result)
    if mutates and not rails.dry_run:
        _note_edit(undo_label, changes, file)
    return _parse(result)


def _split_changes(result: str | None) -> tuple[dict | None, str | None]:
    """Part the journal report from the tool's own result. A rail-less edit has none."""
    if not result or not result.startswith(CHANGES_MARK):
        return None, result
    report, _, rest = result[len(CHANGES_MARK) :].partition(CHANGES_MARK)
    try:
        return json.loads(report), rest
    except ValueError:
        return None, rest


def _note_edit(label: str, changes: dict | None, file: str | None) -> None:
    journal.append({"label": label, "at": time.time(), **(changes or {})})
    del journal[:-JOURNAL_LIMIT]
    for hook in after_edit:
        hook(file)


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
