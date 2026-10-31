"""Live demo: drive the RUNNING Aseprite editor via the MCP server.

Prereq: the relay is running (python -m aseprite_live_mcp.relay) and Aseprite is
open with the Claude Bridge extension installed. Then:

    ASEPRITE_MCP_BACKEND=live python examples/live_demo.py

It draws a small emblem on your ACTIVE sprite. Every edit is one app.transaction,
so each is a single Ctrl+Z — watch the shapes appear, then undo them one at a time.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

os.environ.setdefault("ASEPRITE_MCP_BACKEND", "live")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aseprite_live_mcp.server import build_server  # noqa: E402

PNG = os.path.join(tempfile.gettempdir(), "aselm_live_demo.png")


async def main() -> int:
    mcp = build_server()

    async def call(name, args=None):
        res = await mcp.call_tool(name, args or {})
        txt = " ".join(
            getattr(p, "text", str(p)) for p in (res[0] if isinstance(res, tuple) else res)
        )
        print(f"  {name}: {txt[:140].replace(chr(10), ' ')}")
        return txt

    print("status:")
    await call("status")
    print("active sprite:")
    await call("get_sprite_info")

    edits = [
        (
            "draw_circle",
            {"center_x": 32, "center_y": 32, "radius": 20, "color": "#2288ff", "fill": True},
        ),
        (
            "draw_circle",
            {"center_x": 32, "center_y": 32, "radius": 28, "color": "#ffffff", "fill": False},
        ),
        (
            "draw_rectangle",
            {"x": 20, "y": 20, "width": 24, "height": 24, "color": "#ffcc00", "fill": False},
        ),
        ("draw_line", {"x1": 0, "y1": 0, "x2": 63, "y2": 63, "color": "#ff3355"}),
        ("draw_line", {"x1": 0, "y1": 63, "x2": 63, "y2": 0, "color": "#ff3355"}),
    ]
    print(f"drawing {len(edits)} shapes (each is one undo step):")
    for name, args in edits:
        await call(name, args)

    print("read-back + QA:")
    await call("get_pixel", {"x": 32, "y": 32})
    await call("measure_padding")

    print("export live sprite -> PNG:")
    await call("export_sprite", {"out_path": PNG})
    print(
        f"\nDone. {len(edits)} edits made on your live canvas. Press Ctrl+Z {len(edits)} times to undo them one at a time."
    )
    print(f"Exported to: {PNG}")
    return len(edits)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
