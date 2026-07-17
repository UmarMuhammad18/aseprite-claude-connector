"""Test suite for aseprite-live-mcp.

Unit tests (no Aseprite needed) cover registration and the pure-Python helpers.
The headless integration test drives real tools through the MCP layer and is
skipped automatically when Aseprite isn't installed. For the full multi-tool
sweep, run ``python tests/smoke_headless.py``.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from aseprite_live_mcp import backends
from aseprite_live_mcp.config import _default_aseprite
from aseprite_live_mcp.lua import build_lua, lua_locals
from aseprite_live_mcp.server import build_server
from aseprite_live_mcp.tools._common import ToolError, parse_color
from aseprite_live_mcp.tools.export import _resolve_written
from aseprite_live_mcp.tools.unity_export import _gen_meta

ASEPRITE = _default_aseprite()
HAS_ASEPRITE = os.path.isfile(ASEPRITE)


def _run(coro):
    return asyncio.run(coro)


def _text(res) -> str:
    if isinstance(res, tuple):
        res = res[0]
    return " ".join(getattr(p, "text", str(p)) for p in res)


# --- unit tests (no Aseprite) ---------------------------------------------------


def test_tools_registered():
    names = {t.name for t in _run(build_server().list_tools())}
    assert len(names) >= 48
    for t in (
        "status",
        "create_sprite",
        "draw_rectangle",
        "export_sprite",
        "export_unity_sprite",
        "measure_padding",
        "qa_sweep",
        "palette_ramp_walk",
        "smear_frame",
        "run_lua",
    ):
        assert t in names, f"missing tool {t}"


def test_tool_annotations_present():
    tools = {t.name: t for t in _run(build_server().list_tools())}
    # read-only tools should be marked read-only; run_lua should be open-world
    assert tools["get_sprite_info"].annotations.readOnlyHint is True
    assert tools["run_lua"].annotations.openWorldHint is True


def test_parse_color():
    assert parse_color("#ff0000") == (255, 0, 0, 255)
    assert parse_color("00ff0080") == (0, 255, 0, 128)
    with pytest.raises(ToolError):
        parse_color("#nothex")
    with pytest.raises(ToolError):
        parse_color("#fff")


def test_lua_locals_and_transaction_wrapping():
    s = lua_locals(X=1, NAME="a", FLAG=True, NOPE=None)
    assert "local X = 1" in s
    assert 'local NAME = "a"' in s
    assert "local FLAG = true" in s
    assert "local NOPE = nil" in s
    assert "app.transaction(" in build_lua("return 1", mutates=True)
    assert "app.transaction(" not in build_lua("return 1", mutates=False)


def test_unity_meta_structure_and_yaml():
    meta, rects = _gen_meta("g" * 32, 16, 3, 16, 16, "uni", 0.5, 0.0)
    assert "spriteMode: 2" in meta
    assert "textureType: 8" in meta
    assert meta.count("name: uni_") == 3
    assert [r["x"] for r in rects] == [0, 16, 32]
    yaml = pytest.importorskip("yaml")
    yaml.safe_load(meta)  # valid YAML, no duplicate keys


def test_resolve_written(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"x")
    assert _resolve_written(str(p), 1) == [str(p)]
    # multi-frame split naming
    for i in (1, 2):
        (tmp_path / f"b{i}.png").write_bytes(b"x")
    got = _resolve_written(str(tmp_path / "b.png"), 2)
    assert got == [str(tmp_path / "b1.png"), str(tmp_path / "b2.png")]


# --- headless integration (needs Aseprite) --------------------------------------


@pytest.mark.skipif(not HAS_ASEPRITE, reason="Aseprite not installed")
def test_headless_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ASEPRITE_MCP_BACKEND", "headless")
    backends.set_backend(None)  # reset the cached backend so it re-reads the env
    mcp = build_server()
    ase = str(tmp_path / "t.aseprite")

    async def go():
        await mcp.call_tool(
            "create_sprite", {"width": 20, "height": 20, "color_mode": "rgb", "file": ase}
        )
        await mcp.call_tool(
            "draw_rectangle",
            {"x": 7, "y": 7, "width": 6, "height": 6, "color": "#ffffff", "file": ase},
        )
        return await mcp.call_tool("measure_padding", {"file": ase})

    data = json.loads(_text(_run(go())))
    assert data["padding"] == {"left": 7, "right": 7, "top": 7, "bottom": 7}
    backends.set_backend(None)
