# aseprite-live-mcp

[![PyPI](https://img.shields.io/pypi/v/aseprite-live-mcp)](https://pypi.org/project/aseprite-live-mcp/)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP%20spec-2025--11--25-8A2BE2)
![tools](https://img.shields.io/badge/tools-77-orange)
![capabilities](https://img.shields.io/badge/MCP-tools%20·%20resources%20·%20prompts-blue)

**Let an AI agent draw in your *live* Aseprite editor — one named undo per edit — with a Unity-first, game-dev toolset.**

An open-source [Model Context Protocol](https://modelcontextprotocol.io) server for
[Aseprite](https://www.aseprite.org/). It drives your **running editor** (all open
documents, unsaved state, each edit a single Ctrl-Z) *and* runs **headless**
(`aseprite --batch`) against files on disk — **77 typed tools** from one server,
including one-action **Unity sprite-sheet + `.meta` export** (named slices carry
per-slice pivots), a project-convention **art-QA sweep**, and **isometric drawing
primitives** we haven't found in another Aseprite MCP. It also exposes **MCP prompts**
— guided one-call art workflows we haven't seen another Aseprite MCP ship — and
**MCP resources** that read your live editor's open documents, active palette, and
last QA/export report (a live-state resource set unique to the live bridge).

## See it in action

Each of these is an AI agent driving a **live** 64×64 Aseprite canvas through the MCP — one named undo per step.

<table>
<tr>
<td align="center"><img src="docs/demo.gif" width="240" alt="Isometric machine build"><br><sub><b>Isometric primitives</b><br>iso box → recessed port → tank → outline</sub></td>
<td align="center"><img src="docs/demo-drawing.gif" width="240" alt="Drawing suite"><br><sub><b>Drawing suite</b><br>rect · dithered gradient · ellipse · circle · dither · outline</sub></td>
<td align="center"><img src="docs/demo-shading.gif" width="240" alt="Palette ramp-walk shading"><br><sub><b>Ramp-walk shading</b><br>flat fill → volumetric, along a hand-ordered palette</sub></td>
</tr>
</table>

## Install

**Recommended — one command (no clone):**
```bash
uvx aseprite-live-mcp        # or: pipx run aseprite-live-mcp
```

**From source:**
```bash
git clone https://github.com/oaktreegames/aseprite-live-mcp
cd aseprite-live-mcp
pip install -e .
```

Requires **Python 3.10+** and **Aseprite 1.3+**. That's it for headless; the live
editor needs one extra step (below).

## Quickstart — headless (2 minutes, no editor open)

Add the server to your MCP client (Claude Code, Claude Desktop, Cursor, …):

```jsonc
{
  "mcpServers": {
    "aseprite-live": {
      "command": "uvx",
      "args": ["aseprite-live-mcp"],
      "env": {
        "ASEPRITE_MCP_BACKEND": "headless",
        "ASEPRITE_PATH": "C:/Program Files/Aseprite/Aseprite.exe"
      }
    }
  }
}
```

Set `ASEPRITE_PATH` to your Aseprite executable (auto-detected on common installs
if you omit it). In headless mode, tools take a `file` argument — the `.aseprite`
to act on. Ask your agent to run `status` to confirm the connection.

## Quickstart — live editor (drive your open canvas)

The live backend edits your **running** Aseprite, one undo step per edit.

1. **Install the bridge script into Aseprite** — in Aseprite, `File → Scripts →
   Open Scripts Folder`, and copy [`aseprite_client/claude-bridge.lua`](aseprite_client/claude-bridge.lua)
   into it. Restart Aseprite (or `File → Scripts → Rescan Scripts Folder`).
2. **Start the relay:** `python bridge/relay_server.py` (needs `pip install websockets`).
3. **Connect:** in Aseprite, `File → Scripts → claude-bridge`, and grant the script
   trust when asked. The panel shows **"connected to Claude"**, live activity, and a
   Pause toggle.
4. **Switch the backend** to `live` in your MCP config (`"ASEPRITE_MCP_BACKEND": "live"`).

Now tools act on your active document; watch edits appear and press Ctrl-Z to undo
each one. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how it works.

## What you can ask it to do

- *"Make a 32×32 sprite, draw a red circle, and export it as icon.png."*
- *"Measure the transparent padding on player.aseprite and tell me if it's centered."*
- *"Export machines.aseprite as a Unity sprite sheet at 16 pixels-per-unit."* → drops a sheet + a pre-sliced `.meta` straight into your Unity project.
- *"Draw an isometric box for a 1×1 machine base and put a recessed port on its front face."*
- *"Run a QA sweep on this sprite: it must be 64×64, ≤ 16 colors, and grid-aligned."*
- *"Pull a 16-color palette out of concept.png and snap my sprite to it."*
- *"Slice this atlas, set each slice's pivot, and export it to Unity with the pivots baked in."*

Sanity check the whole surface: `python tests/smoke_headless.py` drives all 77
tools (plus resources + prompts) in-process against a throwaway sprite, and
`pytest` runs the unit suite plus wire-path tests that validate structured
output through a real MCP client session (`pip install -e ".[dev]"` first).

## Where this sits (honest positioning)

There are already good Aseprite MCP servers. This project is **not the first**, and
doesn't claim to be. What it claims — and can defend:

| Capability | Landscape | This project |
|---|---|---|
| Draw / layer / frame / palette / export, plus dithering, gradients, outline, color replace, quantize, ramps, palette-from-image | Well covered by the headless leaders (diivi ~104 tools, pixel-mcp, ext-sakamoro) | **Parity** — a clean, typed, curated surface |
| Palette-constrained shading, cel tweening | Shipped elsewhere (pixel-mcp `apply_shading`, diivi tweens) | Parity |
| Godot `.tres` SpriteFrames export | Shipped (commercial Aseprite MCP Pro) | Out of scope — already solved |
| **Unity `.meta` sprite export in one action — frames (uniform pivot / alignment preset) *or* named slices (each with its own baked pivot)** | **Unoccupied** — every Aseprite→Unity path is a separate engine-side importer, and none export pivots | **Differentiator** ✅ |
| **Art-QA sweep incl. transparent sticker-padding measurement** | No MCP ships it as a sweep; padding measurement we found in no MCP or lint tool we surveyed | **Differentiator** ✅ |
| **Isometric drawing primitives** (2:1 iso boxes/cylinders, auto face-shading, recessed ports) | No Aseprite MCP we surveyed has them — all flat-canvas | **Differentiator** ✅ |
| **MCP resources for live editor state** (open/unsaved docs, active palette, last QA + export report) | Only one nascent server exposes any resources, and it's headless — nothing live to read | **Differentiator** ✅ |
| **MCP prompts — guided one-call art workflows** (`unity_qa_gate`, `iso_building_to_spec`, …) | No Aseprite MCP we found exposes formal protocol prompts (some ship a guide string or an external doc) | **Differentiator** ✅ |
| Live editor with **one named `app.transaction` undo per edit** | Live-GUI exists (Pro commercial; Dizzd/Shexiaoyun OSS, nascent); per-edit transaction discipline isn't a stated guarantee | Defensible in **combination** (undo + live resources + QA on the live doc) |

We don't compete on raw tool count (the leaders ship 100+). The pitch is **curated,
Unity-first, and QA-gated**, with an **MCP-native integration layer** — guided-workflow
prompts (which we haven't seen another Aseprite MCP ship) and live-state resources
(unique to the live bridge).

## Tools (77)

- **Inspect** — `status`, `get_sprite_info`, `get_pixel`, `get_pixels` (composited read-back for the AI feedback loop), `get_color_stats` (histogram)
- **Canvas / layers / frames / cels** — `create_sprite`; `add_layer`/`delete_layer`/`rename_layer`/`set_layer_visibility`/`set_layer_opacity`/`set_layer_blend_mode`/`duplicate_layer`/`merge_layer_down`/`move_layer`/`import_image_as_layer`/`flatten_sprite`; `add_frame`/`duplicate_frame`/`delete_frame`/`set_frame_duration`; `clear_cel`/`set_cel_position`/`set_cel_opacity`
- **Tags** — `create_tag`, `list_tags`, `delete_tag`
- **Draw** — `draw_rectangle`, `draw_line`, `draw_circle`, `draw_ellipse`, `draw_gradient` (optional dither), `apply_dither` (ordered Bayer), `add_outline`, `fill_area`
- **Palette / color** — `get_palette`, `set_palette_color`, `add_palette_color`, `set_palette`, `apply_preset_palette` (gameboy/pico8/cga), `generate_color_ramp` (hue-shifted), `extract_palette_from_image` (median-cut); `replace_color`, `quantize_to_palette`, `adjust_hsl`
- **Shading** — `apply_shading`, `palette_ramp_walk` (index-adjacency ramp shading)
- **Selection / transform** — `select_rectangle`/`select_all`/`deselect`; `flip_sprite`/`rotate_sprite`/`resize_sprite`/`crop_sprite`
- **Slices** — `create_slice`, `set_slice_pivot`, `set_slice_center` (9-patch), `list_slices`, `delete_slice`
- **Animation** — `tween_frames`, `smear_frame`
- **Isometric** — `draw_iso_box`, `draw_iso_cylinder`, `fill_polygon`, `iso_recessed_panel` (2:1 iso primitives with automatic top/left/right face shading)
- **Export** — `export_sprite` (honest multi-frame split reporting), `export_spritesheet` (+ JSON atlas), `export_unity_sprite` (frames), `export_unity_slices` (named slices, per-slice pivots)
- **Batch** (whole folder, headless, non-destructive) — `batch_export`, `batch_resize`, `batch_apply_palette`
- **Editor** — `undo`, `redo` · **Advanced** — `run_lua` (guarded escape hatch)
- **Art-QA** — `measure_padding`, `qa_sweep`

Every tool is typed with accurate MCP annotations (`readOnlyHint` / `destructiveHint`
/ `idempotentHint` / `openWorldHint`); mutating tools are wrapped in a **named**
`app.transaction`, so each edit is exactly one undo step (the editor shows
"Undo <label>"). The QA and Unity-export tools also declare an `outputSchema` and
return `structuredContent`. Built on the official MCP Python SDK's `FastMCP`, stdio
transport, targeting the stable **2025-11-25** spec.

## Resources

Read live editor state without spending a tool call — enabled by the live bridge:

- `aseprite://sprite/active` — size, color mode, layer/frame/tag names of the active document
- `aseprite://palette/active` — the active palette as hex
- `aseprite://docs` — every open document, including unsaved/untitled tabs
- `aseprite://qa/last` — the most recent `qa_sweep` / `measure_padding` result
- `aseprite://export/last` — the most recent Unity export (files written + sprite manifest)

## Prompts (guided workflows)

One-call "skills" that chain the tools into finished art tasks:

- `unity_qa_gate` — run the ship-ready QA gate, then export a Unity sheet + `.meta`
- `iso_building_to_spec` — build a 2:1 isometric building from a footprint spec
- `shade_along_ramp` — shade a sprite by walking its hand-ordered palette ramp
- `autoslice_to_unity` — multi-frame sprite → Unity-import-ready sheet + pre-sliced `.meta`
- `concept_to_placeholder` — external concept image → correctly-padded, in-palette placeholder

## Security

The relay executes Lua inside Aseprite — treat it as local code execution. It binds
to `127.0.0.1` only, and every edit is one undo step. Full threat model:
[`SECURITY.md`](SECURITY.md).

## Contributing

Issues and PRs welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). Run `pytest` and
`python tests/smoke_headless.py` before submitting.

## License

MIT — see [`LICENSE`](LICENSE). © 2026 Kyle Ocheltree / OakTree Games.

<!-- mcp-name: io.github.oaktreegames/aseprite-live-mcp -->
<!-- The line above is the MCP Registry PyPI ownership marker (ships in the PyPI
     description). It must match the "name" in server.json. Do not remove. -->
