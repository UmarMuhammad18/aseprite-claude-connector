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


_CLIP_BEFORE = """
local __s = app.activeSprite
if __s.selection.isEmpty then error("select an area in Aseprite first") end
local __keep = Selection()
__keep:add(__s.selection)
local __box = __keep.bounds
local __frames, __w, __h = #__s.frames, __s.width, __s.height
local __layers = {}
local function __walk(layers)
  for _, l in ipairs(layers) do
    if l.isGroup then __walk(l.layers)
    elseif not l.isTilemap then __layers[#__layers + 1] = l end
  end
end
__walk(__s.layers)
local __count = #__layers
local __mode = __s.colorMode
local function __blank()
  local img = Image(__w, __h, __mode)
  if __mode == ColorMode.INDEXED then img:clear(__s.transparentColor) end
  return img
end
local __before = {}
for i, l in ipairs(__layers) do
  __before[i] = {}
  for _, c in ipairs(l.cels) do
    __before[i][c.frameNumber] = { image = c.image:clone(), x = c.position.x, y = c.position.y }
  end
end
"""

_CLIP_AFTER = """
if #__s.frames ~= __frames or __s.width ~= __w or __s.height ~= __h then
  error("edits inside a selection can't change the frames or the canvas size")
end
__layers = {}
__walk(__s.layers)
if #__layers ~= __count then
  error("edits inside a selection can't add or remove layers")
end
local __reverted = 0
for i, l in ipairs(__layers) do
  for n = 1, __frames do
    local old, cel = __before[i][n], l:cel(n)
    if cel then
      local same = old and cel.position.x == old.x and cel.position.y == old.y
        and cel.image:isEqual(old.image)
      if not same then
        local kept, fresh = __blank(), __blank()
        if old then kept:drawImage(old.image, Point(old.x, old.y)) end
        fresh:drawImage(cel.image, cel.position)
        local out = Image(kept)
        for y = __box.y, __box.y + __box.height - 1 do
          for x = __box.x, __box.x + __box.width - 1 do
            if x >= 0 and y >= 0 and x < __w and y < __h and __keep:contains(x, y) then
              out:drawPixel(x, y, fresh:getPixel(x, y))
            end
          end
        end
        cel.image = out
        cel.position = Point(0, 0)
        __reverted = __reverted + 1
      end
    elseif old then
      local out = __blank()
      local kept = __blank()
      kept:drawImage(old.image, Point(old.x, old.y))
      for y = 0, __h - 1 do
        for x = 0, __w - 1 do
          if not __keep:contains(x, y) then out:drawPixel(x, y, kept:getPixel(x, y)) end
        end
      end
      if not out:isEmpty() then __s:newCel(l, n, out, Point(0, 0)) end
    end
  end
end
__s.selection = __keep
"""


def _clipped(bodies: list[str]) -> str:
    """The steps, with everything outside the selection put back afterward. The drawing
    tools write to images directly, which Aseprite's selection doesn't guard."""
    steps = "".join(
        f"__steps[{i}] = tostring((function()\n{body}\nend)())\n"
        for i, body in enumerate(bodies, 1)
    )
    return (
        _CLIP_BEFORE
        + f"local __steps = {{}}\n{steps}"
        + _CLIP_AFTER
        + 'return "[" .. table.concat(__steps, ",") .. "]"\n'
    )


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

    @mcp.tool(annotations=ToolAnnotations(title="Edit inside the selection"))
    def edit_in_selection(
        steps: list[dict[str, Any]], label: str = "AI edits in selection", file: str | None = None
    ) -> dict:
        """ "Fix this bit": run editing tools so they change only what's inside the current
        selection, as one undo step. Anything they'd do outside it, on any layer or frame,
        is put back. Steps are written as in ``edit_batch``. Select the area in Aseprite
        first; ``look`` with ``selection`` shows what's selected. Steps can't change the
        frames, layers, or canvas size. Headless: pass ``file`` here, not in the steps."""
        if not 1 <= len(steps) <= MAX_STEPS:
            raise ToolError(f"steps must hold 1-{MAX_STEPS} entries")
        bodies = _collect(mcp, steps)
        results = run(_clipped(bodies), mutates=True, undo_label=label, file=file)
        return {"steps": len(bodies), "results": results}
