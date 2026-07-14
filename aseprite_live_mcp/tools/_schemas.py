"""Typed return shapes for the flagship tools.

Annotating a tool's return with one of these makes FastMCP publish an
``outputSchema`` in ``tools/list`` and return ``structuredContent`` on
``tools/call`` — so a client can render the QA / Unity-export result as a report
card instead of re-parsing a JSON string. All are ``total=False`` (every field
optional) so a partial result (e.g. an empty sprite) still validates.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SizeReport(TypedDict, total=False):
    width: int
    height: int


class PaddingReport(TypedDict, total=False):
    empty: bool
    canvas: SizeReport
    content: dict[str, int]
    padding: dict[str, int]
    fillRatio: float
    colorCount: int


CheckItem = TypedDict("CheckItem", {"check": str, "pass": bool, "detail": str}, total=False)


class QAReport(TypedDict, total=False):
    passed: int
    failed: int
    checks: list[CheckItem]
    measurements: PaddingReport


class SpriteInfo(TypedDict, total=False):
    width: int
    height: int
    colorMode: str
    frames: int
    layers: list[str]
    tags: list[str]
    filename: str
    error: str


class UnityExport(TypedDict, total=False):
    mode: str
    png: str
    png_exists: bool
    meta: str
    guid: str
    frames: int
    frame_size: SizeReport
    sheet_size: SizeReport
    texture_size: SizeReport
    pixels_per_unit: int
    alignment: str
    sprites: list[dict[str, Any]]
