# Architecture

## Two backends, one tool surface

Every MCP tool this server exposes is backend-agnostic. The backend decides
*where* the generated Lua runs:

- **Live backend** — the Lua runs inside the artist's **running** Aseprite via the
  relay. Sees all open documents and unsaved state; each edit is a single undo
  step. This is the differentiating path.
- **Headless backend** — the Lua runs against a `.aseprite` file on disk via
  `aseprite --batch --script`. No editor needed; good for CI/batch. This is what
  every other Aseprite MCP does exclusively.

The server picks the backend per configuration (and, where it matters, per tool):
if a live editor is connected, live tools use it; headless tools always spawn a
batch process.

## Why the editor connects to us (not the reverse)

Aseprite's Lua `WebSocket` API can only act as a **client** — it dials out, it
cannot listen. So the relay hosts the WebSocket server and the Claude Bridge
extension connects to it. Every live-GUI Aseprite tool (this one, Aseprite MCP Pro, Dizzd,
Shexiaoyun) is forced into this same shape by the API; it is not a novel trick.

## Wire protocol (relay ⇄ editor)

One text frame per message:

```
request   = "<id>\n<lua code>"
response  = "<id>\nOK\n<result>"      (success; result is tostring(returned value))
          | "<id>\nERR\n<error>"      (compile or runtime error)
```

The relay exposes HTTP on `127.0.0.1:9878`:
- `POST /exec` — body is raw Lua; returns `{ok, result}` or `{ok:false, error}`.
- `GET  /status` — `{connected, info}` for health.

The WebSocket listens on `127.0.0.1:9877`.

### Hard-won networking facts (do not regress)

- The in-editor callback signature is `onreceive(messageType, data)` with
  `WebSocketMessageType.TEXT/OPEN/CLOSE`. An `onreceivetext` parameter is
  **silently ignored** (sends work, receives vanish).
- The relay refuses permessage-deflate (`compression=None`); Aseprite's
  IXWebSocket client and python-websockets disagree on it and frames vanish.
- A ticking `Timer` heartbeat in the client keeps Aseprite's event loop pumping
  callbacks while the window is unfocused (an idle editor starves them).
- Aseprite's client sends `Origin: ws://127.0.0.1:9877`, so the relay can't simply
  refuse every Origin. Browsers only send http(s) or `null`, so allowing that one
  value still keeps web pages out.

## Who starts what

`relay.py` runs on a daemon thread inside the MCP server, so it lives and dies with
that server. Only one process can own the ports: `ensure_running` lets a second
server fail quietly and use the first one's relay, and `LiveBackend` starts its own
if the relay later refuses a connection. The extension retries every few seconds, so
it finds whichever relay is up. `ASEPRITE_MCP_NO_RELAY=1` turns auto-start off.

The extension connects on its first `Timer` tick rather than in `init`, because
connecting can raise Aseprite's access prompt, which needs the UI to be up.

`setup` installs the extension by unpacking it into Aseprite's per-user `extensions`
folder with an `__info.json` file list, which is exactly what Aseprite's own installer
writes. Passing a `.aseprite-extension` to `Aseprite.exe` doesn't work: it tries to
load it as a sprite.

## Port map (avoid collisions)

| Port | Who |
|---|---|
| 9877 | this relay — WebSocket (editor connects here) |
| 9878 | this relay — HTTP (`/exec`, `/status`) |
| 9876 | Blender MCP bridge; also Dizzd/Shexiaoyun Aseprite tools — **avoid** |
| 6515 | Aseprite MCP Pro (commercial) |

## The MCP layer

Wrapping the relay as a real MCP server, per the current best-practice set:

- **SDK**: the official MCP Python SDK's bundled `mcp.server.fastmcp.FastMCP`
  (decorator API). *Not* PrefectHQ's standalone FastMCP — the README states the
  lineage to avoid the well-known naming ambiguity.
- **Transport**: `stdio` (local, single-client — the Aseprite-on-your-machine
  case). No HTTP+SSE (deprecated 2025-03-26).
- **Spec**: target the current stable **2025-11-25** revision (declare it, send the
  `MCP-Protocol-Version` header on any HTTP path). The stateless 2026-07-28
  revision is treated as forward-compat work, not claimed as conformance.
- **Tools**: typed input schemas (Pydantic `Annotated` + `Field(description=...)`),
  `outputSchema` + `structuredContent`, and accurate annotations
  (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`).
- **No raw-Lua-as-the-product**: a guarded `run_lua` escape hatch may exist
  (annotated destructive + openWorld), but the primary surface is concrete typed
  tools, each wrapping its edit in `app.transaction()`.
- **Logging**: stderr only (stdout is JSON-RPC framing on stdio).
- **Layout**: one module per tool group; tool logic separated from registration; a
  single server file registers them.

## The live-interaction layer (v0.2)

Interactive tools (in-editor dialogs, ask-the-artist point picking, artist-edit
watching) are **two-phase and non-blocking** by contract: a start call registers
UI or an event listener and returns immediately; a poll call fetches the
outcome. Blocking inside a bridge command would stall Aseprite's event loop and
the relay heartbeat — nothing in this codebase waits inside the editor.

State between calls lives in the bridge script's Lua environment in one global
table, `__almcp` (globals persist across relay execs — verified on 1.3.17.2).
Two empirical facts the implementation encodes:

- `Editor:cancel()` does **not** fire an `askPoint`'s `oncancel` callback; the
  `cancel_ask_point` tool marks the state itself.
- `Dialog{...}:show{wait=false}` keeps the dialog open across execs; the button
  callbacks write the choice into `__almcp` for the poll tool.

## Canvas vision

`tools/look.py` returns pictures to the model as MCP image content. Lua renders a
frame and returns its raw pixels as base64 over the ordinary result channel;
`raster.py` (stdlib only) zooms, adds the backdrop, lays out panels, diffs, and
encodes the PNG. Two facts shaped this:

- **Never write a temp file from Lua in these tools.** Aseprite tracks trust per
  script, and the bridge runs what it receives under the chunk name `claude`, which
  counts as a separate script from the extension. So `Image:saveAs` raises the
  script-security prompt even when the extension has full trust. The prompt is
  modal: the call hangs until someone answers, and commands sent meanwhile stack more
  prompts on top.
- **The relay's `max_size` must exceed the largest picture payload.** Python's
  websockets defaults to 1 MiB and drops the connection above that.

Only canvases too big for the picture shrink in Lua, which keeps payloads small;
zooming up costs nothing on the wire because it happens in Python.

`previewable` wraps a drawing tool. It renders before and after in separate
read-only calls around the unchanged tool, so the edit stays one undo step, and it
returns a `CallToolResult` so the tool's structured output survives next to the
image. If a render fails, the edit's result still comes back, with `preview_error`.

## Update awareness (v0.2)

`update_check.py` fetches PyPI's public JSON for this package on a daemon
thread (never blocks startup), caches the result for 24h in the platform cache
dir, and surfaces it through the `status` tool, the `aseprite://update`
resource, and a single stderr line. Opt-out: `ASEPRITE_MCP_NO_UPDATE_CHECK=1`;
auto-disabled under `CI`. `serverInfo.version` is set on the lowlevel server at
build time (FastMCP doesn't forward one), so MCP clients see the real release.

## Generated docs

The README's tool reference and the `tools-N` badge are written by
`scripts/gen_docs.py` from the actual registrations; CI runs `--check` and
fails on drift. A hand-edited count can't lie because it doesn't exist.
