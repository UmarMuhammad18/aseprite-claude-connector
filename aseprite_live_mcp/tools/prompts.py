"""MCP prompts — guided art workflows ("skills").

A prompt turns a 5-10 tool chain into one discoverable, argument-typed call, so a
client gets a short menu of finished art tasks instead of dozens of raw verbs.
Across the Aseprite-MCP field, formal MCP prompts are unoccupied — the others ship,
at most, a guide string or an external doc. Each prompt returns instructions for
the agent; it names the exact tools to call and where to stop and ask the human.

Prompt arguments are strings (the MCP prompt contract); formats are noted inline.
"""

from __future__ import annotations


def register(mcp):
    @mcp.prompt(
        title="Unity QA gate",
        description="Run the ship-ready QA gate on the active sprite and export a Unity sheet + .meta.",
    )
    def unity_qa_gate(
        expected_size: str = "64x64", grid: str = "16", max_colors: str = "16"
    ) -> str:
        return (
            "Run the Unity-ready QA gate on the active Aseprite sprite. Do this in order:\n"
            f"1. Call `qa_sweep` with expected_width/expected_height parsed from '{expected_size}', "
            f"grid_multiple={grid}, max_colors={max_colors}, require_symmetric_padding=true.\n"
            "2. Call `measure_padding` and report the per-side padding.\n"
            "3. If any check fails — off-grid size or asymmetric padding — DESCRIBE the exact fix "
            "(`crop_sprite`/`resize_sprite` to center the content and hit the grid) and ASK the user to "
            "confirm before mutating. Do not silently crop.\n"
            "4. Once every check passes, call `export_unity_sprite` (or `export_unity_slices` if the "
            "sprite uses named slices) to write the sheet and the pre-sliced `.meta`.\n"
            "Report the result as a checklist: each check, pass/fail, and the files written."
        )

    @mcp.prompt(
        title="Isometric building to spec",
        description="Build a game-ready 2:1 isometric building sprite from a footprint spec.",
    )
    def iso_building_to_spec(
        footprint: str = "1x1",
        height: str = "24",
        base_color: str = "#8a94a0",
        ports: str = "front",
    ) -> str:
        return (
            f"Build a 2:1 isometric building for a {footprint}-tile footprint, ~{height}px tall, base "
            f"color {base_color}, with docking ports on: {ports}.\n"
            "Steps:\n"
            "1. `create_sprite` sized so the iso footprint diamond spans the full tile width "
            "(1x1 short -> 64x64; 1x1 tall or 2x2 -> 128x128; scale up for bigger footprints).\n"
            "2. `draw_iso_box` (and `draw_iso_cylinder` for tanks/silos) centered on the tile, using "
            "base_color — it auto-shades top/left/right faces. Keep the returned face polygons.\n"
            "3. For each requested port, call `iso_recessed_panel` with the matching returned face "
            "(e.g. face_se) so the socket style stays consistent.\n"
            "4. Optionally `generate_color_ramp` from base_color then `palette_ramp_walk` to deepen the "
            "shading along the hand-ordered ramp.\n"
            "5. `measure_padding` to confirm the art is centered, then stop and show the user "
            "`get_pixels` of the result for approval. Do not export until they approve."
        )

    @mcp.prompt(
        title="Shade along ramp",
        description="Shade the active sprite by walking its hand-ordered palette ramp (not luminance-nearest).",
    )
    def shade_along_ramp(light_direction: str = "top_left", steps: str = "2") -> str:
        return (
            "Shade the active sprite so it respects the hand-ordered palette ramp:\n"
            "1. `get_palette` and confirm it is an ordered dark->light ramp; if it is not, offer to "
            "`generate_color_ramp` from the sprite's dominant color first.\n"
            f"2. `palette_ramp_walk` over the content region with light_direction={light_direction}, "
            f"steps={steps}. This walks the palette by index rather than snapping to the nearest color, "
            "so authored ramps stay intact.\n"
            "3. `get_pixels` on a corner-to-corner sample and confirm the lit side moved toward the "
            "lighter indices and the shadow side toward the darker ones. Report before/after."
        )

    @mcp.prompt(
        title="Auto-slice to Unity",
        description="Turn a multi-frame sprite into a Unity-import-ready sheet + pre-sliced .meta.",
    )
    def autoslice_to_unity(png_path: str = "sprite.png", pixels_per_unit: str = "16") -> str:
        return (
            "Take the active multi-frame sprite to a Unity-import-ready asset in one pass:\n"
            "1. `get_sprite_info` to confirm the frame count and size.\n"
            f"2. `export_unity_sprite` with png_path='{png_path}', pixels_per_unit={pixels_per_unit}. "
            "This writes a horizontal sheet AND a `.meta` pre-sliced into named Multiple-mode sprites "
            "(one per frame) — no manual Sprite Editor pass in Unity.\n"
            "3. Read back the `aseprite://export/last` resource and report the sprite rects and the .meta "
            "path so the user can drop it straight into their Unity project."
        )

    @mcp.prompt(
        title="Concept art to placeholder",
        description="Turn an external concept image into a correctly-padded, in-palette placeholder sprite.",
    )
    def concept_to_placeholder(
        image_path: str = "concept.png", target_size: str = "64x64", max_colors: str = "16"
    ) -> str:
        return (
            f"Turn the concept image '{image_path}' into a clean placeholder sprite:\n"
            f"1. `create_sprite` at {target_size} (RGB).\n"
            "2. `import_image_as_layer` to drop the concept in as a reference/trace layer; if it is "
            "larger than the canvas, note that the user should scale it down.\n"
            f"3. `extract_palette_from_image` from '{image_path}' with max_colors={max_colors}, replace=true, "
            "to lock a tight palette from the concept.\n"
            "4. `quantize_to_palette` so the sprite conforms to the locked palette, then "
            "`measure_padding` to confirm it is centered.\n"
            "5. Stop and present the result for the human to hand-finish. This is a TEMP placeholder — "
            "do not treat it as final art, and do not export it as shipped art without explicit approval."
        )
