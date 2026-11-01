"""Ask a real Aseprite whether ``setup`` put the extension where it will look.

``setup`` works out Aseprite's user folder on its own, so a wrong guess would pass every
other test and only show up as an extension that never loads. Run it with
``ASEPRITE_PATH`` set. Exits non-zero on a mismatch.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from aseprite_claude_connector.config import load_config
from aseprite_claude_connector.setup import (
    EXTENSION_FILES,
    EXTENSION_NAME,
    install_extension,
    user_dir,
)

_ASK = 'print("USERDIR=" .. app.fs.userConfigPath)\n'


def main() -> int:
    dest = install_extension()
    print(f"setup installed to {dest}")
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "ask.lua"
        script.write_text(_ASK, encoding="utf-8")
        out = subprocess.run(
            [load_config().aseprite_path, "--batch", "--script", str(script)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    print(out.stdout, out.stderr, file=sys.stderr)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("USERDIR=")]
    if not lines:
        print("Aseprite didn't report its user folder")
        return 1
    theirs = os.path.realpath(lines[0].removeprefix("USERDIR="))
    ours = os.path.realpath(user_dir())
    print(f"Aseprite says {theirs}\nsetup says    {ours}")
    if os.path.normcase(theirs).rstrip("/\\") != os.path.normcase(ours).rstrip("/\\"):
        print("MISMATCH: the extension would never load")
        return 1
    missing = [
        n
        for n in EXTENSION_FILES
        if not (Path(theirs) / "extensions" / EXTENSION_NAME / n).is_file()
    ]
    if missing:
        print(f"missing from the extension folder: {missing}")
        return 1
    print("OK: the extension is where Aseprite looks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
