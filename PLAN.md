# Aseprite Connector: Fork Plan

Last updated 30 Oct 2026

## Summary

Project name: **aseprite-claude-connector**.

Yes, we can fork it. We should build on **aseprite-live-mcp** by OakTree Games: it is MIT licensed, already drives the running Aseprite editor, and has 139 tools.

What it lacks is what makes the Blender connector feel good: Claude can't actually *see* the canvas. Every edit is done blind, and previews only land as PNG files on disk. The plan is to give Claude eyes first, make setup one step instead of three, then add docs search and smarter animation help on top.

## Project details and status

We are in **phase 1: fork and run**. Live mode works on Umar's Windows PC: a test edit landed in an open sprite and undid cleanly. Left in phase 1: register the server with Claude Code, set `ASEPRITE_PATH` for headless mode, and commit `CLAUDE.md` plus the `mcp>=1.10.0,<2` pin (mcp 2.x removed `FastMCP`).

| | |
| --- | --- |
| Our repo | [UmarMuhammad18/aseprite-claude-connector](https://github.com/UmarMuhammad18/aseprite-claude-connector) |
| Forked from | [oaktreegames/aseprite-live-mcp](https://github.com/oaktreegames/aseprite-live-mcp) (MIT, keep their `LICENSE`) |
| Language | Python 3.10+ |
| Needs | Aseprite 1.3+, Git |
| Platforms | Windows and Mac, Aseprite standalone (not Steam) |
| Game engines | Godot and Unity |
| Visibility | Public on GitHub. Never commit secrets, API keys or personal file paths |
| Built with | Claude Code in VS Code |
| Key files | `aseprite_live_mcp/tools/` (one module per tool group), `aseprite_live_mcp/backends/live.py`, `bridge/relay_server.py`, `aseprite_client/claude-bridge.lua`, `docs/ARCHITECTURE.md` |
| Ports | Relay WebSocket 9877, relay HTTP 9878. Avoid 9876 (Blender connector) |

**Notes for Claude Code**

- Read `docs/ARCHITECTURE.md` before changing the relay or the Lua bridge; it lists networking fixes that must not regress.
- Keep every edit inside `app.transaction()` so each request is one Ctrl-Z.
- Ask before pushing to GitHub. Work on a branch per phase.
- Keep `CLAUDE.md` updated with the current phase and what's done.

## Can we fork it?

Three of the four candidates are MIT licensed, which lets us copy, change and republish the code as long as we keep their copyright notice. The fourth has no licence file, so legally we can read it but not reuse it.

| Repo | Language | Licence | Can we fork and reuse? | Last commit |
| --- | --- | --- | --- | --- |
| [oaktreegames/aseprite-live-mcp](https://github.com/oaktreegames/aseprite-live-mcp) | Python | MIT (Kyle Ocheltree / OakTree Games, 2026) | Yes | 28 Jul 2026 |
| [letsagents/aseprite-mcp](https://github.com/letsagents/aseprite-mcp) | TypeScript | MIT (LuoHan, 2026) | Yes | 12 Aug 2026 |
| [rkdfx/aseprite-mcp](https://github.com/rkdfx/aseprite-mcp) | Python | MIT (2025) | Yes | 17 Apr 2026 |
| [iborymagic/aseprite-mcp](https://github.com/iborymagic/aseprite-mcp) | TypeScript | None found | No, read only | 4 Jan 2026 |

What MIT asks of us: keep the original `LICENSE` file and copyright line in our fork. We can add our own name alongside it.

## Which base to pick

**aseprite-live-mcp** wins clearly. It is the only one that works inside your open Aseprite window, and it is the most complete by a wide margin.

| | aseprite-live-mcp | letsagents/aseprite-mcp | rkdfx/aseprite-mcp |
| --- | --- | --- | --- |
| Works in your open editor | Yes, each edit is one Ctrl-Z | No, files on disk only | No, files on disk only |
| Tools | 139 | 76 | 13 |
| Animation | Tweens, smear frames, onion-skin render, frame diff | Tweens | Basic |
| Talks back to you | In-editor dialogs, "click a point for me", watches your edits | No | No |
| Export | Sprite sheets, tags, layers, Unity sheets with `.meta` | Sprite sheets | PNG, GIF |
| Tests | 3 test files | Tests beside each module | 8 test files |
| Shows Claude the canvas | No, PNGs written to disk | No | No |

The things we'd still want from the others are small: letsagents has tidier per-module tests, which we can copy as a pattern.

## What the Blender connector does that we should match

The Blender connector doesn't win on number of tools. It wins because Claude can look, look things up, and point you at things. aseprite-live-mcp already matches it on running code in the live app; the rest are our gaps.

| Blender connector can | aseprite-live-mcp today | Gap |
| --- | --- | --- |
| Screenshot the window or one panel and show it to Claude | Writes PNGs to disk only | Big |
| Render the viewport or a thumbnail | Onion-skin render to a file | Medium |
| Search the Python API docs and the user manual | One static docs resource | Big |
| Summarise the file: objects, missing files, linked libraries | Sprite info, layers, tags, palette | Small |
| Jump the UI to a tab or an object | Set zoom and scroll | Small |
| Run code in the live app | `run_lua` plus 139 typed tools | None |
| Connects through the Claude desktop app, no manual relay | Copy a script, start a relay by hand, run the script in Aseprite | Big |

## Must-haves

These are what it takes to beat the Blender connector. The first two matter most.

- [ ] **Show Claude the canvas.** A `look` tool that returns the current frame as an image straight into the chat, scaled up with sharp pixels so a 32×32 sprite is readable. Options: one layer, all layers, a selection, or a zoomed-in crop.
- [ ] **Show Claude the animation.** A `look_animation` tool that returns a strip or grid of frames for a tag in one image, plus the onion-skin view returned as an image instead of a file.
- [ ] **Look after every edit, optionally.** A flag on drawing tools that sends back a before/after picture, so Claude can catch its own mistakes without an extra step.
- [ ] **One-step setup.** The server starts the relay itself, and the Aseprite side ships as a proper `.aseprite-extension` you double-click to install, which connects automatically on launch.
- [ ] **Searchable Aseprite docs.** Bundle the Lua API reference and the user manual, with `search_api_docs` and `search_manual` tools, so Claude writes correct scripts first time.
- [ ] **Better state reading.** A `describe_sprite` tool giving one compact summary: size, colour mode, layers, frames, tags, slices, palette and what's selected.
- [ ] **Safety rails.** A dry-run mode, a cap on how many pixels one call can change, and a single undo step per request so you can always roll back.
- [ ] **Godot export.** One-action export to Godot (sprite sheet plus a `SpriteFrames` `.tres` resource with animations from tags), to match the Unity export that already exists.
- [ ] **Works on your OS.** Test the full live setup on Windows and Mac, with standalone Aseprite.

## Cool to have

Nice extras once the must-haves work. Roughly ordered by how much they'd help day-to-day.

**Animation helpers**

- In-betweening: you draw key poses, Claude fills the frames between using tweens and smears, then shows you the result.
- Walk and run cycle templates: pick a body size and frame count, get a timed, tagged skeleton to draw over.
- Timing presets: ease-in, ease-out, hold and bounce applied to frame durations in one call.
- Loop check: compare the last and first frames and flag a jump.

**Colour and cleanup**

- Palette ramps from one colour, with hue shifting in shadows and highlights.
- Orphan pixel and stray-colour finder, with a picture showing where they are.
- Auto outline, one colour or selective, per layer.
- Recolour a sprite into team colours or seasons in one batch.

**Working together**

- Reference images: you drop a sketch in the chat and Claude imports it as a faded guide layer.
- "Fix this bit": you select an area in Aseprite and Claude works only inside it.
- Change summary: after a long session, a short list of what Claude changed, frame by frame.
- Session recording: export the whole build as a GIF timelapse.

**Export and game engines**

- GameMaker export preset beside the Unity and Godot ones.
- Pack several sprites into one atlas with JSON data.

**Learning**

- Explain mode: Claude says which Aseprite tool or shortcut would do what it just did, so you pick up techniques.

## How it fits together

```
Claude (desktop app or Claude Code)
   |  tool calls  ↓        ↑  images back (new)
Our MCP server (Python)
   ├─ Typed tools: 139 today, plus look tools (new)
   ├─ Relay, auto-started (new): WebSocket on this computer
   │     └─ live → Aseprite (open), via bridge extension (new), one undo per edit
   ├─ Docs search (new): Lua API and user manual
   └─ or → aseprite --batch: files on disk, no window
```

The shape stays the same as today. What changes is that the relay starts on its own, Aseprite connects through an installed extension, and pictures of the canvas come back to Claude instead of landing on disk.

## Roadmap

Each phase only starts once the one before passes its finish line.

| Phase | Work | Done when |
| --- | --- | --- |
| 1. Fork and run (current) | Fork on GitHub; get live mode working on Umar's computer | A test edit lands live in the open sprite |
| 2. Claude's eyes | `look` tool, animation strips, before/after views | Claude spots its own mistake from a picture |
| 3. Easy setup | Auto-start relay, Aseprite extension, Windows and Mac tests | Install takes one step |
| 4. Smarter help | Docs search, `describe_sprite`, safety rails, then the cool extras | It beats the Blender connector for sprite work |

Phase 2 makes the biggest difference, so it comes straight after the fork is running.

## Limits, risks and open questions

**Limits to expect**

- Claude is strong at structured work (palettes, tweens, sheets, cleanup) and weaker at expressive freehand drawing. This is an assistant to the artist, not a replacement.
- Aseprite's Lua can only dial out, not listen, so a small relay will always sit between Claude and the editor. We can hide it, not remove it.
- Images sent to Claude use up conversation space, so `look` should send small, cropped pictures by default.

**Risks**

- The original author may change direction. Keep the fork close to theirs and offer improvements back upstream where they fit.
- Aseprite updates can change the Lua API. Pin a tested version and test on each new release.
- Live edits run real code in the editor. Keep the Pause toggle and undo-per-request, and never auto-save over the user's files.

**Open questions**

- None right now.
