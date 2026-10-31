"""Docs search, describe_sprite wiring, and the safety rails."""

from __future__ import annotations

import asyncio
import io
import json
import tarfile

import pytest
from mcp.server.fastmcp.exceptions import ToolError as FastMCPToolError

from aseprite_claude_connector import docs_search
from aseprite_claude_connector.docs_search import (
    DocIndex,
    api_index,
    fetch_markdown,
    split_sections,
)
from aseprite_claude_connector.lua import build_lua
from aseprite_claude_connector.server import build_server
from aseprite_claude_connector.tools import _common
from aseprite_claude_connector.tools._common import ToolError, rails, run
from aseprite_claude_connector.tools.godot_export import (
    animations,
    build_tres,
    frame_order,
    res_path_for,
)
from aseprite_claude_connector.tools.safety import _combine

PAGE = """# Sprite

Intro text.

## Sprite:newLayer()

```lua
# not a heading
local l = sprite:newLayer()
```

## Sprite.width

The width.
"""


@pytest.fixture(autouse=True)
def fresh_rails():
    saved = (rails.dry_run, rails.max_pixels)
    yield
    rails.dry_run, rails.max_pixels = saved


class FakeBackend:
    def __init__(self):
        self.calls = []

    def exec(self, lua, *, file=None, save=False):
        from aseprite_claude_connector.backends.base import ExecResult

        self.calls.append((lua, save))
        return ExecResult(ok=True, result='{"ok": true}')


@pytest.fixture
def backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(_common, "get_backend", lambda: fake)
    return fake


def _call(tool, args=None):
    return asyncio.run(build_server().call_tool(tool, args or {}))


# --- docs -------------------------------------------------------------------------


def test_sections_follow_headings_and_ignore_code_fences():
    secs = split_sections(PAGE, "u")
    assert [s.title for s in secs] == [
        "Sprite",
        "Sprite > Sprite:newLayer()",
        "Sprite > Sprite.width",
    ]
    assert "# not a heading" in secs[1].text


def test_a_heading_match_outranks_a_passing_mention():
    index = DocIndex(
        split_sections(PAGE, "a") + split_sections("# Other\n\nSee newLayer here.\n", "b")
    )
    assert index.search("newLayer")[0]["title"] == "Sprite > Sprite:newLayer()"
    assert index.search("nothingmatchesthis") == []


def test_bundled_api_docs_find_a_real_method_and_keep_their_licence():
    assert (docs_search.API_DIR / "LICENSE.txt").is_file()
    hit = api_index().search("Image:isEqual", 1)[0]
    assert hit["title"] == "Image > Image:isEqual()"
    assert hit["url"] == "https://www.aseprite.org/api/image"


