"""The command-line entry point: --help and --version answer without starting the server."""

import subprocess
import sys

from aseprite_claude_connector import __version__


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "aseprite_claude_connector", *args],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )


def test_help_prints_usage_and_exits():
    for flag in ("--help", "-h"):
        r = _run(flag)
        assert r.returncode == 0
        assert "usage: aseprite-claude-connector" in r.stdout
        assert "setup" in r.stdout
        assert "[relay]" not in r.stderr  # the server (and its relay) never started


def test_version_prints_the_installed_version():
    for flag in ("--version", "-V"):
        r = _run(flag)
        assert r.returncode == 0
        assert r.stdout.strip() == f"aseprite-claude-connector {__version__}"
        assert "[relay]" not in r.stderr
