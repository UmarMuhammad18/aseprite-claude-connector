"""Wire-path output-schema validation tests.

``FastMCP.call_tool()`` — what the smoke suite and the older tests use — runs
only pydantic result conversion. A real MCP client additionally passes through
the low-level server, which None-fills every unset ``total=False`` TypedDict
key and then strictly ``jsonschema``-validates the structured content against
the tool's published ``outputSchema``. That is the layer where v0.1.1 failed:
``get_sprite_info`` and both Unity-export tools returned partial dicts whose
None-filled keys violated their own schemas on 100% of real client calls.

These tests drive ``tools/call`` through a real in-memory client session
(``mcp.shared.memory``) so the validating path is exercised. Backend Lua
execution is stubbed at each tool module's ``run`` symbol, so no Aseprite is
needed and each schema shape is pinned exactly.
"""

from __future__ import annotations

import asyncio
import base64

from mcp.shared.memory import create_connected_server_and_client_session

from aseprite_claude_connector.server import build_server
from aseprite_claude_connector.tools._common import ToolError

# The exact success shape the live backend returns for an ordinary open sprite
# (no ``error`` key — that key only ever appears in the failure shape).
LIVE_SPRITE_INFO = {
    "width": 64,
    "height": 64,
    "colorMode": "rgb",
    "frames": 1,
    "layers": ["Layer 1"],
    "tags": [],
    "filename": "Sprite-0001",
}

# The exact analysis shapes artqa's Lua returns.
PADDING_EMPTY = {"empty": True, "canvas": {"width": 64, "height": 64}, "colorCount": 0}
PADDING_NORMAL = {
    "empty": False,
    "canvas": {"width": 64, "height": 64},
    "content": {"x": 8, "y": 8, "width": 48, "height": 48},
    "padding": {"left": 8, "top": 8, "right": 8, "bottom": 8},
    "fillRatio": 0.5625,
    "colorCount": 7,
}


def _stub_run(result):
    def fake_run(body, **kwargs):
        return dict(result) if isinstance(result, dict) else result

    return fake_run


def _wire_call(tool: str, args: dict | None = None):
    """One tools/call through a real client session (initialize + validate)."""

    async def go():
        server = build_server()
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            return await client.call_tool(tool, args or {})

    return asyncio.run(go())


def _text(res) -> str:
    return " ".join(getattr(c, "text", "") for c in res.content)


# --- get_sprite_info -------------------------------------------------------------


def test_get_sprite_info_success_passes_wire_validation(monkeypatch):
    monkeypatch.setattr("aseprite_claude_connector.tools.inspect.run", _stub_run(LIVE_SPRITE_INFO))
    res = _wire_call("get_sprite_info")
    assert res.isError is False, f"schema rejected a normal sprite: {_text(res)}"
    assert res.structuredContent["width"] == 64
    assert res.structuredContent["filename"] == "Sprite-0001"


def test_get_sprite_info_no_sprite_is_a_tool_error(monkeypatch):
    """The Lua failure shape must surface as a ToolError (isError=True with the
    real message), never as a success payload or an output-validation crash."""
    monkeypatch.setattr(
        "aseprite_claude_connector.tools.inspect.run",
        _stub_run({"error": "no active sprite"}),
    )
    res = _wire_call("get_sprite_info")
    assert res.isError is True
    assert "no active sprite" in _text(res)
    assert "validation error" not in _text(res).lower()


# --- measure_padding / qa_sweep ---------------------------------------------------


def test_measure_padding_empty_sprite_passes_wire_validation(monkeypatch):
    monkeypatch.setattr("aseprite_claude_connector.tools.artqa.run", _stub_run(PADDING_EMPTY))
    res = _wire_call("measure_padding")
    assert res.isError is False, f"schema rejected the empty-sprite branch: {_text(res)}"
    assert res.structuredContent["empty"] is True


def test_measure_padding_normal_passes_wire_validation(monkeypatch):
    monkeypatch.setattr("aseprite_claude_connector.tools.artqa.run", _stub_run(PADDING_NORMAL))
    res = _wire_call("measure_padding")
    assert res.isError is False, _text(res)
    assert res.structuredContent["padding"]["left"] == 8


def test_qa_sweep_passes_wire_validation_on_both_branches(monkeypatch):
    for shape in (PADDING_NORMAL, PADDING_EMPTY):
        monkeypatch.setattr("aseprite_claude_connector.tools.artqa.run", _stub_run(shape))
        res = _wire_call("qa_sweep", {"expected_width": 64, "expected_height": 64})
        assert res.isError is False, _text(res)
        assert "passed" in res.structuredContent


# --- Unity exports ----------------------------------------------------------------


