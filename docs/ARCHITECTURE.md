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
cannot listen. So the relay hosts the WebSocket server and the in-editor script
connects to it. Every live-GUI Aseprite tool (this one, Aseprite MCP Pro, Dizzd,
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

## Port map (avoid collisions)

| Port | Who |
|---|---|
| 9877 | this relay — WebSocket (editor connects here) |
| 9878 | this relay — HTTP (`/exec`, `/status`) |
| 9876 | Blender MCP bridge; also Dizzd/Shexiaoyun Aseprite tools — **avoid** |
| 6515 | Aseprite MCP Pro (commercial) |

## The MCP layer (Phase 1)

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
