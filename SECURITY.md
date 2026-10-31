# Security model

This tool gives an AI agent (or any local program) the ability to run Lua inside
a running Aseprite instance. That is powerful, and the security posture is
deliberately simple and explicit.

## Threat model

- **`/exec` runs arbitrary Lua in Aseprite.** The relay's `POST /exec` endpoint
  hands raw Lua to Aseprite's scripting runtime, which can read and write the open
  documents and — once you grant the script trust — touch the filesystem and
  network. Treat the relay as **equivalent to local code execution** on the
  machine running Aseprite.
- **Localhost only.** Both the WebSocket (default `9877`) and HTTP (default `9878`)
  listeners bind to `127.0.0.1`. Nothing is exposed to the network. Do not
  port-forward, reverse-proxy, or bind these to `0.0.0.0`.
- **Browsers are refused.** Any web page can send a plain POST to `127.0.0.1`, so the
  relay turns away HTTP requests that carry an `Origin` header or a foreign `Host`,
  and WebSocket clients with a web `Origin`. Any other program running as you can
  still reach it: this is not authentication.
- **The relay starts with the server.** It runs whenever a live MCP server is
  running, and stops with it. Set `ASEPRITE_MCP_NO_RELAY=1` to start it yourself
  instead.
- **Explicit trust.** Aseprite asks before the Claude Bridge extension first connects;
  the bridge can't connect without your click, and `setup` never edits that setting.
  Once allowed, the extension connects every time Aseprite starts. Use the Pause
  toggle in **File → Scripts → Claude Bridge** to reject commands, or disable the
  extension in **Edit → Preferences → Extensions** to stop it.
- **One undo per edit.** Every edit an agent makes is wrapped in `app.transaction`,
  so a single Ctrl+Z reverts it like any manual action — you are never more than
  one keystroke away from undoing what the agent did.
- **The update check is a read, not telemetry.** At most once a day the server
  fetches `https://pypi.org/pypi/aseprite-live-mcp/json` to learn the latest
  released version. Nothing about you, your machine, or your art is sent —
  it's an HTTP GET of a public document, cached locally, disabled entirely with
  `ASEPRITE_MCP_NO_UPDATE_CHECK=1` (and auto-disabled when `CI` is set). It is
  the only network request this server ever makes on its own.

## Recommendations

- Pause or disable the bridge if you aren't using it and don't want a running
  agent to reach your open documents.
- Never expose the relay ports beyond localhost. If you need remote access, put it
  behind an authenticated tunnel you control — that is out of scope and
  unsupported here.
- Review Lua before running it if it comes from an untrusted source, exactly as
  you would review a shell command.

## Reporting

This is a solo-maintained tool. For anything security-relevant, use GitHub's
private vulnerability reporting (the repo's Security tab → "Report a
vulnerability"), or email hello@oaktree-games.com — please don't open a public
issue for security problems.