def _archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in {
            "docs-abc/good.md": "# Good\n",
            "docs-abc/.github/skip.md": "x",
            "docs-abc/pic.png": "x",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(text)
            tar.addfile(info, io.BytesIO(text.encode()))
    return buf.getvalue()


def test_fetch_keeps_only_markdown_in_memory(monkeypatch):
    monkeypatch.setattr(
        docs_search.urllib.request,
        "urlopen",
        lambda *a, **k: io.BufferedReader(io.BytesIO(_archive())),
    )
    assert fetch_markdown("http://x") == {"good.md": "# Good\n"}


def test_the_manual_is_cached_and_survives_going_offline(monkeypatch, tmp_path):
    cache = tmp_path / "manual.json"
    monkeypatch.setattr(docs_search, "_manual_cache", lambda: cache)
    monkeypatch.setattr(docs_search, "fetch_markdown", lambda url: {"a.md": "# A\n"})
    assert docs_search._load_manual() == {"a.md": "# A\n"}
    assert json.loads(cache.read_text()) == {"a.md": "# A\n"}

    def offline(url):
        raise OSError("no network")

    monkeypatch.setattr(docs_search, "fetch_markdown", offline)
    monkeypatch.setattr(docs_search, "MANUAL_TTL", -1)
    assert docs_search._load_manual() == {"a.md": "# A\n"}
    cache.unlink()
    with pytest.raises(OSError):
        docs_search._load_manual()


# --- rails ------------------------------------------------------------------------


def test_no_rails_leaves_the_plain_transaction():
    lua = build_lua("return 1", mutates=True, undo_label="X")
    assert "__snapshot" not in lua and 'app.transaction("X"' in lua


def test_read_only_calls_never_carry_the_rails():
    assert "__snapshot" not in build_lua("return 1", dry_run=True, max_pixels=5)


def test_the_stop_happens_inside_the_transaction():
    lua = build_lua("return 1", mutates=True, dry_run=True)
    assert lua.index("app.transaction(__LABEL") < lua.index("__countChanges(__before")
    assert lua.index("__countChanges(__before") < lua.rindex("end)\nend)")


def test_cap_defaults_on_and_reads_the_environment(monkeypatch):
    rails.max_pixels = None
    assert rails.cap() == 250_000
    rails.max_pixels = None
    monkeypatch.setenv("ASEPRITE_MCP_MAX_PIXELS", "10")
    assert rails.cap() == 10


def test_dry_run_never_saves_in_headless(backend):
    rails.dry_run = True
    run("return J({})", mutates=True, file="a.aseprite")
    assert backend.calls[0][1] is False


@pytest.mark.parametrize(
    "body",
    ["img:saveAs(OUT)", "s:saveCopyAs(OUT)", "app.command.ExportSpriteSheet{}", "app.open(PATH)"],
)
def test_dry_run_refuses_what_a_rollback_cant_undo(backend, body):
    rails.dry_run = True
    with pytest.raises(ToolError, match="dry run"):
        run(body, mutates=True)
    assert backend.calls == []


def test_run_lua_refuses_in_a_dry_run(backend):
    rails.dry_run = True
    with pytest.raises(FastMCPToolError, match="dry run"):
        _call("run_lua", {"code": "return 1"})
    assert backend.calls == []


def test_set_safety_rails_rejects_a_negative_cap():
    with pytest.raises(FastMCPToolError, match="0 or more"):
        _call("set_safety_rails", {"max_changed_pixels": -1})


# --- edit_batch -------------------------------------------------------------------


STEPS = [
    {"tool": "draw_line", "args": {"x1": 0, "y1": 0, "x2": 3, "y2": 3, "color": "#ff0000"}},
    {"tool": "add_layer", "args": {"name": "top"}},
]


def test_batch_is_one_call_and_one_transaction(backend):
    _call("edit_batch", {"steps": STEPS, "label": "Two things"})
    assert len(backend.calls) == 1
    lua = backend.calls[0][0]
    assert lua.count("app.transaction(") == 1 and '"Two things"' in lua
    assert "__steps[2]" in lua
    assert rails.capturing is False


def test_combined_steps_return_a_json_list():
    assert (
        _combine(["return J(1)"])
        .rstrip()
        .endswith('return "[" .. table.concat(__steps, ",") .. "]"')
    )


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ([], "1-100"),
        ([{"tool": "nope"}], "unknown tool"),
        ([{"tool": "get_palette"}], "doesn't edit"),
        ([{"tool": "export_sprite", "args": {"out_path": "a.png"}}], "can't be batched"),
        ([{"tool": "draw_line", "args": {"bad": 1}}], "step 1"),
        ([{**STEPS[0], "args": {**STEPS[0]["args"], "preview": True}}], "preview"),
    ],
)
def test_batch_refuses_bad_steps_before_touching_the_sprite(monkeypatch, steps, message):
    fake = FakeBackend()
    fake.exec_result = None
    monkeypatch.setattr(_common, "get_backend", lambda: fake)
    with pytest.raises(FastMCPToolError, match=message):
        _call("edit_batch", {"steps": steps})
    assert not any("app.transaction" in lua for lua, _ in fake.calls)
    assert rails.capturing is False


# --- polish -----------------------------------------------------------------------


def test_select_tools_can_be_batched_with_an_edit(backend):
    steps = [
        {"tool": "select_frame", "args": {"number": 2}},
        {"tool": "select_layer", "args": {"name": "top"}},
        STEPS[0],
    ]
    _call("edit_batch", {"steps": steps})
    lua = backend.calls[0][0]
    assert (
        len(backend.calls) == 1 and "__steps[3]" in lua and "app.activeFrame = s.frames[N]" in lua
    )


def test_ping_pong_doesnt_double_the_turnaround():
    assert frame_order(1, 4, "pingpong") == [1, 2, 3, 4, 3, 2]
    assert frame_order(1, 4, "pingpong_reverse") == [4, 3, 2, 1, 2, 3]
    assert frame_order(2, 4, "reverse") == [4, 3, 2]
    assert frame_order(3, 3, "pingpong") == [3]


def test_no_tags_gives_one_looping_default():
    assert animations([100, 100], []) == [{"name": "default", "frames": [1, 2], "loop": True}]


def test_repeats_stop_the_loop_and_same_names_stay_distinct():
    tags = [
        {"name": "hit", "from": 1, "to": 2, "repeats": 2},
        {"name": "hit", "from": 1, "to": 1, "repeats": 0},
    ]
    a, b = animations([100, 100], tags)
    assert a == {"name": "hit", "frames": [1, 2, 1, 2], "loop": False}
    assert b["name"] == "hit_2" and b["loop"] is True


def test_tres_keeps_timing_and_only_the_frames_it_uses():
    anims = [{"name": 'a"b', "frames": [2, 3], "loop": True}]
    text = build_tres("res://s.png", 16, 8, [50, 100, 200], anims)
    assert "load_steps=4 format=3" in text
    assert "region = Rect2(16, 0, 16, 8)" in text and "region = Rect2(32, 0, 16, 8)" in text
    assert "Rect2(0, 0" not in text
    assert '"duration": 1.0' in text and '"duration": 2.0' in text and '"speed": 10.0' in text
    assert r'&"a\"b"' in text


def test_res_path_comes_from_the_nearest_project(tmp_path):
    (tmp_path / "project.godot").write_text("")
    sub = tmp_path / "art" / "hero"
    sub.mkdir(parents=True)
    assert res_path_for(str(sub / "a.png")) == ("res://art/hero/a.png", True)
    assert res_path_for("/nowhere/a.png") == ("res://a.png", False)
