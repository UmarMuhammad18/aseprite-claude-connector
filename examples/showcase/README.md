# Showcase set

Six `.aseprite` files built end-to-end by an AI agent driving a **live** Aseprite
editor through this MCP — deterministic primitives only, no human strokes. Open
them in Aseprite and press Ctrl-Z: every step of the build is one named undo.

| File | What it demonstrates |
|---|---|
| `01_refinery.aseprite` | `draw_iso_box` face polygons → `iso_recessed_panel`, iso cylinders, `generate_color_ramp` + `apply_shading` + `quantize_to_palette`, rivets scattered with `paint_with_stamp`, layer groups, `qa_sweep` 4/4 |
| `02_beacon.aseprite` | additive glow layer, `box_blur`, eased `tween_cel_opacity` down and back up for a breathing 6-frame loop, tags, `frame_diff` |
| `03_drone.aseprite` | hand-placed `draw_pixels` ship, `add_outline`, `tween_frames` (smoothstep), `smear_frame`, motion QA via `frame_diff` + `render_onion_composite` |
| `04_depot_floor.aseprite` | `create_tilemap_layer`, tiles drawn into the tileset, a 6×6 map placed with `set_tiles`, grid verified with `get_tilemap_info`, `export_tileset` |
| `05_showcase_sheet.aseprite` | the other four assembled with `import_image_as_layer`, pixel-font labels drawn through `run_lua`, 10 named slices with pivots, `export_unity_slices` |
| `06_dusk_castle.aseprite` | the README hero: a 480×270 dusk landscape, 16 layers, a 24-frame loop. `paint_sky` with drifting clouds, `paint_mountains`, `reflect_in_water`, `add_mist`, `add_fire`, and `add_glow` make the setting; the castle, knight, pines, and tent were drawn through `run_lua`. Checked with `look` and `check_loop`, exported with `export_animation` |

`unity/` holds the one-action Unity export from the sheet: the atlas PNG plus a
`.meta` with all ten sprites pre-sliced and pivot-baked (32 pixels-per-unit).
Drop both into a Unity project's `Assets/` and the texture imports already
sliced, pivots included.

Each file carries its own provenance in sprite metadata — read it with
`get_sprite_metadata`.
