from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExecResult:
    ok: bool
    result: str = ""
    error: str = ""


class Backend(Protocol):
    name: str

    def exec(self, lua: str, *, file: str | None = None, save: bool = False) -> ExecResult:
        """Run a full Lua chunk and return its string result.

        ``file`` and ``save`` are honored by the headless backend (which loads the
        file as the active sprite and optionally saves it back); the live backend
        ignores them and operates on the editor's active document.
        """
        ...

    def health(self) -> dict:
        ...
