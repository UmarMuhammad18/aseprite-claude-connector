# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/): while we're pre-1.0, minor bumps
(0.x) may change tool behavior; patch bumps are fixes only.

**How you'll know it's time to update:** the `status` tool reports your installed
version and whether a newer release exists (checked against PyPI at most once a
day; set `ASEPRITE_MCP_NO_UPDATE_CHECK=1` to disable). To upgrade:
`pip install -U aseprite-claude-connector`.

## [Unreleased]

### Added — skies, water, and light

- `paint_sky`: a dawn, day, sunset, or night sky in dithered bands, with a sun the sky
  glows round, clouds lit from its side, and stars. With `drift` the clouds travel
  across the sky as a seamless loop, on their own layer.
- `paint_mountains`: up to three ranges on the horizon, paler and hazier with distance,
  lit from the sun's side, with snow caps and a treeline.
- `reflect_in_water`: everything above a horizon mirrored into water that ripples more
  the nearer it comes, as a seamless loop over the sprite's frames, with a path of light
  under the sun.
- `add_glow`: a pool of fire or lantern light on a layer that adds to what is under it.
  It can flicker, and can light chosen layers fully while the open air stays dark.
- `add_rim_light`: the edge of a layer that faces a light, on its own layer above it.
- `add_fire`: a looping fire with embers that lean with the wind, with or without logs,
  in fire, blue, or green.
- `add_mist`: a band of mist that drifts as a seamless loop and warms toward the sun.

### Fixed

- `export_animation` and session recordings no longer tint art that has more than 256
  colours. The GIF palette is now fitted to the picture, where it used to fall back to
  a fixed colour cube that turned smooth shading green and purple.

## [0.4.0] — 2026-11-11

### Fixed

- `set_palette` and `apply_preset_palette` work again. The `load_palette` change
  below had replaced the Lua they share, so in 0.3.0 both failed. The Mac workflow,
  the only CI run against real Aseprite, now runs on any change to the package, so a
  tool can't break unseen again.
- `load_palette` no longer raises Aseprite's security prompt in the live editor. A
  batch Aseprite reads the file and only its colours reach the editor.
- In the live editor, clicking another tab no longer redirects Claude's edits. The
  sprite Claude creates, opens, or picks stays its target until it picks another
  (`pin_sprite`); if that sprite is closed, tools say so instead of editing
  whichever sprite is active.

### Added — characters

- `split_sheet` cuts a character sheet into one sprite per pose, at one scale and
  on one shared palette, with the background and bits of neighbouring poses
  cleared.
- `draw_eyes` redraws eyes frame by frame: where they look, blinks, lids, brows
  (angry to worried), smiles. It returns the eye colours it used, to pass back on
  every pose so a character's eyes match.
- `swing_part` swings a wing, arm, or tail about its joint without opening a gap.
- `bob_body` makes breathing, hops, and sways with the feet planted.
- `lift_symbols` moves "!", "?", Zzz, or hearts onto their own layer and animates
  them there.
- These keyed tools make the frames they need, so a whole animation is one call,
  and they stack on the same frames.
- `check_consistency` finds colours that drift between sprites of one set (as
  poses pixelated separately do) and differences in subject size, and
  `match_palettes` merges the drift onto one palette.
- `pixelate_reference` can clear a white or flat background (`remove_background`)
  and drop bits of neighbouring art a crop catches (`clear_edges`).
- An `animate_character` prompt walks through all of it, and asks you to pick an
  expression from options when the mood matters.

### Added — working live

- `pin_sprite` picks the sprite Claude works on, by filename, by tag, or "the one
  I have open", and `list_sprites` shows which one is pinned, and each sprite's tags.
- `save_all_sprites` saves open work into a folder: unsaved sprites become files
  there, and sprites that already have a file are copied, never overwritten.
- `aseprite-claude-connector setup --desktop` also registers the server with the
  Claude desktop app, so you can use it from a normal Claude chat.

### Added — checks

- A `Release check` workflow installs each published version from PyPI on Windows,
  Linux, and Mac, without the repo, and checks that it runs.
- A `Unity` workflow and test project (`unity/`) have real Unity import a sliced
  sheet and an autotile set and paint with its Rule Tile. It skips itself until the
  repository has a Unity licence in its secrets.
