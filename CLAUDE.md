# aseprite-claude-connector

A fork of [aseprite-live-mcp](https://github.com/oaktreegames/aseprite-live-mcp)
(MIT, © Kyle Ocheltree / OakTree Games) that is becoming **aseprite-claude-connector**:
Claude drawing in a running Aseprite, with setup simple enough to need no terminal
babysitting. Our remote is `UmarMuhammad18/aseprite-claude-connector`.

The rename hasn't started: the package, CLI, MCP server name, and PyPI references
all still say `aseprite-live-mcp` / `aseprite_live_mcp`.

## Targets

- **Platforms:** Windows and Mac.
- **Aseprite:** the standalone build, not Steam.
- **Game engines:** Godot and Unity.
- **Repo:** public. Never commit secrets, API keys, or personal file paths; keep
  machine-specific config at local scope.

## How it works

```
Claude ⇄ MCP server (stdio) ⇄ HTTP :9878 ⇄ relay ⇄ WS :9877 ⇄ claude-bridge.lua in Aseprite
```

- **`aseprite_live_mcp/`** — FastMCP server with 139 tools. One module per group in
  `tools/`, each exposing `register(mcp)`. Tools generate Lua and run it through
  `run()` in `tools/_common.py`.
- **Two backends, one tool surface** — `live` (default) runs Lua in the open editor
  via the relay; `headless` runs `aseprite --batch` against files on disk.
- **`bridge/relay_server.py`** — hosts the WebSocket, because Aseprite's Lua
  `WebSocket` can only dial out. Binds to `127.0.0.1` only.
- **`aseprite_client/claude-bridge.lua`** — runs inside Aseprite and executes the Lua
  it receives. Stop it by closing its panel.

The relay and the Lua script are not in the wheel; they ship only in this repo.
Read `docs/ARCHITECTURE.md` before changing anything in the live path, and
`SECURITY.md` before changing what can reach `/exec`.

## Run it (Windows, this machine)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[relay,dev]"
.venv/Scripts/python bridge/relay_server.py        # keep running
```

Install the bridge once by copying `aseprite_client/claude-bridge.lua` to
`%APPDATA%\Aseprite\scripts\`. Re-copy it after every edit: Aseprite runs the
installed copy, not the one in this repo.

In Aseprite, open a sprite and run **File > Scripts > claude-bridge**, allowing access
when prompted. The Status line must read `connected to Claude`; `connecting...` and
`bridge started - waiting for Claude` both mean it isn't connected yet. To confirm:

```bash
curl http://127.0.0.1:9878/status    # {"connected": true, "info": "aseprite 1.3.17.2 | ..."}
```

`config.py` auto-detects standard Aseprite install paths, including `Program Files
(x86)`. Set `ASEPRITE_PATH` for anything else.

Claude Code connects through a local-scope registration, which is stored in the
user's config rather than the repo. Set one up with `claude mcp add-json`, using the
venv's `aseprite-live-mcp.exe` and `ASEPRITE_MCP_BACKEND=live`. Don't add a
`.mcp.json`.

## Checks

```bash
.venv/Scripts/python -m pytest                     # unit + wire-validation
.venv/Scripts/python tests/smoke_headless.py       # every tool, against real Aseprite
.venv/Scripts/python scripts/gen_docs.py           # regenerate the README tool list
```

CI also runs `ruff check .`, `ruff format --check .`, and `gen_docs.py --check`.
Ruff isn't in the `dev` extra, so install it separately. Set
`ASEPRITE_MCP_NO_UPDATE_CHECK=1` for local runs to skip the PyPI lookup.

## Rules

- **Every mutating tool is one named undo step:** `run(..., mutates=True)`.
- **Tools target `app.activeSprite`** so the same code runs live and headless. Build
  Lua with `lua_locals(...)` and a static template, never by string-formatting Lua.
- **A new tool** needs a typed signature, accurate `ToolAnnotations`, and a line in
  `tests/smoke_headless.py`. New modules are registered in `server.py`.
- **Never block inside the bridge.** Interactive tools are two-phase: a start call
  plus a poll call.
- **Logs go to stderr.** Stdout is JSON-RPC on stdio.
- **Keep the sockets on `127.0.0.1`.** `/exec` is equivalent to local code execution.
- **Don't "fix" the networking details:** `onreceive(messageType, data)`,
  `compression=None` on the relay, and the `Timer` heartbeat are all deliberate.
- **Test edits on a new layer, and never save them to the user's art.** Saving to a
  `.png` flattens it.
- **Check visual work with `look`, not just tool results.** A tool can report success
  while the picture is wrong.
- **Never write files from Lua in the look tools.** It raises a modal security prompt
  in the live editor. See "Canvas vision" in `docs/ARCHITECTURE.md`.

## Known issues

- **`mcp` is pinned to `<2`.** The 2.x SDK replaced `mcp.server.fastmcp` with
  `MCPServer`, so the server can't import on it. Migrating is separate work.
- **`uvx aseprite-live-mcp` installs the upstream package**, not this fork.
- **The update check queries upstream's PyPI entry**, so `status` reports upstream's
  releases until `update_check.py` is pointed elsewhere.
- **`test_headless_roundtrip` ignores `ASEPRITE_PATH`** and only checks the
  auto-detected paths, so it skips on non-standard installs.
- **The relay keeps a stale `info`** in `/status` after a disconnect. Trust
  `connected`, not `info`.
- **`set_color_mode` to `indexed` can blank a sprite** when the palette has one
  entry, which is the default for a new sprite. Apply a palette first.
- **`tween_frames` does nothing for frames made with the drawing tools**, because
  they leave every cel at (0, 0). Set the end cel with `set_cel_position` first.
- **Other tools that write files from Lua can hit the security prompt live**, such as
  the exports. So far it has only been seen with `Image:saveAs`.

## Roadmap

### 1. Fork and run — done

Done: the package installs, the relay and bridge connect, and a test edit landed in
an open sprite and undid cleanly. The server is registered with Claude Code at local
scope, and headless mode finds Aseprite on its own.

Not yet scheduled: renaming the package, CLI, and server to aseprite-claude-connector.

### 2. Claude's eyes — done

`look`, `look_animation`, `look_onion`, and a `preview` flag on the 10 drawing tools
in `draw.py` return pictures straight to Claude. Finish line met in the live editor:
`look_animation` exposed a broken tween that every tool result had reported as a
success.

### 3. One-step setup

Start the relay automatically and package the bridge as an Aseprite extension, so
nobody has to copy a script, run a terminal, or open File > Scripts by hand.

### 4. Docs search, `describe_sprite`, and safety rails

- Docs search: let Claude look up Aseprite's scripting API.
- `describe_sprite`: a single summary of the sprite in one call.
- Safety rails: a dry-run mode, a cap on how many pixels one call can change, and a
  single undo step per request so you can always roll back.

### Godot export (must-have, no phase assigned yet)

One-action export to Godot (sprite sheet plus a `SpriteFrames` `.tres` resource with
animations from tags), to match the Unity export that already exists.