def test_export_unity_sprite_passes_wire_validation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "aseprite_claude_connector.tools.unity_export.run",
        _stub_run({"frames": 3, "width": 16, "height": 16}),
    )
    png = str(tmp_path / "strip.png")
    res = _wire_call("export_unity_sprite", {"png_path": png})
    assert res.isError is False, f"frames-mode export rejected: {_text(res)}"
    sc = res.structuredContent
    assert sc["mode"] == "frames"
    assert sc["frames"] == 3
    assert (tmp_path / "strip.png.meta").is_file()


def test_export_unity_slices_passes_wire_validation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "aseprite_claude_connector.tools.unity_export.run",
        _stub_run(
            {
                "width": 32,
                "height": 32,
                "slices": [
                    {
                        "name": "body",
                        "x": 0,
                        "y": 0,
                        "width": 16,
                        "height": 16,
                        "px": 0.5,
                        "py": 0.5,
                    }
                ],
            }
        ),
    )
    png = str(tmp_path / "atlas.png")
    res = _wire_call("export_unity_slices", {"png_path": png})
    assert res.isError is False, f"slices-mode export rejected: {_text(res)}"
    sc = res.structuredContent
    assert sc["mode"] == "slices"
    assert sc["texture_size"] == {"width": 32, "height": 32}
    assert (tmp_path / "atlas.png.meta").is_file()


# --- look tools ------------------------------------------------------------------


RED_PIXEL = base64.b64encode(bytes((255, 0, 0, 255))).decode()
CLEAR_PIXEL = base64.b64encode(bytes(4)).decode()


def _images(res):
    return [c for c in res.content if c.type == "image"]


def test_look_returns_an_image_over_the_wire(monkeypatch):
    meta = {"rgba": RED_PIXEL, "width": 1, "height": 1, "frame": 1, "frames": 1, "layer": "all"}
    monkeypatch.setattr("aseprite_claude_connector.tools.look.run", _stub_run(meta))
    res = _wire_call("look")
    assert res.isError is False, _text(res)
    assert _images(res)[0].mimeType == "image/png"
    assert '"image_width": 32' in _text(res)


def test_look_animation_lists_cells(monkeypatch):
    meta = {
        "frames": [RED_PIXEL, CLEAR_PIXEL],
        "durations": [100, 250],
        "width": 1,
        "height": 1,
        "first_frame": 3,
        "last_frame": 4,
        "columns": 2,
        "tag": "run",
    }
    monkeypatch.setattr("aseprite_claude_connector.tools.look.run", _stub_run(meta))
    res = _wire_call("look_animation", {"tag": "run"})
    assert res.isError is False, _text(res)
    assert len(_images(res)) == 1
    assert '"frame": 4' in _text(res) and '"duration_ms": 250' in _text(res)


def test_look_rejects_truncated_pixels(monkeypatch):
    meta = {"rgba": RED_PIXEL, "width": 2, "height": 2}
    monkeypatch.setattr("aseprite_claude_connector.tools.look.run", _stub_run(meta))
    res = _wire_call("look")
    assert res.isError is True
    assert "bad pixel data" in _text(res)


RECT_ARGS = {"x": 0, "y": 0, "width": 1, "height": 1, "color": "#ff0000"}
DRAWN = {"drawn": "rectangle"}


def test_preview_off_leaves_a_drawing_tool_unchanged(monkeypatch):
    monkeypatch.setattr("aseprite_claude_connector.tools.draw.run", _stub_run(DRAWN))
    res = _wire_call("draw_rectangle", RECT_ARGS)
    assert res.isError is False, _text(res)
    assert not _images(res)
    assert '"drawn": "rectangle"' in _text(res)


def test_preview_adds_a_picture_and_keeps_structured_output(monkeypatch):
    shots = iter([CLEAR_PIXEL, RED_PIXEL])

    def snapshot(body, **kwargs):
        return {"rgba": next(shots), "width": 1, "height": 1, "frame": 1}

    monkeypatch.setattr("aseprite_claude_connector.tools.look.run", snapshot)
    monkeypatch.setattr("aseprite_claude_connector.tools.draw.run", _stub_run(DRAWN))
    res = _wire_call("draw_rectangle", {**RECT_ARGS, "preview": True})
    assert res.isError is False, _text(res)
    assert len(_images(res)) == 1
    assert res.structuredContent == {"result": DRAWN}
    assert '"changed_pixels": 1' in _text(res)


def test_a_failed_preview_never_loses_the_edit(monkeypatch):
    def broken(body, **kwargs):
        raise ToolError("no pictures today")

    monkeypatch.setattr("aseprite_claude_connector.tools.look.run", broken)
    monkeypatch.setattr("aseprite_claude_connector.tools.draw.run", _stub_run(DRAWN))
    res = _wire_call("draw_rectangle", {**RECT_ARGS, "preview": True})
    assert res.isError is False, _text(res)
    assert res.structuredContent == {"result": DRAWN}
    assert "no pictures today" in _text(res)