- `docs/MAC_TESTING.md`: how to test the live connection on a Mac for free, by building
  Aseprite from source, without Claude.

## [0.3.0] — 2026-11-06

### Added — references, scenes, and game assets

- `pixelate_reference` turns a reference picture into a pixel-art layer. It shrinks
  the picture by area averaging, picks a palette that keeps small accents like a
  scatter of flowers, can snap to your own palette or dither, and clears lone noise
  pixels.
- `compare_to_reference` shows the reference, the canvas, and a difference heatmap
  side by side, with scores and the areas that differ most.
- The server's instructions tell Claude to start from `pixelate_reference` when asked
  to recreate a picture, instead of drawing it from memory.
- `ambient_motion` brings a still scene to life as a seamless loop: wind rolling
  through it, water shimmer, a light glint, and a layer of motes, snow, rain, or
  embers. It adds and tags the frames itself.
- `split_into_layers` separates a picture into named parts from a few seed points,
  at the parts' real edges, so each can be edited or animated alone.
- `extend_scene` grows the canvas and fills the new space by continuing the picture's
  own texture, like turning a portrait into a wide banner.
- `clean_pixel_art` merges noise specks and firms up edges with the art's own colours.
- Three new prompts: `recreate_picture`, `make_banner`, and `animate_scene`.

- `animate_parts` animates a character from its part layers: key poses per part,
  frames in between filled in, a pivot for each part, and parents so a forearm follows
  its arm. Parts turn with RotSprite-style rotation, so edges stay crisp.
- `make_seamless` makes a texture repeat with no visible edge.
- `make_autotiles` builds the 47-tile edge-and-corner set for one terrain over another,
  with a Godot TileSet whose terrain paints it, or a sliced Unity sheet and Rule Tile.
- `make_normal_map` makes a normal map for Godot's and Unity's 2D lights, as a hidden
  layer and optionally a PNG strip.
- `relight_scene` makes dawn, noon, sunset, or night versions of a scene on new layers,
  with warm pools around lanterns.
- `clean_lines` thins sketched strokes to one pixel and removes doubled corners.
- `export_animation` writes a GIF or animated PNG at a whole-number scale, with each
  frame's own duration, from Python, so the live editor shows no security prompt.
- The `Mac` workflow's Godot check now has Godot paint with a `make_autotiles` TileSet
  and checks the tile it picks for every cell.

### Changed — the pixel cap, and installing from PyPI

- This is the first release on PyPI under this name: install with
  `pip install aseprite-claude-connector`. The update check now finds new releases.

- The pixel cap no longer counts cels on layers or frames an edit made itself, since
  they can't overwrite anything. Importing a long sprite sheet onto a new layer no
  longer needs the cap raised.

### Fixed

- `add_reference_image`, `import_image_as_layer`, `import_spritesheet`,
  `paint_with_stamp`, and `extract_palette_from_image` no longer stall on Aseprite's
  security prompt in the live editor. A batch Aseprite reads the picture instead.
- `pack_atlas` reads closed files in the live editor, as it always said it did.

### Added — the cool extras

- **`inbetween`** fills the frames between two key poses and shows the result, with no
  new colors. **`walk_cycle_template`** lays down a timed, tagged walk or run skeleton.
  **`apply_timing`** applies ease, hold, or bounce presets. **`check_loop`** flags a jump
  at an animation's seam.
- **`find_stray_pixels`** shows likely accidents in a picture. **`recolor_variants`**
  writes team or season recolors in one batch. **`add_outline`** gains `selective`,
  `layer`, and `all_frames`, and no longer crops art that sits past the canvas.
- **`add_reference_image`** makes a faded, locked guide layer. **`edit_in_selection`**
  keeps edits inside the artist's selection. **`change_summary`** lists what changed
  frame by frame. **`start_recording`** and **`stop_recording`** make a GIF timelapse.
  **`explain_changes`** gives the Aseprite tool or shortcut behind recent edits.
- **`export_gamemaker`** writes `_stripN` sprite strips. **`pack_atlas`** packs several
  sprites into one texture with JSON data.
- A `Mac` workflow compiles Aseprite on a Mac and runs setup and every tool against it.
  `setup` now finds `~/Applications`, and tells Mac users to quit with Cmd+Q.

### Changed — renamed to aseprite-claude-connector

