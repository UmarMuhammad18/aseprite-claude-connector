"""Guarded raw-Lua escape hatch — deliberately NOT the primary surface.

Best-practice MCP servers wrap concrete typed operations rather than exposing an
unbounded 'run arbitrary code' tool. We keep one, clearly annotated as destructive
and open-world, for the long tail the typed tools don't cover — but the typed
tools are the intended interface.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ._common import refuse_in_dry_run, run


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Run Lua (advanced)", readOnlyHint=False, destructiveHint=True, openWorldHint=True
        )
    )
    def run_lua(code: str, save: bool = False, file: str | None = None):
        """Run arbitrary Lua inside Aseprite and return its result (advanced escape
        hatch — equivalent to local code execution). ``J(value)`` is available for
        JSON returns; wrap your own edits in ``app.transaction`` for clean undo.
        The prelude also provides ``editCel(fn)`` and ``findLayer(s, name)``. Set
        ``save=true`` (headless) to persist changes to ``file``. Your code must
        ``return`` a value. Safety rails don't apply here: the pixel cap isn't
        enforced, and in a dry run this tool refuses to run."""
        refuse_in_dry_run("run_lua")
        return run(code, mutates=False, file=file, save=save)
