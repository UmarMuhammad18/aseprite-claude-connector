# Contributing

Thanks for your interest. This is a small, solo-maintained project — issues and
focused PRs are welcome.

## Dev setup

```bash
git clone https://github.com/oaktreegames/aseprite-live-mcp
cd aseprite-live-mcp
pip install -e ".[dev]"
```

Requires Python 3.10+ and Aseprite 1.3+ (set `ASEPRITE_PATH` if it isn't on a
standard install path).

## Before you submit

```bash
ruff check . && ruff format --check .   # lint + format (CI enforces both)
pytest                          # unit + wire-validation + a headless roundtrip (auto-skips if Aseprite is absent)
python tests/smoke_headless.py  # full end-to-end sweep (all tools + resources + prompts) against a throwaway sprite
```

CI runs the suite on Linux/Windows/macOS against both the Python floor (3.10)
and a current Python — a PR that's green locally but red on the floor will be
caught there.

## Adding a tool

Each tool group is a module in `aseprite_live_mcp/tools/` exposing `register(mcp)`.
A tool:

- builds its Lua with `lua_locals(...)` + a static template (never string-formats Lua
  braces), and runs it through `run(...)` from `tools/_common.py`;
- wraps mutating edits so they're one undo step (`run(..., mutates=True)`);
- carries a typed signature + accurate `ToolAnnotations`
  (`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`);
- targets `app.activeSprite` so the same code runs live and headless;
- gets a line in `tests/smoke_headless.py`.

Register the module in `server.py` and update the tool list in the README.

## Notes

- Headless results come back over a temp file — Aseprite's batch `print` is
  unreliable. Don't switch it to stdout.
- Don't touch the relay's websocket details (`deflate=false`, the `onreceive`
  signature, the heartbeat) — they were hard-won; see `docs/ARCHITECTURE.md`.
