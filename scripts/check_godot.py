"""Load a real export in real Godot, which no text test can stand in for.

Draws a tagged animation, runs ``export_to_game`` into a new project, has Godot import
it, then compares what Godot reports with what was drawn. Run it with ``GODOT_PATH`` and
``ASEPRITE_PATH`` set. Exits non-zero on any difference.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["ASEPRITE_MCP_BACKEND"] = "headless"
os.environ["ASEPRITE_MCP_NO_UPDATE_CHECK"] = "1"

from aseprite_claude_connector.server import build_server  # noqa: E402

SIZE = 8
# (tag, one colour per frame, milliseconds per frame)
TAGS = [
    ("walk", ["c83232", "32c832", "3232c8", "c8c832"], [100, 100, 100, 100]),
    ("idle", ["c832c8", "32c8c8"], [200, 400]),
]

_DRAW = """
local s = app.activeSprite
local layer = s.layers[1]
local spec = SPEC
local n = 0
local spans = {}
for _, tag in ipairs(spec) do
  local first = n + 1
  for i, hex in ipairs(tag.colors) do
    n = n + 1
    if n > 1 then s:newEmptyFrame() end
    local img = Image(s.width, s.height, ColorMode.RGB)
    img:clear(Color(tonumber(hex:sub(1, 2), 16), tonumber(hex:sub(3, 4), 16),
                    tonumber(hex:sub(5, 6), 16), 255))
    s:newCel(layer, n, img, Point(0, 0))
    s.frames[n].duration = tag.ms[i] / 1000
  end
  spans[#spans + 1] = { tag.name, first, n }
end
-- Tags come last: a frame added after a tag's end stretches it.
for _, span in ipairs(spans) do
  local t = s:newTag(span[2], span[3])
  t.name = span[1]
end
return J({ frames = #s.frames })
"""


def _lua_spec() -> str:
    tags = []
    for name, colors, ms in TAGS:
        hexes = ", ".join(f'"{c}"' for c in colors)
        tags.append(
            f'{{ name = "{name}", colors = {{ {hexes} }}, ms = {{ {", ".join(map(str, ms))} }} }}'
        )
    return "{ " + ", ".join(tags) + " }"


def _differences(report: dict) -> list[str]:
    found = report["animations"]
    wrong = []
    for name, colors, ms in TAGS:
        got = found.get(name)
        if not got:
            wrong.append(f"no animation '{name}' in {sorted(found)}")
            continue
        if len(got["frames"]) != len(colors):
            wrong.append(f"{name}: {len(got['frames'])} frames, drew {len(colors)}")
            continue
        for n, (cell, color, want) in enumerate(zip(got["frames"], colors, ms, strict=True)):
            shown = cell["duration"] / got["fps"] * 1000
            if abs(shown - want) > 1:
                wrong.append(f"{name} frame {n}: plays {shown:.1f} ms, drew {want}")
            if cell["color"] != color:
                wrong.append(f"{name} frame {n}: shows {cell['color']}, drew {color}")
            if cell["size"] != [SIZE, SIZE]:
                wrong.append(f"{name} frame {n}: region {cell['size']}")
    return wrong


async def _export(project: Path, sprite: Path) -> dict:
    mcp = build_server()
    await mcp.call_tool("create_sprite", {"width": SIZE, "height": SIZE, "file": str(sprite)})
    code = _DRAW.replace("SPEC", _lua_spec())
    await mcp.call_tool("run_lua", {"code": code, "save": True, "file": str(sprite)})
    res = await mcp.call_tool("export_to_game", {"game_dir": str(project), "file": str(sprite)})
    return json.loads((res[0] if isinstance(res, tuple) else res)[0].text)


def main() -> int:
    godot = os.environ["GODOT_PATH"]
    with tempfile.TemporaryDirectory() as folder:
        project = Path(folder) / "game"
        project.mkdir()
        (project / "project.godot").write_text(
            'config_version=5\n\n[application]\n\nconfig/name="check"\n', encoding="utf-8"
        )
        print(asyncio.run(_export(project, Path(folder) / "hero.aseprite")))
        shutil.copy(Path(__file__).with_name("godot_check.gd"), project / "godot_check.gd")
        base = [godot, "--headless", "--path", str(project)]
        subprocess.run([*base, "--import"], check=True, timeout=300)
        out = subprocess.run(
            [*base, "--script", "godot_check.gd"], capture_output=True, text=True, timeout=120
        )
    print(out.stdout, out.stderr, file=sys.stderr)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("GODOT_REPORT=")]
    if not lines:
        print("Godot couldn't load the export")
        return 1
    report = json.loads(lines[0].removeprefix("GODOT_REPORT="))
    print(json.dumps(report, indent=2))
    wrong = _differences(report)
    for line in wrong:
        print(f"WRONG: {line}")
    if not wrong:
        print("OK: Godot loaded every animation as drawn")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
