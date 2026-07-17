"""Art-QA tools — a differentiator.

No other Aseprite MCP ships a packaged art-QA sweep, and transparent
sticker-padding measurement was found in no tool at all (MCP or otherwise). These
audit a sprite against project conventions inside the AI loop: content bounds,
transparent padding, color count, grid-fit.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from . import state
from ._common import ToolError, run
from ._schemas import PaddingReport, QAReport

# One composited pass: content bbox, per-side transparent padding, fill ratio, and
# the count of distinct opaque colors.
_ANALYZE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local frame = app.activeFrame or s.frames[1]
local img = Image(s.width, s.height, ColorMode.RGB)
img:drawSprite(s, frame)
local minx, miny, maxx, maxy = s.width, s.height, -1, -1
local colors = {}
local ccount = 0
for y = 0, s.height - 1 do
  for x = 0, s.width - 1 do
    local v = img:getPixel(x, y)
    if app.pixelColor.rgbaA(v) > 0 then
      if x < minx then minx = x end
      if x > maxx then maxx = x end
      if y < miny then miny = y end
      if y > maxy then maxy = y end
      if not colors[v] then colors[v] = true; ccount = ccount + 1 end
    end
  end
end
if maxx < 0 then
  return J({ empty = true, canvas = { width = s.width, height = s.height }, colorCount = 0 })
end
local cw, ch = maxx - minx + 1, maxy - miny + 1
return J({
  empty = false,
  canvas = { width = s.width, height = s.height },
  content = { x = minx, y = miny, width = cw, height = ch },
  padding = { left = minx, top = miny, right = s.width - 1 - maxx, bottom = s.height - 1 - maxy },
  fillRatio = (cw * ch) / (s.width * s.height),
  colorCount = ccount,
})
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Measure padding", readOnlyHint=True))
    def measure_padding(file: str | None = None) -> PaddingReport:
        """Measure the transparent 'sticker' padding around the content: content
        bounding box, per-side padding (left/right/top/bottom), fill ratio, and
        distinct opaque color count. Read-only. Headless: pass ``file``."""
        res = run(_ANALYZE, file=file)
        if not isinstance(res, dict):
            raise ToolError("padding analysis failed")
        state.set_last("qa", {"kind": "measure_padding", "result": res})
        return res

    @mcp.tool(annotations=ToolAnnotations(title="Art-QA sweep", readOnlyHint=True))
    def qa_sweep(
        expected_width: int | None = None,
        expected_height: int | None = None,
        max_colors: int | None = None,
        grid_multiple: int | None = None,
        require_symmetric_padding: bool = False,
        file: str | None = None,
    ) -> QAReport:
        """Audit the active sprite against project conventions and return per-check
        pass/fail. Any rule you pass is checked: exact canvas size
        (``expected_width``/``expected_height``), ``grid_multiple`` (canvas dims
        divisible by N), ``max_colors`` (distinct opaque colors ≤ N), and
        ``require_symmetric_padding`` (equal left/right + top/bottom margins).
        Read-only. Headless: pass ``file``."""
        data = run(_ANALYZE, file=file)
        if not isinstance(data, dict):
            raise ToolError("analysis failed")

        checks: list[dict] = []

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "pass": bool(ok), "detail": detail})

        if data.get("empty"):
            add("non_empty", False, "sprite has no non-transparent pixels")
            empty_res = {"passed": 0, "failed": 1, "checks": checks, "measurements": data}
            state.set_last("qa", {"kind": "qa_sweep", "result": empty_res})
            return empty_res

        canvas = data["canvas"]
        pad = data["padding"]
        cc = data["colorCount"]

        if expected_width is not None:
            add(
                "width",
                canvas["width"] == expected_width,
                f"{canvas['width']} (expected {expected_width})",
            )
        if expected_height is not None:
            add(
                "height",
                canvas["height"] == expected_height,
                f"{canvas['height']} (expected {expected_height})",
            )
        if grid_multiple:
            ok = canvas["width"] % grid_multiple == 0 and canvas["height"] % grid_multiple == 0
            add(
                "grid_fit",
                ok,
                f"{canvas['width']}x{canvas['height']} vs multiple of {grid_multiple}",
            )
        if max_colors is not None:
            add("max_colors", cc <= max_colors, f"{cc} colors (max {max_colors})")
        if require_symmetric_padding:
            sym = pad["left"] == pad["right"] and pad["top"] == pad["bottom"]
            add(
                "symmetric_padding",
                sym,
                f"L{pad['left']} R{pad['right']} T{pad['top']} B{pad['bottom']}",
            )

        passed = sum(1 for c in checks if c["pass"])
        result = {
            "passed": passed,
            "failed": len(checks) - passed,
            "checks": checks,
            "measurements": data,
        }
        state.set_last("qa", {"kind": "qa_sweep", "result": result})
        return result
