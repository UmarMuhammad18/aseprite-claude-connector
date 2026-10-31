"""Export into a game project, and the fixes that keep repeat exports safe."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from aseprite_claude_connector import setup
from aseprite_claude_connector.backends.live import LiveBackend
from aseprite_claude_connector.tools._common import ToolError
from aseprite_claude_connector.tools.game_export import locate, sprite_name
from aseprite_claude_connector.tools.unity_export import _gen_meta, _guid_for


def godot(tmp_path):
    (tmp_path / "project.godot").write_text("")
    return tmp_path


def unity(tmp_path):
    (tmp_path / "Assets").mkdir()
    (tmp_path / "ProjectSettings").mkdir()
    return tmp_path


def test_godot_project_gets_a_new_sprites_folder(tmp_path):
    assert locate(str(godot(tmp_path))) == ("godot", str(tmp_path / "sprites"))


def test_existing_assets_folder_is_used(tmp_path):
    (godot(tmp_path) / "assets").mkdir()
    assert locate(str(tmp_path)) == ("godot", str(tmp_path / "assets"))


def test_sprites_folder_beats_assets(tmp_path):
    (godot(tmp_path) / "assets" / "sprites").mkdir(parents=True)
    assert locate(str(tmp_path)) == ("godot", str(tmp_path / "assets" / "sprites"))


def test_unity_goes_under_assets(tmp_path):
    expected = os.path.normpath(tmp_path / "Assets" / "Sprites")
    assert locate(str(unity(tmp_path))) == ("unity", expected)


def test_a_folder_inside_a_project_is_taken_as_chosen(tmp_path):
    inner = godot(tmp_path) / "characters" / "hero"
    inner.mkdir(parents=True)
    assert locate(str(inner)) == ("godot", str(inner))


def test_plain_folder_named_sprites_is_used_directly(tmp_path):
    folder = tmp_path / "Sprites"
    folder.mkdir()
    assert locate(str(folder)) == ("folder", str(folder))


def test_plain_folder_gets_a_sprites_subfolder(tmp_path):
    assert locate(str(tmp_path)) == ("folder", str(tmp_path / "sprites"))


def test_missing_game_folder_is_an_error(tmp_path):
    with pytest.raises(ToolError, match="not found"):
        locate(str(tmp_path / "nope"))


def test_name_comes_from_the_sprite_file():
    assert sprite_name("C:\\art\\campfire.aseprite", None) == "campfire"
    assert sprite_name("/art/hero.ase", "knight") == "knight"


@pytest.mark.parametrize("filename, name", [("", None), ("x.ase", "a/b"), ("x.ase", "a:b")])
def test_unusable_names_are_refused(filename, name):
    with pytest.raises(ToolError):
        sprite_name(filename, name)


def test_unity_export_keeps_its_guid(tmp_path):
    meta = tmp_path / "hero.png.meta"
    first = _guid_for(str(meta))
    text, _ = _gen_meta(first, 16, 3, 8, 8, "hero", 0.5, 0.5)
    meta.write_text(text, encoding="utf-8")
    assert _guid_for(str(meta)) == first
    assert _gen_meta(first, 16, 3, 8, 8, "hero", 0.5, 0.5)[0] == text


def test_setup_moves_a_local_registration_to_user_scope(monkeypatch):
    calls = []

    def fake_run(cmd, **_):
        calls.append(cmd[1:3] + cmd[-2:])
        stdout = "aseprite:\n  Scope: Local config" if cmd[2] == "get" else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(setup.shutil, "which", lambda _: "claude")
    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    assert setup.register_claude_code("aseprite").startswith("Registered")
    assert [c[1] for c in calls] == ["get", "remove", "add-json"]
    assert calls[1][-2:] == ["-s", "local"] and calls[2][-2:] == ["--scope", "user"]


def test_setup_leaves_a_user_registration_alone(monkeypatch):
    done = SimpleNamespace(returncode=0, stdout="  Scope: User config", stderr="")
    monkeypatch.setattr(setup.shutil, "which", lambda _: "claude")
    monkeypatch.setattr(setup.subprocess, "run", lambda *_a, **_k: done)
    assert "already" in setup.register_claude_code("aseprite")


def test_handover_waits_for_the_extension(monkeypatch):
    backend = LiveBackend("http://127.0.0.1:1", 1)
    replies = [{"ok": False, "error": "Aseprite isn't connected."}, {"ok": True, "result": "1"}]
    monkeypatch.setattr(backend, "_post", lambda _lua: replies.pop(0))
    monkeypatch.setattr("time.sleep", lambda _s: None)
    assert backend._post_after_handover("return 1")["ok"]
    assert not replies


def test_handover_passes_other_errors_straight_back(monkeypatch):
    backend = LiveBackend("http://127.0.0.1:1", 1)
    posts = []
    monkeypatch.setattr(
        backend, "_post", lambda lua: posts.append(lua) or {"ok": False, "error": "x"}
    )
    assert backend._post_after_handover("return 1")["error"] == "x"
    assert len(posts) == 1
