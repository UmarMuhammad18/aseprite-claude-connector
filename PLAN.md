# Aseprite Connector: Fork Plan

Last updated 31 Oct 2026

## Summary

Project name: **aseprite-claude-connector**.

Yes, we can fork it. We should build on **aseprite-live-mcp** by OakTree Games: it is MIT licensed, already drives the running Aseprite editor, and has 139 tools.

What it lacks is what makes the Blender connector feel good: Claude can't actually *see* the canvas. Every edit is done blind, and previews only land as PNG files on disk. The plan is to give Claude eyes first, make setup one step instead of three, then add docs search and smarter animation help on top.

## Project details and status

Phases 1 to 4 are merged into `main`. **Phase 5: Godot export** and **phase 6: export to your game** are built, but nothing has been opened in a real engine yet. On Umar's Windows PC, Claude can see the canvas, look up Aseprite's docs, and work behind safety rails, and setup is one command plus one permission click in Aseprite. Mac testing is on hold by choice, so nothing has run on a Mac yet.

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
| Key files | `aseprite_claude_connector/tools/` (one module per tool group), `aseprite_claude_connector/tools/look.py`, `aseprite_claude_connector/backends/live.py`, `aseprite_claude_connector/relay.py`, `aseprite_claude_connector/extension/`, `aseprite_claude_connector/setup.py`, `docs/ARCHITECTURE.md` |
| Ports | Relay WebSocket 9877, relay HTTP 9878. Avoid 9876 (Blender connector) |

**Notes for Claude Code**

- Read `docs/ARCHITECTURE.md` before changing the relay or the Lua bridge; it lists networking fixes that must not regress.
- Keep every edit inside `app.transaction()` so each request is one Ctrl-Z.
- Work on a branch per phase. Create and merge pull requests on our repo, and never open one on the original repo.
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
| Search the Python API docs and the user manual | None | Big |
| Summarise the file: objects, missing files, linked libraries | Sprite info, layers, tags, palette | Small |
| Jump the UI to a tab or an object | Set zoom and scroll | Small |
| Run code in the live app | `run_lua` plus 139 typed tools | None |
| Connects through the Claude desktop app, no manual relay | Copy a script, start a relay by hand, run the script in Aseprite | Big |

## Must-haves

These are what it takes to beat the Blender connector. The first two matter most.

- [x] **Show Claude the canvas.** A `look` tool that returns the current frame as an image straight into the chat, scaled up with sharp pixels so a 32×32 sprite is readable. Options: one layer, all layers, a selection, or a zoomed-in crop.
- [x] **Show Claude the animation.** A `look_animation` tool that returns a strip or grid of frames for a tag in one image, plus the onion-skin view returned as an image instead of a file.
- [x] **Look after every edit, optionally.** A flag on drawing tools that sends back a before/after picture, so Claude can catch its own mistakes without an extra step. Covers the drawing tools in `draw.py`, the isometric tools, polygons and stamps.
- [x] **One-step setup.** The server starts the relay itself, and `aseprite-claude-connector setup` installs the Aseprite extension, which connects automatically on launch. `setup --out` also writes a `.aseprite-extension` file for installing by hand.
- [x] **Searchable Aseprite docs.** `search_api_docs` searches the Lua API reference, bundled because it's MIT licensed. `search_manual` searches the user manual, which has no licence, so it downloads to the user's cache instead of shipping with us.
- [x] **Better state reading.** A `describe_sprite` tool giving one compact summary: size, colour mode, layers, frames, tags, slices, palette and what's selected.
- [x] **Safety rails.** A dry-run mode, a cap on how many pixels one call can change (250,000 by default), and `edit_batch`, which makes several tools one undo step. The server can't see where a request starts or ends, so Claude has to choose `edit_batch`. `run_lua` isn't capped.
- [x] **Godot export.** `export_godot` writes a sprite sheet plus a `SpriteFrames` `.tres` resource with animations from tags, to match the Unity export. Still needs opening in real Godot.
- [x] **Export to your game.** File → Export → Export to Game... in Aseprite, or `export_to_game` through Claude, puts art in the project's sprites folder, ready to select in Godot or Unity. Still needs opening in real engines.
- [ ] **Works on your OS.** Test the full live setup on Windows and Mac, with standalone Aseprite. Windows is done; Mac is on hold.

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
   |  tool calls  ↓        ↑  images back
Our MCP server (Python)
   ├─ Typed tools: 151, including look tools
   ├─ Relay, auto-started: WebSocket on this computer
   │     └─ live → Aseprite (open), via bridge extension, one undo per edit
   ├─ Docs search: Lua API and user manual
   └─ or → aseprite --batch: files on disk, no window
```

The shape is the same as the original project. What changed is that the relay starts on its own, Aseprite connects through an installed extension, and pictures of the canvas come back to Claude instead of landing on disk.

## Roadmap

Each phase only starts once the one before passes its finish line. The Mac tests in phase 3 are the one exception: they're on hold by choice, so phase 4 can start without them.

| Phase | Work | Done when | Status |
| --- | --- | --- | --- |
| 1. Fork and run | Fork on GitHub; get live mode working on Umar's computer | A test edit lands live in the open sprite | Done |
| 2. Claude's eyes | `look` tool, animation strips, before/after views | Claude spots its own mistake from a picture | Done |
| 3. Easy setup | Auto-start relay, Aseprite extension, Windows and Mac tests | Install takes one step | Done on Windows; Mac on hold |
| 4. Smarter help | Docs search, `describe_sprite`, safety rails, then the cool extras | It beats the Blender connector for sprite work | Must-haves done; cool extras not started |
| 5. Godot export | One-action sprite sheet plus `SpriteFrames` `.tres`, with animations from tags | A sprite exported in one action plays its tagged animations in Godot | Built; needs checking in Godot |
| 6. Export to your game | One Export button plus `export_to_game`, for Godot, Unity or any folder | Art exported from Aseprite can be selected straight away in the engine | Built; needs checking in Godot and Unity |

## Limits, risks and open questions

**Limits to expect**

- Claude is strong at structured work (palettes, tweens, sheets, cleanup) and weaker at expressive freehand drawing. This is an assistant to the artist, not a replacement.
- Aseprite's Lua can only dial out, not listen, so a small relay will always sit between Claude and the editor. We can hide it, not remove it.
- Images sent to Claude use up conversation space, so `look` should send small, cropped pictures by default.

**Risks**

- The original author may change direction. Keep the fork close to theirs and offer improvements back upstream where they fit.
- Aseprite updates can change the Lua API. Pin a tested version and test on each new release.
- Live edits run real code in the editor. Keep the Pause toggle and undo-per-request, and never auto-save over the user's files.
- The relay refuses browsers, but any other program on the computer can still reach it. It has no password, because that password would sit in a file those same programs can read.
- One undo per request depends on Claude using `edit_batch`. Separate tool calls are still one undo each.

**Decisions and open questions**

- Live exports: Claude's code gets full trust. Umar grants it in Aseprite's permission prompt the first time an export runs; we never write it to Aseprite's settings ourselves.
- Renamed: the package, command and server are all `aseprite-claude-connector` now. It isn't on PyPI yet, so installs come from GitHub.
