"""One-step setup: ``aseprite-claude-connector setup``.

Registers this server with Claude Code and installs the Claude Bridge extension. It
never touches Aseprite's trust settings: the access prompt stays yours to answer,
the first time the extension connects.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

EXTENSION_DIR = Path(__file__).parent / "extension"
EXTENSION_NAME = "aseprite-claude-connector"
EXTENSION_FILE = f"{EXTENSION_NAME}.aseprite-extension"
EXTENSION_FILES = ("package.json", "claude-bridge.lua", "game-export.lua")


def build_extension(out_dir: Path) -> Path:
    """Zip the bridge into an installable ``.aseprite-extension``."""
    out = out_dir / EXTENSION_FILE
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in EXTENSION_FILES:
            z.write(EXTENSION_DIR / name, name)
    return out


def user_dir() -> Path:
    """Aseprite's per-user folder, as ResourceFinder::includeUserDir resolves it."""
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Aseprite"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Aseprite"
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "aseprite"


def install_extension(extensions_dir: Path | None = None) -> Path:
    """Install the bridge the way Aseprite's own installer lays it out: unpacked in
    the user's extensions folder, with ``__info.json`` listing its files so
    Preferences > Extensions can uninstall it. Installing again replaces it."""
    dest = (extensions_dir or user_dir() / "extensions") / EXTENSION_NAME
    dest.mkdir(parents=True, exist_ok=True)
    for name in EXTENSION_FILES:
        shutil.copyfile(EXTENSION_DIR / name, dest / name)
    info = {"installedFiles": [*EXTENSION_FILES, "__info.json"]}
    (dest / "__info.json").write_text(json.dumps(info), encoding="utf-8")
    return dest


def register_claude_code(name: str) -> str:
    """Add the server to Claude Code in the user's own config, never a repo file."""
    claude = shutil.which("claude")
    if claude is None:
        return "Claude Code not found, so nothing was registered."
    probe = subprocess.run([claude, "mcp", "get", name], capture_output=True, text=True)
    if probe.returncode == 0 and "Scope: Local" not in probe.stdout:
        return f"Claude Code already has a server named '{name}'."
    if probe.returncode == 0:
        # A local entry only matches this exact spelling of the folder, and VS Code can
        # open the same folder under another, which hides the tools.
        subprocess.run([claude, "mcp", "remove", name, "-s", "local"], capture_output=True)
    config = {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "aseprite_claude_connector"],
        "env": {"ASEPRITE_MCP_BACKEND": "live"},
    }
    add = [claude, "mcp", "add-json", name, json.dumps(config), "--scope", "user"]
    res = subprocess.run(add, capture_output=True, text=True)
    if res.returncode != 0:
        return f"Claude Code registration failed: {(res.stderr or res.stdout).strip()}"
    return f"Registered '{name}' with Claude Code."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aseprite-claude-connector setup",
        description="Connect Claude to Aseprite: register the server and install the extension.",
    )
    parser.add_argument("--name", default="aseprite", help="server name in Claude Code")
    parser.add_argument(
        "--no-register", action="store_true", help="skip the Claude Code registration"
    )
    parser.add_argument(
        "--out", type=Path, help="write a .aseprite-extension here instead of installing"
    )
    args = parser.parse_args(argv)

    if not args.no_register:
        print(register_claude_code(args.name))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        print(f"Wrote {build_extension(args.out)}")
        return 0

    print(f"Installed the Claude Bridge extension in {install_extension()}")
    # Closing the window on a Mac leaves the app running, with the old extension loaded.
    restart = "Quit it with Cmd+Q and reopen it" if sys.platform == "darwin" else "Reopen it"
    print(
        f"Restart Aseprite if it's open. {restart}. It asks once to allow the connection: "
        "tick the box to remember, then allow it."
    )
    return 0
