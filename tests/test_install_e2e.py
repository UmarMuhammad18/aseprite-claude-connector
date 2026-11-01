"""Run the real ``setup`` command and the real server as a user would, on each OS.

CI runs this on macOS too, so these are the Mac install tests: everything short of
Aseprite itself, which ``.github/workflows/mac.yml`` covers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aseprite_claude_connector import config
from aseprite_claude_connector.setup import EXTENSION_FILES, EXTENSION_NAME, user_dir

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake claude is a shell script")


def _home_env(tmp_path: Path) -> dict:
    env = {**os.environ, "HOME": str(tmp_path), "APPDATA": str(tmp_path)}
    env.pop("XDG_CONFIG_HOME", None)
    return env


def _setup(env: dict, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "aseprite_claude_connector", "setup", *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)


def _expected_user_dir(home: Path) -> Path:
    if sys.platform == "win32":
        return home / "Aseprite"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Aseprite"
    return home / ".config" / "aseprite"


def test_setup_installs_the_extension_into_this_systems_user_folder(tmp_path):
    res = _setup(_home_env(tmp_path), "--no-register")
    assert res.returncode == 0, res.stderr
    folder = _expected_user_dir(tmp_path) / "extensions" / EXTENSION_NAME
    assert sorted(p.name for p in folder.iterdir()) == sorted([*EXTENSION_FILES, "__info.json"])
    assert "Restart Aseprite" in res.stdout


def test_setup_says_how_to_quit_on_this_system(tmp_path):
    out = _setup(_home_env(tmp_path), "--no-register").stdout
    assert ("Cmd+Q" in out) == (sys.platform == "darwin")


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("darwin", "Library/Application Support/Aseprite"),
        ("linux", ".config/aseprite"),
    ],
)
def test_user_folder_on_other_systems(monkeypatch, tmp_path, platform, expected):
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert user_dir() == tmp_path / Path(expected)


def test_a_personal_applications_folder_is_found(monkeypatch, tmp_path):
    app = tmp_path / "Applications" / "Aseprite.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app / "aseprite").write_text("")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(
        config, "_DEFAULT_ASEPRITE_PATHS", ["~/Applications/Aseprite.app/Contents/MacOS/aseprite"]
    )
    assert Path(config._default_aseprite()) == app / "aseprite"


@unix_only
def test_setup_registers_through_the_claude_command(tmp_path):
    log = tmp_path / "calls.log"
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\necho "$@" >> "$CLAUDE_LOG"\n[ "$2" = "get" ] && exit 1\nexit 0\n')
    fake.chmod(0o755)
    env = _home_env(tmp_path)
    env["PATH"] = f"{fake.parent}{os.pathsep}{env['PATH']}"
    env["CLAUDE_LOG"] = str(log)
    res = _setup(env)
    assert res.returncode == 0, res.stderr
    assert "Registered 'aseprite'" in res.stdout
    added = [ln for ln in log.read_text().splitlines() if ln.startswith("mcp add-json")][0]
    assert "--scope user" in added
    entry = json.loads(added[added.index("{") : added.rindex("}") + 1])
    assert entry["command"] == sys.executable
    assert entry["env"] == {"ASEPRITE_MCP_BACKEND": "live"}


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_the_server_starts_the_way_claude_starts_it(tmp_path):
    env = {
        **_home_env(tmp_path),
        "ASEPRITE_MCP_NO_RELAY": "1",
        "ASEPRITE_MCP_NO_UPDATE_CHECK": "1",
        "ASEPRITE_MCP_BACKEND": "live",
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "aseprite_claude_connector"], env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    assert {"look", "check_loop", "export_to_game"} <= names
