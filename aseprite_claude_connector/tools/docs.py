"""Docs search: look Aseprite's scripting API and manual up instead of guessing."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..docs_search import api_index, manual_index
from ._common import ToolError


def _results(query: str, hits: list[dict]) -> dict:
    return {"query": query, "count": len(hits), "results": hits}


def _check(query: str, limit: int) -> None:
    if not query.strip():
        raise ToolError("query must not be empty")
    if not 1 <= limit <= 20:
        raise ToolError("limit must be 1-20")


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Search API docs", readOnlyHint=True))
    def search_api_docs(query: str, limit: int = 5) -> dict:
        """Search Aseprite's Lua scripting API reference, bundled with this server.
        Use it before writing ``run_lua`` code, for a class, method, or property such
        as ``Image:drawImage`` or ``selection bounds``."""
        _check(query, limit)
        return _results(query, api_index().search(query, limit))

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search the manual", readOnlyHint=True, openWorldHint=True
        )
    )
    def search_manual(query: str, limit: int = 5) -> dict:
        """Search Aseprite's user manual: how features work in the editor, such as
        tilemaps, onion skinning, or slices. The first search downloads the manual
        from GitHub to your cache, then it refreshes every 30 days."""
        _check(query, limit)
        try:
            index = manual_index()
        except OSError as e:
            raise ToolError(f"couldn't download the manual: {e}") from e
        return _results(query, index.search(query, limit))