- The package, command, import name, and server name are now
  `aseprite-claude-connector` (`aseprite_claude_connector` in Python). Earlier
  entries below this one keep the names they shipped with. Install from GitHub;
  this name isn't on PyPI yet.

### Added — export to your game

- **File → Export → Export to Game...** in Aseprite, and the **`export_to_game`** tool.
  Either one finds the engine from the folder, uses the project's sprites folder, and
  writes what that engine needs. The button works without Claude running.

### Fixed — repeat exports and known issues

- Exporting to Unity again keeps the `guid` in the `.meta`, so prefabs and scenes stay
  linked to the sprite. Each export used to make a new one and break those links.
- `tween_frames` works on art redrawn in a new place, and refuses when the art hasn't
  moved instead of reporting success on a still animation.
- `move_layer` no longer trips the pixel cap, because a reorder changes no pixels.
- `run_lua` takes `edit=true` for one undo step under the pixel cap and dry run.
- Calls right after a relay handover wait for the extension instead of failing.
- `setup` moves a local Claude Code registration to user scope, so the tools appear
  however VS Code spells the folder path.

### Added — Godot export and targeting

- **`export_godot`** writes a sprite sheet and a Godot 4 `SpriteFrames` `.tres`, with
  one animation per tag, keeping frame timing, tag direction, and repeat counts.
- **`select_frame`** and **`select_layer`** choose where edits land, and work as
  `edit_batch` steps, which is how to target a frame or layer in headless mode.
- **`bands`** on `draw_gradient` steps through solid colors and dithers only the seams.
- **`preview`** now also covers the isometric tools, `fill_polygon`, and
  `paint_with_stamp`.

### Fixed

- `set_color_mode` to `indexed` no longer blanks a sprite with a one-entry palette.
- The relay reads a refused request before answering, so Windows callers get the 403
  instead of a connection reset.
- The relay stalled on startup on Macs, doing a reverse DNS lookup it never used.

### Added — smarter help

- **`describe_sprite`** summarizes the sprite in one call: layer tree, frame timing,
  tags, slices, palette, selection, and what's active.
- **`search_api_docs`** searches the Lua API reference, bundled with its MIT licence.
- **`search_manual`** searches the user manual, downloaded to your cache on first use.
- **`edit_batch`** runs several editing tools as one undo step.
- **`set_safety_rails`** sets a dry-run mode and the cap on pixels one call can change.
  The cap is on by default at 250,000 pixels; `ASEPRITE_MCP_MAX_PIXELS` changes it, and
  0 removes it. An edit that hits a rail rolls back and leaves nothing on the undo stack.

### Added — canvas vision

- **`look`** returns a frame as an image in the conversation, scaled up with sharp
  pixels: all layers or one, a crop, or the selection.
- **`look_animation`** returns a tag or frame range as one strip or grid image.
- **`look_onion`** returns the onion-skin view as an image.
- **`preview`** on the 10 drawing tools in `draw.py` adds a before/after picture plus
  the changed-pixel count and bbox. The edit is still one undo step.

### Added — one-step setup

- **`aseprite-claude-connector setup`** registers the server with Claude Code and installs the
  bridge. `--out` writes a `.aseprite-extension` file instead.
- **The Claude Bridge extension** replaces the script you had to run by hand. It
  connects when Aseprite starts and keeps retrying. **File → Scripts → Claude Bridge**
  opens the status panel, and Pause is remembered between runs.
- **The server starts the relay itself**, and takes over if another session's relay
  stops. `ASEPRITE_MCP_NO_RELAY=1` turns this off.

### Security

- The relay refuses browsers: HTTP requests with an `Origin` or a foreign `Host`, and
  WebSocket clients with a web `Origin`.

### Changed

- The relay moved to `aseprite_claude_connector/relay.py` (run it with
  `python -m aseprite_claude_connector.relay`) and the bridge to `aseprite_claude_connector/extension/`.
  Remove any old `claude-bridge.lua` from Aseprite's scripts folder.
- `websockets` is now a core dependency; the `relay` extra is gone.
- The relay accepts WebSocket messages up to 64 MiB, for pixel data.
- The `mcp` dependency now requires `>=1.19.0,<2`.

## [0.2.0] — 2026-07-16

The tool surface closes the gaps we found surveying the other Aseprite MCP
servers, the live editor becomes a two-way surface, and the server learns to
tell you when it's out of date.

