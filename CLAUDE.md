# aseprite-claude-connector

A fork of [aseprite-live-mcp](https://github.com/oaktreegames/aseprite-live-mcp)
(MIT, © Kyle Ocheltree / OakTree Games), renamed **aseprite-claude-connector**:
Claude drawing in a running Aseprite, with setup simple enough to need no terminal
babysitting. Our remote is `UmarMuhammad18/aseprite-claude-connector`.

## Targets

- **Platforms:** Windows and Mac.
- **Aseprite:** the standalone build, not Steam.
- **Game engines:** Godot and Unity.
- **Repo:** public. Never commit secrets, API keys, or personal file paths; keep
  machine-specific config at local scope.

## How it works

```
Claude ⇄ MCP server (stdio, runs the relay) ⇄ WS :9877 ⇄ Claude Bridge extension in Aseprite
```

- **`aseprite_claude_connector/`** — FastMCP server with 165 tools. One module per group in
  `tools/`, each exposing `register(mcp)`. Tools generate Lua and run it through
  `run()` in `tools/_common.py`.
- **Two backends, one tool surface** — `live` (default) runs Lua in the open editor
  via the relay; `headless` runs `aseprite --batch` against files on disk.
- **`aseprite_claude_connector/relay.py`** — hosts the WebSocket, because Aseprite's Lua
  `WebSocket` can only dial out. Runs on a thread inside the server and binds to
  `127.0.0.1` only.
- **`aseprite_claude_connector/extension/`** — the Claude Bridge extension, which runs inside
  Aseprite, connects on launch, and executes the Lua it receives.
- **`aseprite_claude_connector/setup.py`** — the `aseprite-claude-connector setup` command.
- **`extension/game-export.lua`** — the Export to Game button. It repeats
  `tools/game_export.py` in Lua because it has to work with no server running. The
  smoke test holds their output byte-equal, so change them together.

Read `docs/ARCHITECTURE.md` before changing anything in the live path, and
`SECURITY.md` before changing what can reach `/exec`.

## Run it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/aseprite-claude-connector setup
```

`setup` registers the server with Claude Code in the user's own config, so no
`.mcp.json` is needed or wanted. It also installs the extension to Aseprite's user
folder. Run it again after editing anything in `aseprite_claude_connector/extension/`:
Aseprite runs the installed copy, not the one in this repo, and only reads it at
launch, so quit Aseprite fully and reopen it.

The server starts the relay. To check the connection while a server is running:

```bash
curl http://127.0.0.1:9878/status    # {"connected": true, "info": "aseprite 1.3.17.2 | ..."}
```

`config.py` auto-detects standard Aseprite install paths, including `Program Files
(x86)`. Set `ASEPRITE_PATH` for anything else.

## Checks

```bash
.venv/Scripts/python -m pytest                     # unit + wire-validation
.venv/Scripts/python tests/smoke_headless.py       # every tool, against real Aseprite
.venv/Scripts/python scripts/gen_docs.py           # regenerate the README tool list
```

The `Mac` workflow compiles Aseprite on a Mac runner and runs `scripts/check_mac.py` and
the smoke test against it. Aseprite's licence covers compiling for your own use, so
never upload or cache that binary.

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
- **Never ship the user manual.** `aseprite/docs` has no licence; only the MIT API
  docs in `api_docs/` are bundled. Refresh them with `scripts/update_api_docs.py`.
- **Keep the sockets on `127.0.0.1`.** `/exec` is equivalent to local code execution.
- **Don't "fix" the networking details:** `onreceive(messageType, data)`,
  `compression=None` on the relay, the `Timer` heartbeat, and the allowed `ws://`
  Origin are all deliberate.
- **Never write to Aseprite's trust settings.** The access prompt is the user's call.
- **Test the live path against real Aseprite.** A fake client passed the Origin check
  that locked out the real one.
- **Test edits on a new layer, and never save them to the user's art.** Saving to a
  `.png` flattens it.
- **Check visual work with `look`, not just tool results.** A tool can report success
  while the picture is wrong.
- **Build export files in Python where you can.** `frames_of` in `tools/look.py` reads
  the pixels, and writing from Python never raises Aseprite's security prompt.
- **Never write files from Lua in the look tools.** It raises a modal security prompt
  in the live editor. See "Canvas vision" in `docs/ARCHITECTURE.md`.
- **Read closed files with a batch Aseprite, not the editor.** Loading one from Lua
  raises the same prompt. `read_sprite` in `tools/atlas.py` shows the pattern.

## Known issues

- **`mcp` is pinned to `<2`.** The 2.x SDK replaced `mcp.server.fastmcp` with
  `MCPServer`, so the server can't import on it. Migrating is separate work.
- **This package isn't on PyPI**, so install from GitHub, and the update check finds
  nothing until a release is published under this name.
- **Tools that write files from Lua should hit the security prompt live**, such as
  the exports. The bridge runs received code under the chunk name `claude`, which
  Aseprite trusts separately from the extension. `Image:saveAs`, `save_sprite`, and
  loading a file with `Sprite{ fromFile = ... }` have all been seen doing this. Umar
  has chosen to give that code full trust, by answering the prompt in Aseprite the
  first time it appears.
- **Exports haven't been opened in real Godot or Unity.** Their text is tested and
  the art was exported live, but no engine has loaded the `.tres` or `.meta`.
- **The Export to Game dialog hasn't been clicked through.** Real Aseprite loads the
  command and its export code passes the smoke test, but the dialog itself needs a
  person.
- **Local-scope registration matches the exact path spelling.** VS Code can open
  this folder as `c:\`, which misses a server registered under `C:/`. `setup` moves a
  local entry to user scope.
- **The live connection hasn't run on a Mac.** CI covers setup and every tool headless
  on a Mac, but the bridge's first connection needs a person to answer Aseprite's
  prompt, and we never write trust settings to get round that.
- **GameMaker strips haven't been opened in GameMaker.** Their names follow its
  `_stripN` import rule.
- **`edit_in_selection` can't be tested headless through the tool,** because a
  selection doesn't survive in a file. The smoke test makes one in the same script, and
  the tool itself was checked in the live editor.
- **`change_summary` has no frames for edits run with `capped=False`,** or with the
  pixel cap off, because the journal reads them from the rails.
- **`setup` run through `uvx` would register a temporary path.** Install with `pip`.
- **`run_lua` is only covered by the rails with `edit=true`.** Without it, the pixel
  cap doesn't apply and it refuses to run in a dry run.
- **A dry-run report comes back as a tool error,** so that no tool has to handle a
  result that didn't happen.
- **A reordered layer counts as changed pixels inside `edit_batch`,** because layers
  have no id in the API. `move_layer` on its own skips the cap.

## Roadmap

### 1. Fork and run — done

Done: the package installs, the relay and bridge connect, and a test edit landed in
an open sprite and undid cleanly. The server is registered with Claude Code at local
scope, and headless mode finds Aseprite on its own.

### 2. Claude's eyes — done

`look`, `look_animation`, `look_onion`, and a `preview` flag on the 10 drawing tools
in `draw.py` return pictures straight to Claude. Finish line met in the live editor:
`look_animation` exposed a broken tween that every tool result had reported as a
success.

### 3. Easy setup — done on Windows

`aseprite-claude-connector setup` registers the server and installs the extension. The server
starts the relay, and Aseprite connects on launch after one access prompt.

The `Mac` workflow checks setup and every tool on a Mac. Only the live editor
connection still needs a person with a Mac.

### 4. Docs search, `describe_sprite`, and safety rails — must-haves done

`search_api_docs`, `search_manual`, `describe_sprite`, `set_safety_rails`, and
`edit_batch` are in. Rollback and one-undo batches were checked in the live editor.
See "Safety rails" in `docs/ARCHITECTURE.md`. The cool extras in `PLAN.md` are built
too: `tools/motion.py`, `tools/cleanup.py`, `tools/session_tools.py`, `tools/atlas.py`,
and `edit_in_selection` in `tools/safety.py`.

### 5. Godot export — built, not yet confirmed in Godot

`export_godot` writes a sprite sheet plus a `SpriteFrames` `.tres` with animations from
tags. The finish line, a tagged animation playing in Godot, still needs checking.

### 6. Export to your game — built, not yet confirmed in an engine

**File → Export → Export to Game...** and `export_to_game` put art straight into a
Godot or Unity project, ready to select. Tested live and headless.
