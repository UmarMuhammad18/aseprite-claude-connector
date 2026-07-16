"""Typed return shapes for the flagship tools.

Annotating a tool's return with one of these makes FastMCP publish an
``outputSchema`` in ``tools/list`` and return ``structuredContent`` on
``tools/call`` — so a client can render the QA / Unity-export result as a report
card instead of re-parsing a JSON string.

Every top-level field is BOTH optional (``total=False``) and nullable
(``| None``). Nullable is load-bearing, not style: the MCP SDK's result
conversion None-fills every unset TypedDict key before the low-level server
jsonschema-validates the structured content on real ``tools/call`` requests, so
a non-nullable optional field makes any partial result fail validation on the
wire even though the in-process FastMCP path accepts it. (v0.1.1 shipped that
exact bug in ``get_sprite_info`` and the Unity exports.) Nested shapes like
``SizeReport`` stay non-nullable-valued because they are always fully populated
when present.
"""
from __future__ import annotations

from typing import Any

# typing_extensions, not typing: pydantic refuses typing.TypedDict on
# Python < 3.12 (PydanticUserError at server startup), and mcp already
# hard-requires typing-extensions — so this keeps the declared 3.10 floor real.
from typing_extensions import TypedDict


class SizeReport(TypedDict, total=False):
    width: int
    height: int


class PaddingReport(TypedDict, total=False):
    empty: bool | None
    canvas: SizeReport | None
    content: dict[str, int] | None
    padding: dict[str, int] | None
    fillRatio: float | None
    colorCount: int | None


CheckItem = TypedDict("CheckItem", {"check": str, "pass": bool, "detail": str}, total=False)


class QAReport(TypedDict, total=False):
    passed: int | None
    failed: int | None
    checks: list[CheckItem] | None
    measurements: PaddingReport | None


class SpriteInfo(TypedDict, total=False):
    # No ``error`` field: a Lua failure raises ToolError in get_sprite_info —
    # failures must never share the success schema (and pydantic would silently
    # strip an unknown key, hiding the error entirely).
    width: int | None
    height: int | None
    colorMode: str | None
    frames: int | None
    layers: list[str] | None
    tags: list[str] | None
    filename: str | None


class UnityExport(TypedDict, total=False):
    mode: str | None
    png: str | None
    png_exists: bool | None
    meta: str | None
    guid: str | None
    frames: int | None
    frame_size: SizeReport | None
    sheet_size: SizeReport | None
    texture_size: SizeReport | None
    pixels_per_unit: int | None
    alignment: str | None
    sprites: list[dict[str, Any]] | None