### Added — update awareness
- `status` now reports the server version and (checked against PyPI at most
  daily, opt-out `ASEPRITE_MCP_NO_UPDATE_CHECK=1`) whether a newer release
  exists; also surfaced as the `aseprite://update` resource and one stderr line.
- MCP `serverInfo` now reports the real package version (was the SDK's).

### Added — live-editor interaction (needs the running editor)
- `show_choice_dialog` / `get_dialog_choice` — pop an approve/redo dialog inside
  Aseprite, non-blocking.
- `ask_point` / `get_asked_point` / `cancel_ask_point` — ask the artist to click
  a canvas point (pivot, anchor), human-in-the-loop.
- `watch_changes` / `get_watched_changes` / `stop_watching_changes` — count the
  artist's own edits via `Sprite.events`, e.g. re-QA after they stop.
- `get_editor_state` / `set_editor_view` — read/drive zoom, scroll, mouse pixel.
- `set_symmetry` — mirror-painting control (mode + axis placement).

### Added — tilemaps
- `create_tilemap_layer`, `add_tile`, `draw_on_tile`, `set_tiles`,
  `get_tilemap_info`, `export_tileset` — full tileset/tilemap editing, live and
  headless.

### Added — parity and beyond
- Layer groups: `add_group`, `move_layer_to_group`, `list_layers` (full tree);
  every layer-name argument now finds nested layers, including `Group/Layer`
  paths.
- Filters: `adjust_brightness_contrast`, `invert_colors`, `desaturate`,
  `box_blur` (alpha-weighted), `sharpen` (edge-safe unsharp).
- Selection: `select_ellipse`, `select_by_color`, `invert_selection`,
  `get_selection`, `erase_area` (rect or current selection).
- Animation QA: `frame_diff` (pixel-exact diff + change bbox),
  `render_onion_composite` (red/blue ghosted PNG of the motion arc).
- `paint_with_stamp` — stamp an image (file or sprite region) along a path of
  points, one undo step.
- Typed sprite metadata: `set_sprite_metadata` / `get_sprite_metadata`
  (Aseprite's Properties system — provenance that saves with the file).

### Changed
- README tool reference is now generated from the code
  (`python scripts/gen_docs.py`); CI fails if it drifts. The tools badge is
  written by the same script.
- CI: lint (ruff check + format) and a 3-OS × 2-Python test matrix.
- Repo practices: issue templates, dependabot, GitHub Releases cut from
  CHANGELOG on tag push.

## [0.1.2] — 2026-07-16

### Fixed
- **Structured output failed MCP output-schema validation on real client calls**
  for `get_sprite_info` (both backends) and the Unity exports (files were written,
  then the call reported an error). In-process tests couldn't see it; a new
  wire-validation test lane (real MCP client session) now guards every tool that
  declares an `outputSchema`.
- Hard crash at server startup on Python 3.10/3.11 (pydantic rejects
  `typing.TypedDict` there; now `typing_extensions.TypedDict`). CI now tests on
  the declared 3.10 floor before every release.
- Honest dependency floors: `mcp>=1.10.0`, `typing-extensions>=4.9.0`.

## [0.1.1] — 2026-07-14

### Added
- Project URLs (Homepage / Repository / Issues) in the package metadata.

## [0.1.0] — 2026-07-13

### Added
- Initial public release: 77 typed tools (canvas, layers, frames, cels, tags,
  draw, palette, color, shading, selection, transform, slices, animation,
  isometric primitives, export, batch, art-QA, editor), 5 MCP resources,
  5 MCP prompts.
- Hybrid backends: the same tools drive the **live** Aseprite editor (one named
  undo per edit) or run **headless** via `aseprite --batch`.
- One-action Unity export: sprite sheet + pre-sliced `.meta` (frames with
  alignment presets, or named slices with per-slice pivots baked in).
- Art-QA sweep: size/grid/palette checks plus transparent sticker-padding
  measurement.

[Unreleased]: https://github.com/UmarMuhammad18/aseprite-claude-connector/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/UmarMuhammad18/aseprite-claude-connector/releases/tag/v0.4.0
[0.3.0]: https://github.com/UmarMuhammad18/aseprite-claude-connector/releases/tag/v0.3.0
[0.2.0]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.2.0
[0.1.2]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.1.2
[0.1.1]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.1.0
