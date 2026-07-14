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
- **Explicit trust.** Aseprite prompts you to grant the client script full trust
  the first time you run it; the bridge cannot start without your click. Closing
  the bridge dialog stops it.
- **One undo per edit.** Every edit an agent makes is wrapped in `app.transaction`,
  so a single Ctrl+Z reverts it like any manual action — you are never more than
  one keystroke away from undoing what the agent did.

## Recommendations

- Run the relay only while you are actively driving Aseprite with an agent; stop
  it (close the dialog) when you're done.
- Never expose the relay ports beyond localhost. If you need remote access, put it
  behind an authenticated tunnel you control — that is out of scope and
  unsupported here.
- Review Lua before running it if it comes from an untrusted source, exactly as
  you would review a shell command.

## Reporting

This is a solo-maintained studio tool. For anything security-relevant, open a
private issue rather than a public one.
