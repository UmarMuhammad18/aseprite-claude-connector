"""Headless backend — runs Lua against a file via ``aseprite --batch``.

Aseprite's batch ``print`` is unreliable on stdout (and the PixelLab extension, if
installed, prints a harmless dialog error), so results come back through a temp
file, not stdout. ``aseprite --batch FILE`` loads FILE as ``app.activeSprite``, so
the same tool Lua that targets the active document works here too.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from .base import ExecResult


class HeadlessBackend:
    name = "headless"

    def __init__(self, aseprite_path: str, timeout: float):
        self.aseprite_path = aseprite_path
        self.timeout = timeout

    def exec(self, lua: str, *, file: str | None = None, save: bool = False) -> ExecResult:
        tmpdir = tempfile.mkdtemp(prefix="aselm_")
        script_path = os.path.join(tmpdir, "op.lua")
        result_path = os.path.join(tmpdir, "result.txt")

        rp = result_path.replace("\\", "\\\\")
        save_line = ""
        if save and file:
            fp = file.replace("\\", "\\\\")
            save_line = f'if app.activeSprite then app.activeSprite:saveAs("{fp}") end'

        wrapper = (
            "local __ok, __val = pcall(function()\n"
            f"{lua}\n"
            "end)\n"
            f'local __rf = io.open("{rp}", "w")\n'
            "if __rf then\n"
            '  if __ok then __rf:write("OK\\n" .. tostring(__val == nil and "" or __val))\n'
            '  else __rf:write("ERR\\n" .. tostring(__val)) end\n'
            "  __rf:close()\n"
            "end\n"
            "if __ok then\n"
            f"  {save_line}\n"
            "end\n"
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(wrapper)

        cmd = [self.aseprite_path, "--batch"]
        if file and os.path.isfile(file):
            cmd.append(file)
        cmd += ["--script", script_path]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 30)
        except subprocess.TimeoutExpired:
            return ExecResult(ok=False, error=f"headless Aseprite timed out ({self.timeout + 30}s)")
        except FileNotFoundError:
            return ExecResult(
                ok=False, error=f"Aseprite not found at '{self.aseprite_path}' (set ASEPRITE_PATH)"
            )

        if not os.path.isfile(result_path):
            tail = (proc.stderr or proc.stdout or "").strip()[-600:]
            return ExecResult(
                ok=False, error=f"no result from headless run (exit {proc.returncode}). output: {tail}"
            )
        with open(result_path, "r", encoding="utf-8") as f:
            raw = f.read()
        status, _, body = raw.partition("\n")
        if status == "OK":
            return ExecResult(ok=True, result=body)
        return ExecResult(ok=False, error=body)

    def health(self) -> dict:
        return {
            "backend": "headless",
            "aseprite_path": self.aseprite_path,
            "exists": os.path.isfile(self.aseprite_path),
        }
