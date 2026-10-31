"""Safety rails: a dry-run mode, a pixel cap, and one undo step for many edits.

The rails live in ``build_lua``, so every mutating tool gets them. ``edit_batch`` runs
each step's tool in capture mode, where ``run`` hands back the step's Lua instead of
executing it, then runs all of it in one transaction. A transaction can't stay open
across bridge calls, so this is the only way to get one real Ctrl-Z for several tools.
"""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from ._common import Captured, ToolError, rails, run

MAX_STEPS = 100


def _collect(mcp, steps: list[dict]) -> list[str]:
    bodies = []
    rails.capturing = True
    try:
        for i, step in enumerate(steps, 1):
            name = step.get("tool", "")
            args = dict(step.get("args") or {})
            tool = mcp._tool_manager.get_tool(name)
            if tool is None:
                raise ToolError(f"step {i}: unknown tool '{name}'")
            if args.pop("preview", False):
                raise ToolError(f"step {i}: preview isn't available in a batch; use look after")
            args.pop("file", None)
            try:
                tool.fn(**args)
            except Captured as captured:
                bodies.append(captured.body)
                continue
            except ToolError as e:
                raise ToolError(f"step {i} ({name}): {e}") from e
            except TypeError as e:
                raise ToolError(f"step {i} ({name}): {e}") from e
            raise ToolError(f"step {i}: '{name}' doesn't edit the sprite, so it can't be batched")
    finally:
        rails.capturing = False
    return bodies


def _combine(bodies: list[str]) -> str:
    steps = "".join(
        f"__steps[{i}] = tostring((function()\n{body}\nend)())\n"
        for i, body in enumerate(bodies, 1)
    )
    return f'local __steps = {{}}\n{steps}return "[" .. table.concat(__steps, ",") .. "]"\n'


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Set safety rails", idempotentHint=True))
    def set_safety_rails(
        dry_run: bool | None = None, max_changed_pixels: int | None = None
    ) -> dict:
        """Set the safety rails for this session, or pass nothing to read them.
        ``dry_run`` true makes every edit report what it would change, as an error,
        then roll back; tools that save, export, or run raw Lua refuse instead.
        ``max_changed_pixels`` caps what one call can change, and an edit over it is
        rolled back; 0 removes the cap. It counts hidden layers. ``move_layer`` isn't capped, and
        ``run_lua`` is capped only with ``edit=true``."""
        if max_changed_pixels is not None:
            if max_changed_pixels < 0:
                raise ToolError("max_changed_pixels must be 0 or more")
            rails.max_pixels = max_changed_pixels
        if dry_run is not None:
            rails.dry_run = dry_run
        return {"dry_run": rails.dry_run, "max_changed_pixels": rails.cap()}

    @mcp.tool(annotations=ToolAnnotations(title="Edit in one undo step"))
    def edit_batch(
        steps: list[dict[str, Any]], label: str = "AI edits", file: str | None = None
    ) -> dict:
        """Run several editing tools as one undo step, so one Ctrl-Z reverts them all.
        Each step is ``{"tool": "draw_line", "args": {...}}``, in order. If any step
        fails, none of them apply. The pixel cap covers the whole batch. Steps can't
        see each other's results, and tools that save or export can't be batched.
        Headless: pass ``file`` here, not in the steps."""
        if not 1 <= len(steps) <= MAX_STEPS:
            raise ToolError(f"steps must hold 1-{MAX_STEPS} entries")
        bodies = _collect(mcp, steps)
        results = run(_combine(bodies), mutates=True, undo_label=label, file=file)
        return {"steps": len(bodies), "results": results}
