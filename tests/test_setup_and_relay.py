"""One-step setup: the extension package and the auto-started relay."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import zipfile

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from aseprite_live_mcp import __version__, relay
from aseprite_live_mcp.backends.live import LiveBackend
from aseprite_live_mcp.config import load_config
from aseprite_live_mcp.setup import (
    EXTENSION_DIR,
    EXTENSION_FILE,
    build_extension,
    install_extension,
)

# Clear of the real relay, which may be running on this machine.
TEST_WS, TEST_HTTP = 19877, 19878


def test_extension_package_is_installable(tmp_path):
    built = build_extension(tmp_path)
    assert built.name == EXTENSION_FILE
    with zipfile.ZipFile(built) as z:
        assert sorted(z.namelist()) == ["claude-bridge.lua", "package.json"]
        manifest = json.loads(z.read("package.json"))
    paths = [s["path"] for s in manifest["contributes"]["scripts"]]
    assert paths == ["./claude-bridge.lua"]
    assert manifest["version"] == __version__


def test_install_matches_aseprites_own_layout(tmp_path):
    dest = install_extension(tmp_path)
    assert dest.parent == tmp_path
    assert dest.name == json.loads((dest / "package.json").read_text())["name"]
    info = json.loads((dest / "__info.json").read_text())
    assert sorted(info["installedFiles"]) == sorted(p.name for p in dest.iterdir())
    assert install_extension(tmp_path) == dest  # running setup again is safe


def test_extension_keeps_the_hard_won_networking_details():
    lua = (EXTENSION_DIR / "claude-bridge.lua").read_text(encoding="utf-8")
    assert "onreceive = function(mt, data)" in lua
    assert "deflate = false" in lua
    assert "function init(plugin)" in lua and "function exit(plugin)" in lua


def test_autostart_config(monkeypatch):
    for key in ("ASEPRITE_MCP_BACKEND", "ASEPRITE_RELAY_URL", "ASEPRITE_MCP_NO_RELAY"):
        monkeypatch.delenv(key, raising=False)
    assert load_config().relay_autostart is True
    monkeypatch.setenv("ASEPRITE_MCP_NO_RELAY", "1")
    assert load_config().relay_autostart is False
    monkeypatch.delenv("ASEPRITE_MCP_NO_RELAY")
    monkeypatch.setenv("ASEPRITE_RELAY_URL", "http://127.0.0.1:1234")
    assert load_config().relay_autostart is False
    monkeypatch.delenv("ASEPRITE_RELAY_URL")
    monkeypatch.setenv("ASEPRITE_MCP_BACKEND", "headless")
    assert load_config().relay_autostart is False


@pytest.fixture(scope="module")
def running_relay():
    patch = pytest.MonkeyPatch()
    patch.setattr(relay, "WS_PORT", TEST_WS)
    patch.setattr(relay, "HTTP_PORT", TEST_HTTP)
    assert relay.ensure_running() is True
    yield f"127.0.0.1:{TEST_HTTP}"
    patch.undo()


def _request(host_port, path, *, data=None, headers=None):
    req = urllib.request.Request(f"http://{host_port}{path}", data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_ensure_running_is_idempotent(running_relay):
    assert relay.ensure_running() is True


def test_status_and_a_clear_message_without_aseprite(running_relay):
    assert _request(running_relay, "/status")[1]["connected"] is False
    _, res = _request(running_relay, "/exec", data=b"return 1")
    assert res["ok"] is False and "setup" in res["error"]


def test_a_second_owner_cannot_share_the_ports(running_relay):
    with pytest.raises(OSError):
        relay._HttpServer(("127.0.0.1", TEST_HTTP), relay.Http)


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Host": "evil.example"},
    ],
)
def test_browsers_are_refused(running_relay, headers):
    with pytest.raises(urllib.error.HTTPError) as e:
        _request(running_relay, "/exec", data=b"return 1", headers=headers)
    assert e.value.code == 403


def test_a_dead_relay_is_revived_once(monkeypatch):
    calls = []

    def fake_ensure():
        calls.append(1)
        return True

    monkeypatch.setattr(relay, "ensure_running", fake_ensure)
    backend = LiveBackend("http://127.0.0.1:1", 1.0, autostart=True)
    res = backend.exec("return 1")
    assert res.ok is False and calls == [1]
    off = LiveBackend("http://127.0.0.1:1", 1.0)
    assert off.exec("return 1").ok is False and calls == [1]


def test_the_bridge_socket_takes_aseprite_but_not_web_pages(running_relay):
    url = f"ws://127.0.0.1:{TEST_WS}"
    with connect(url, origin=url, compression=None):  # the Origin Aseprite really sends
        pass
    with connect(url, compression=None):
        pass
    for origin in ("https://evil.example", "http://127.0.0.1:9877", "null"):
        with pytest.raises(InvalidStatus):
            connect(url, origin=origin, compression=None)
