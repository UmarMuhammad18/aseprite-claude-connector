"""End-to-end smoke test of the headless backend and the MCP dispatch layer.

Runs real tool calls through the FastMCP server against a throwaway .aseprite,
collecting pass/fail per step, then checks the exported PNG is non-empty.

    ASEPRITE_MCP_BACKEND=headless python tests/smoke_headless.py

Requires Aseprite installed (auto-detected, or set ASEPRITE_PATH).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile

os.environ.setdefault("ASEPRITE_MCP_BACKEND", "headless")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aseprite_claude_connector  # noqa: E402
from aseprite_claude_connector.config import load_config  # noqa: E402
from aseprite_claude_connector.server import build_server  # noqa: E402


def _text(res) -> str:
    # call_tool returns a list of content parts (and maybe a structured dict); we
    # just want a printable string.
    if isinstance(res, tuple):
        res = res[0]
    try:
        return " ".join(getattr(p, "text", str(p)) for p in res)
    except TypeError:
        return str(res)


async def main() -> int:
    mcp = build_server()

    tools = sorted(t.name for t in await mcp.list_tools())
    print(f"registered tools ({len(tools)}):", tools)
    required = {
        "status",
        "get_sprite_info",
        "create_sprite",
        "draw_rectangle",
        "export_sprite",
        "add_layer",
        "delete_layer",
        "rename_layer",
        "set_layer_visibility",
        "set_layer_opacity",
        "flatten_sprite",
        "add_frame",
        "duplicate_frame",
        "delete_frame",
        "set_frame_duration",
        "export_spritesheet",
        "draw_line",
        "draw_circle",
        "fill_area",
        "get_palette",
        "set_palette_color",
        "add_palette_color",
        "set_palette",
        "apply_preset_palette",
        "get_pixel",
        "get_pixels",
        "select_rectangle",
        "select_all",
        "deselect",
        "run_lua",
        "flip_sprite",
        "resize_sprite",
        "crop_sprite",
        "undo",
        "redo",
        "measure_padding",
        "qa_sweep",
        "export_unity_sprite",
        "create_tag",
        "delete_tag",
        "list_tags",
        "clear_cel",
        "set_cel_position",
        "set_cel_opacity",
        "apply_shading",
        "palette_ramp_walk",
        "tween_frames",
        "smear_frame",
        "draw_iso_box",
        "draw_iso_cylinder",
        "fill_polygon",
        "iso_recessed_panel",
        "rotate_sprite",
        "draw_ellipse",
        "draw_gradient",
        "apply_dither",
        "add_outline",
        "generate_color_ramp",
        "extract_palette_from_image",
        "replace_color",
        "quantize_to_palette",
        "adjust_hsl",
        "get_color_stats",
        "set_layer_blend_mode",
        "duplicate_layer",
        "merge_layer_down",
        "move_layer",
        "import_image_as_layer",
        "create_slice",
        "set_slice_pivot",
        "set_slice_center",
        "list_slices",
        "delete_slice",
        "export_unity_slices",
        "batch_export",
        "batch_resize",
        "batch_apply_palette",
    }
    missing = required - set(tools)
    assert not missing, f"missing tools: {missing}"

    # MCP-native integration layer: prompts + resources (unique to this server).
    prompt_names = sorted(p.name for p in await mcp.list_prompts())
    resource_uris = sorted(str(r.uri) for r in await mcp.list_resources())
    print(f"registered prompts ({len(prompt_names)}):", prompt_names)
    print(f"registered resources ({len(resource_uris)}):", resource_uris)
    assert len(prompt_names) == 7, f"expected 7 prompts, got {prompt_names}"
    assert len(resource_uris) == 6, f"expected 6 resources, got {resource_uris}"

    d = tempfile.mkdtemp(prefix="aselm_smoke_")
    ase = os.path.join(d, "smoke.aseprite")
    png = os.path.join(d, "smoke.png")

    failures = []

    async def step(name, args):
        try:
            res = await mcp.call_tool(name, args)
            print(f"  OK  {name}: {_text(res)[:160]}")
            return res
        except Exception as e:
            print(f"  ERR {name}: {e}")
            failures.append((name, str(e)))
            return None

    await step("status", {})
    await step("create_sprite", {"width": 32, "height": 32, "color_mode": "rgb", "file": ase})
    if not os.path.isfile(ase):
        failures.append(("create_sprite", f"did not write {ase}"))
    await step(
        "draw_rectangle",
        {"x": 8, "y": 8, "width": 16, "height": 16, "color": "#ff0000", "file": ase},
    )
    await step("draw_line", {"x1": 0, "y1": 0, "x2": 31, "y2": 31, "color": "#00ff00", "file": ase})
    await step(
        "draw_circle",
        {
            "center_x": 16,
            "center_y": 16,
            "radius": 6,
            "color": "#0000ff",
            "fill": True,
            "file": ase,
        },
    )
    await step("fill_area", {"x": 0, "y": 31, "color": "#222222", "file": ase})
    await step("get_palette", {"file": ase})
    await step("set_palette_color", {"index": 0, "color": "#123456", "file": ase})
    await step("add_palette_color", {"color": "#abcdef", "file": ase})
    await step("set_palette", {"colors": ["#000000", "#ffffff", "#ff0000", "#00ff00"], "file": ase})
    await step("apply_preset_palette", {"name": "pico8", "file": ase})
    await step("get_pixel", {"x": 16, "y": 16, "file": ase})
    await step("get_pixels", {"x": 8, "y": 8, "width": 4, "height": 4, "file": ase})
    await step("select_rectangle", {"x": 4, "y": 4, "width": 8, "height": 8, "file": ase})
    await step("select_all", {"file": ase})
    await step("deselect", {"file": ase})
    await step(
        "run_lua",
        {
            "code": "return J({ w = app.activeSprite.width, layers = #app.activeSprite.layers })",
            "file": ase,
        },
    )
    await step("add_layer", {"name": "fx", "file": ase})
    await step("set_layer_opacity", {"name": "fx", "opacity": 128, "file": ase})
    await step("set_layer_visibility", {"name": "fx", "visible": False, "file": ase})
    await step("rename_layer", {"old_name": "fx", "new_name": "effects", "file": ase})
    await step("add_frame", {"file": ase})
    await step("duplicate_frame", {"number": 1, "file": ase})
    await step("set_frame_duration", {"number": 1, "ms": 120, "file": ase})
    await step("get_sprite_info", {"file": ase})
    await step("delete_frame", {"number": 3, "file": ase})
    await step("delete_layer", {"name": "effects", "file": ase})
    await step("flatten_sprite", {"file": ase})
    await step("flip_sprite", {"direction": "horizontal", "file": ase})
    await step("resize_sprite", {"width": 16, "height": 16, "file": ase})
    await step("crop_sprite", {"x": 0, "y": 0, "width": 12, "height": 12, "file": ase})
    await step("undo", {"file": ase})
    await step("redo", {"file": ase})

    # 2-frame sprite -> single-image export splits into smoke1.png/smoke2.png
    await step("export_sprite", {"out_path": png, "file": ase})
    import glob

    produced = glob.glob(os.path.join(d, "smoke*.png"))
    if not produced:
        failures.append(("export_sprite", "no PNG produced"))

    sheet = os.path.join(d, "sheet.png")
    data = os.path.join(d, "sheet.json")
    await step(
        "export_spritesheet",
        {"out_path": sheet, "data_path": data, "sheet_type": "packed", "file": ase},
    )
    if not os.path.isfile(sheet) or os.path.getsize(sheet) == 0:
        failures.append(("export_spritesheet", "sheet PNG missing/empty"))
    if not os.path.isfile(data):
        failures.append(("export_spritesheet", "JSON atlas missing"))

    # --- differentiator: transparent-padding measurement + QA sweep ---

    pad_ase = os.path.join(d, "pad.aseprite")
    await step("create_sprite", {"width": 20, "height": 20, "color_mode": "rgb", "file": pad_ase})
    await step(
        "draw_rectangle",
        {"x": 7, "y": 7, "width": 6, "height": 6, "color": "#ffffff", "file": pad_ase},
    )
    pad_res = await step("measure_padding", {"file": pad_ase})
    try:
        pad = json.loads(_text(pad_res))["padding"]
        if not (pad["left"] == pad["right"] == pad["top"] == pad["bottom"] == 7):
            failures.append(("measure_padding", f"expected 7px all sides, got {pad}"))
        else:
            print("  padding check: 7px symmetric — correct")
    except Exception as e:
        failures.append(("measure_padding", f"parse failed: {e}"))
    qa_res = await step(
        "qa_sweep",
        {
            "expected_width": 20,
            "expected_height": 20,
            "grid_multiple": 4,
            "max_colors": 4,
            "require_symmetric_padding": True,
            "file": pad_ase,
        },
    )
    try:
        qa = json.loads(_text(qa_res))
        if qa.get("failed", 1) != 0:
            failures.append(("qa_sweep", f"expected all-pass, got {qa.get('checks')}"))
        else:
            print(f"  qa_sweep: {qa['passed']}/{qa['passed']} checks pass")
    except Exception as e:
        failures.append(("qa_sweep", f"parse failed: {e}"))

    # --- flagship differentiator: one-action Unity sprite-sheet + .meta ---
    uni_ase = os.path.join(d, "uni.aseprite")
    uni_png = os.path.join(d, "uni.png")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": uni_ase})
    await step(
        "draw_rectangle",
        {"x": 2, "y": 2, "width": 12, "height": 12, "color": "#ff8800", "file": uni_ase},
    )
    await step("add_frame", {"file": uni_ase})
    await step("add_frame", {"file": uni_ase})  # 3 frames total
    await step("create_tag", {"name": "walk", "from_frame": 1, "to_frame": 3, "file": uni_ase})
    await step("list_tags", {"file": uni_ase})
    await step("delete_tag", {"name": "walk", "file": uni_ase})
    uni_res = await step(
        "export_unity_sprite", {"png_path": uni_png, "pixels_per_unit": 16, "file": uni_ase}
    )
    try:
        u = json.loads(_text(uni_res))
        xs = [sp["x"] for sp in u["sprites"]]
        ok = (
            u["frames"] == 3 and xs == [0, 16, 32] and u["png_exists"] and os.path.isfile(u["meta"])
        )
        if not ok:
            failures.append(
                (
                    "export_unity_sprite",
                    f"frames={u.get('frames')} xs={xs} meta={os.path.isfile(u.get('meta', ''))}",
                )
            )
        else:
            with open(u["meta"], encoding="utf-8") as mf:
                mtext = mf.read()
            if "spriteMode: 2" not in mtext or mtext.count("name: uni_") < 3:
                failures.append(
                    ("export_unity_sprite", "meta missing spriteMode:2 or sprite names")
                )
            else:
                try:
                    import yaml  # optional

                    yaml.safe_load(mtext)
                    print(f"  unity export: 3 sprites sliced, rects {xs}, .meta valid YAML")
                except ImportError:
                    print(
                        f"  unity export: 3 sprites sliced, rects {xs}, .meta structure ok (PyYAML absent)"
                    )
    except Exception as e:
        failures.append(("export_unity_sprite", f"parse failed: {e}"))

    # --- cel ops ---
    cel_ase = os.path.join(d, "cel.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": cel_ase})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 8, "height": 8, "color": "#ffffff", "file": cel_ase},
    )
    await step("set_cel_position", {"x": 2, "y": 2, "file": cel_ase})
    await step("set_cel_opacity", {"opacity": 128, "file": cel_ase})
    await step("clear_cel", {"file": cel_ase})

    # --- differentiator: index-adjacency palette ramp-walk ---
    ramp_ase = os.path.join(d, "ramp.aseprite")
    ramp = ["#202020", "#606060", "#a0a0a0", "#e0e0e0"]  # dark -> light ramp
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": ramp_ase})
    await step("set_palette", {"colors": ramp, "file": ramp_ase})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 8, "height": 8, "color": "#606060", "file": ramp_ase},
    )
    await step(
        "palette_ramp_walk",
        {
            "x": 0,
            "y": 0,
            "width": 8,
            "height": 8,
            "light_direction": "top_left",
            "steps": 2,
            "file": ramp_ase,
        },
    )
    tl = await step("get_pixel", {"x": 0, "y": 0, "file": ramp_ase})
    br = await step("get_pixel", {"x": 7, "y": 7, "file": ramp_ase})
    try:
        tl_c = json.loads(_text(tl))["color"][:7]
        br_c = json.loads(_text(br))["color"][:7]
        if tl_c != "#e0e0e0" or br_c != "#202020":
            failures.append(
                ("palette_ramp_walk", f"TL={tl_c} (want #e0e0e0), BR={br_c} (want #202020)")
            )
        else:
            print(
                f"  ramp-walk: lit corner {tl_c} (lightest idx), shadow corner {br_c} (darkest idx) — correct"
            )
    except Exception as e:
        failures.append(("palette_ramp_walk", f"parse failed: {e}"))
    await step(
        "apply_shading",
        {
            "x": 0,
            "y": 0,
            "width": 8,
            "height": 8,
            "light_direction": "right",
            "intensity": 0.6,
            "file": ramp_ase,
        },
    )

    # --- tween (parity) + smear (stretch) ---
    tw_ase = os.path.join(d, "tween.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": tw_ase})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 2, "height": 2, "color": "#ffffff", "file": tw_ase},
    )
    await step("duplicate_frame", {"number": 1, "file": tw_ase})
    await step("set_cel_position", {"x": 6, "y": 6, "frame": 2, "file": tw_ase})
    await step("tween_frames", {"from_frame": 1, "to_frame": 2, "count": 1, "file": tw_ase})
    tw = await step(
        "run_lua",
        {
            "code": "local c=app.activeLayer:cel(2); return J({x=c.position.x, y=c.position.y})",
            "file": tw_ase,
        },
    )
    try:
        tc = json.loads(_text(tw))
        if not (tc.get("x") == 3 and tc.get("y") == 3):
            failures.append(("tween_frames", f"midpoint cel expected (3,3), got {tc}"))
        else:
            print(f"  tween: inserted midpoint cel at ({tc['x']},{tc['y']}) — correct")
    except Exception as e:
        failures.append(("tween_frames", f"parse failed: {e}"))

    sm_ase = os.path.join(d, "smear.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": sm_ase})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 4, "height": 4, "color": "#ffffff", "file": sm_ase},
    )
    await step("duplicate_frame", {"number": 1, "file": sm_ase})
    await step("set_cel_position", {"x": 4, "y": 4, "frame": 2, "file": sm_ase})
    await step("smear_frame", {"from_frame": 1, "to_frame": 2, "file": sm_ase})
    sm = await step(
        "run_lua",
        {
            "code": "local s=app.activeSprite; local img=Image(s.width,s.height,ColorMode.RGB); img:drawSprite(s,3); return J({a11=app.pixelColor.rgbaA(img:getPixel(1,1)), a55=app.pixelColor.rgbaA(img:getPixel(5,5))})",
            "file": sm_ase,
        },
    )
    try:
        sc = json.loads(_text(sm))
        if not (100 < sc.get("a11", 0) < 200 and 100 < sc.get("a55", 0) < 200):
            failures.append(("smear_frame", f"expected ghost alphas ~128, got {sc}"))
        else:
            print(f"  smear: ghost trails a11={sc['a11']} a55={sc['a55']} — correct")
    except Exception as e:
        failures.append(("smear_frame", f"parse failed: {e}"))

    # --- differentiator: isometric primitives ---
    iso_ase = os.path.join(d, "iso.aseprite")
    await step("create_sprite", {"width": 96, "height": 96, "color_mode": "rgb", "file": iso_ase})
    boxres = await step(
        "draw_iso_box",
        {
            "center_x": 48,
            "center_y": 60,
            "half_width": 30,
            "height": 34,
            "color": "#8a94a0",
            "file": iso_ase,
        },
    )
    try:
        se = json.loads(_text(boxres))["face_se"]
        await step("iso_recessed_panel", {"points": se, "file": iso_ase})
        print("  iso box drawn; recessed port stamped on returned SE face")
    except Exception as e:
        failures.append(("draw_iso_box/iso_recessed_panel", f"{e}"))
    await step(
        "draw_iso_cylinder",
        {
            "center_x": 40,
            "top_y": 18,
            "radius": 7,
            "height": 18,
            "color": "#b07850",
            "file": iso_ase,
        },
    )
    await step(
        "fill_polygon",
        {"points": [[8, 10], [30, 14], [26, 30], [6, 26]], "color": "#40c080", "file": iso_ase},
    )
    await step("export_sprite", {"out_path": os.path.join(d, "iso.png"), "file": iso_ase})

    # --- parity additions: draw / color / transform ---
    add_ase = os.path.join(d, "add.aseprite")
    await step("create_sprite", {"width": 32, "height": 32, "color_mode": "rgb", "file": add_ase})
    await step(
        "draw_ellipse",
        {
            "center_x": 16,
            "center_y": 16,
            "radius_x": 10,
            "radius_y": 6,
            "color": "#ff00ff",
            "fill": True,
            "file": add_ase,
        },
    )
    await step(
        "draw_gradient",
        {
            "x": 0,
            "y": 0,
            "width": 32,
            "height": 8,
            "color1": "#000000",
            "color2": "#ffffff",
            "direction": "horizontal",
            "dither": True,
            "file": add_ase,
        },
    )
    await step(
        "apply_dither",
        {
            "x": 0,
            "y": 24,
            "width": 32,
            "height": 8,
            "color1": "#101020",
            "color2": "#3040a0",
            "density": 0.5,
            "file": add_ase,
        },
    )
    await step("add_outline", {"color": "#000000", "diagonal": False, "file": add_ase})
    await step(
        "replace_color",
        {"from_color": "#ff00ff", "to_color": "#00ffcc", "tolerance": 0, "file": add_ase},
    )
    await step(
        "adjust_hsl", {"hue_shift": 40, "saturation": 1.1, "lightness": 0.05, "file": add_ase}
    )
    await step("get_color_stats", {"top": 5, "file": add_ase})
    await step("rotate_sprite", {"degrees": 90, "file": add_ase})
    await step(
        "generate_color_ramp",
        {"base_color": "#3060c0", "count": 5, "hue_shift": True, "file": add_ase},
    )
    await step("quantize_to_palette", {"file": add_ase})

    # --- layer parity ---
    ly_ase = os.path.join(d, "layers.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": ly_ase})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 16, "height": 16, "color": "#804020", "file": ly_ase},
    )
    await step("add_layer", {"name": "top", "file": ly_ase})
    await step("set_layer_blend_mode", {"name": "top", "mode": "multiply", "file": ly_ase})
    await step("duplicate_layer", {"name": "top", "file": ly_ase})
    await step("move_layer", {"name": "top", "direction": "top", "file": ly_ase})
    await step(
        "merge_layer_down", {"name": "top", "file": ly_ase}
    )  # top has a layer beneath -> valid
    await step(
        "import_image_as_layer",
        {
            "image_path": os.path.join(d, "iso.png"),
            "layer_name": "ref",
            "x": 0,
            "y": 0,
            "file": ly_ase,
        },
    )

    # --- extract palette from an external PNG ---
    ep_ase = os.path.join(d, "extract.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": ep_ase})
    ep_res = await step(
        "extract_palette_from_image",
        {
            "image_path": os.path.join(d, "iso.png"),
            "max_colors": 8,
            "replace": True,
            "file": ep_ase,
        },
    )
    try:
        ep = json.loads(_text(ep_res))
        if ep.get("count", 0) < 2:
            failures.append(
                ("extract_palette_from_image", f"expected >=2 colors, got {ep.get('count')}")
            )
        else:
            print(f"  extract palette: {ep['count']} colors from iso.png")
    except Exception as e:
        failures.append(("extract_palette_from_image", f"parse failed: {e}"))

    # --- regression: replace_color must PRESERVE source alpha for an #rrggbb target ---
    ra_ase = os.path.join(d, "replace_alpha.aseprite")
    await step("create_sprite", {"width": 4, "height": 4, "color_mode": "rgb", "file": ra_ase})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 4, "height": 4, "color": "#00ff0080", "file": ra_ase},
    )  # alpha 128
    await step(
        "replace_color",
        {"from_color": "#00ff00", "to_color": "#0000ff", "tolerance": 0, "file": ra_ase},
    )  # no alpha given
    rap = await step("get_pixel", {"x": 1, "y": 1, "file": ra_ase})
    try:
        c = json.loads(_text(rap))["color"]  # #rrggbbaa
        if c.lower() != "#0000ff80":
            failures.append(("replace_color", f"expected alpha preserved (#0000ff80), got {c}"))
        else:
            print("  replace_color: source alpha 0x80 preserved on #rrggbb target — correct")
    except Exception as e:
        failures.append(("replace_color", f"parse failed: {e}"))

    # --- slices + slice-pivot -> Unity .meta (y-flip correctness) ---
    sl_ase = os.path.join(d, "slices.aseprite")
    sl_png = os.path.join(d, "slices.png")
    await step("create_sprite", {"width": 32, "height": 16, "color_mode": "rgb", "file": sl_ase})
    await step(
        "draw_rectangle",
        {"x": 4, "y": 2, "width": 8, "height": 8, "color": "#ffcc00", "file": sl_ase},
    )
    await step(
        "create_slice", {"name": "gizmo", "x": 4, "y": 2, "width": 8, "height": 8, "file": sl_ase}
    )
    await step("set_slice_pivot", {"name": "gizmo", "pivot_x": 4, "pivot_y": 8, "file": sl_ase})
    await step(
        "set_slice_center",
        {"name": "gizmo", "x": 2, "y": 2, "width": 4, "height": 4, "file": sl_ase},
    )
    await step("list_slices", {"file": sl_ase})
    sl_res = await step(
        "export_unity_slices", {"png_path": sl_png, "pixels_per_unit": 16, "file": sl_ase}
    )
    try:
        su = json.loads(_text(sl_res))
        sp = su["sprites"][0]
        # slice top-left (4,2) size 8x8 in a 16-tall texture -> Unity y = 16-(2+8) = 6
        # pivot (4,8) px -> Unity (0.5, 0.0)
        ok = (
            sp["y"] == 6
            and sp["x"] == 4
            and abs(sp["pivot"][0] - 0.5) < 1e-6
            and abs(sp["pivot"][1] - 0.0) < 1e-6
        )
        if not ok:
            failures.append(
                (
                    "export_unity_slices",
                    f"expected y=6 x=4 pivot[0.5,0.0], got x={sp['x']} y={sp['y']} pivot={sp['pivot']}",
                )
            )
        else:
            print(
                f"  unity slices: '{sp['name']}' rect y-flipped to {sp['y']}, pivot {sp['pivot']} — correct"
            )
    except Exception as e:
        failures.append(("export_unity_slices", f"parse failed: {e}"))
    # regression: a YAML-unsafe slice name must be quoted in the .meta (valid YAML)
    await step(
        "create_slice",
        {"name": "turret: base", "x": 0, "y": 0, "width": 4, "height": 4, "file": sl_ase},
    )
    yq_res = await step(
        "export_unity_slices",
        {"png_path": os.path.join(d, "slices2.png"), "pixels_per_unit": 16, "file": sl_ase},
    )
    try:
        with open(json.loads(_text(yq_res))["meta"], encoding="utf-8") as mf:
            mtext = mf.read()
        if 'name: "turret: base"' not in mtext:
            failures.append(("export_unity_slices", "YAML-unsafe slice name not quoted in .meta"))
        else:
            print("  unity slices: YAML-unsafe name 'turret: base' quoted in .meta — correct")
    except Exception as e:
        failures.append(("export_unity_slices", f"yaml-name check failed: {e}"))
    await step("delete_slice", {"name": "gizmo", "file": sl_ase})

    # --- batch folder engine (headless, non-destructive) ---
    bdir = os.path.join(d, "batchfolder")
    os.makedirs(bdir, exist_ok=True)
    bout = os.path.join(d, "batchout")
    for i in range(3):
        bf = os.path.join(bdir, f"b{i}.aseprite")
        await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": bf})
        await step(
            "draw_rectangle",
            {"x": 2, "y": 2, "width": 12, "height": 12, "color": "#3388cc", "file": bf},
        )
    bx = await step("batch_export", {"folder": bdir, "out_dir": bout, "format": "png", "scale": 2})
    try:
        b = json.loads(_text(bx))
        pngs = glob.glob(os.path.join(bout, "*.png"))
        if b.get("succeeded") != 3 or len(pngs) != 3:
            failures.append(
                (
                    "batch_export",
                    f"expected 3 PNGs, got succeeded={b.get('succeeded')} files={len(pngs)}",
                )
            )
        else:
            print(f"  batch_export: 3/3 sprites -> {len(pngs)} PNGs at 2x")
    except Exception as e:
        failures.append(("batch_export", f"parse failed: {e}"))
    await step(
        "batch_resize", {"folder": bdir, "out_dir": os.path.join(d, "batchrs"), "scale": 1.5}
    )
    bp = await step(
        "batch_apply_palette",
        {"folder": bdir, "out_dir": os.path.join(d, "batchpal"), "preset": "gameboy"},
    )
    try:
        bpr = json.loads(_text(bp))
        if bpr.get("succeeded") != 3:
            failures.append(
                ("batch_apply_palette", f"expected 3 succeeded, got {bpr.get('succeeded')}")
            )
        else:
            print("  batch_apply_palette: 3/3 sprites palette-locked to gameboy")
    except Exception as e:
        failures.append(("batch_apply_palette", f"parse failed: {e}"))

    # --- MCP resources read back the cached QA + export state ---
    async def read_res(uri):
        try:
            contents = await mcp.read_resource(uri)
            parts = list(contents) if not isinstance(contents, (str, bytes)) else [contents]
            txt = " ".join(
                getattr(p, "content", getattr(p, "text", str(p)))
                if not isinstance(p, (str, bytes))
                else str(p)
                for p in parts
            )
            print(f"  RES {uri}: {str(txt)[:120]}")
            return str(txt)
        except Exception as e:
            failures.append((f"resource {uri}", str(e)))
            return ""

    qa_last = await read_res("aseprite://qa/last")
    exp_last = await read_res("aseprite://export/last")
    if "qa_sweep" not in qa_last and "measure_padding" not in qa_last:
        failures.append(("aseprite://qa/last", f"expected cached QA, got {qa_last[:80]}"))
    if "slices" not in exp_last and "frames" not in exp_last:
        failures.append(("aseprite://export/last", f"expected cached export, got {exp_last[:80]}"))
    await read_res("aseprite://sprite/active")
    await read_res("aseprite://palette/active")
    await read_res("aseprite://docs")
    upd = await read_res("aseprite://update")
    if "current" not in upd:
        failures.append(("aseprite://update", f"expected version info, got {upd[:80]}"))

    # --- v0.2 surface ---
    import json as _json

    def _parse(res):
        return _json.loads(_text(res))

    v2 = os.path.join(d, "v02.aseprite")
    await step("create_sprite", {"width": 32, "height": 32, "file": v2})
    await step(
        "draw_pixels",
        {
            "pixels": [{"x": 1, "y": 1, "color": "#ff0000"}, {"x": 2, "y": 2, "color": "#00ff00"}],
            "file": v2,
        },
    )
    await step(
        "draw_polyline",
        {"points": [[4, 28], [16, 4], [28, 28]], "color": "#ffffff", "close": True, "file": v2},
    )
    await step("adjust_brightness_contrast", {"brightness": 10, "contrast": 5, "file": v2})
    await step("desaturate", {"file": v2})
    await step("invert_colors", {"file": v2})
    await step("box_blur", {"radius": 1, "file": v2})
    await step("sharpen", {"strength": 0.4, "file": v2})
    await step("select_ellipse", {"x": 2, "y": 2, "width": 20, "height": 12, "file": v2})
    await step("select_by_color", {"color": "#00000000", "tolerance": 4, "file": v2})
    await step("invert_selection", {"file": v2})
    await step("get_selection", {"file": v2})
    await step("erase_area", {"x": 4, "y": 4, "width": 6, "height": 6, "file": v2})
    await step("add_group", {"name": "Body", "file": v2})
    await step("add_layer", {"name": "Arm", "file": v2})
    await step("move_layer_to_group", {"layer": "Arm", "group": "Body", "file": v2})
    res = await step("list_layers", {"file": v2})
    if res is not None and "Body/Arm" not in _text(res):
        failures.append(("list_layers", "nested path Body/Arm missing from tree"))
    await step(
        "draw_rectangle",
        {
            "x": 0,
            "y": 0,
            "width": 3,
            "height": 3,
            "color": "#ffcc00",
            "fill": True,
            "layer": "Body/Arm",
            "file": v2,
        },
    )
    await step("set_sprite_metadata", {"entries": {"generated_by": "smoke", "rev": 2}, "file": v2})
    res = await step("get_sprite_metadata", {"file": v2})
    if res is not None and "generated_by" not in _text(res):
        failures.append(("get_sprite_metadata", "metadata did not round-trip"))
    await step(
        "paint_with_stamp",
        {"points": [[20, 20], [26, 24]], "source_rect": [0, 0, 3, 3], "file": v2},
    )

    # animation QA + frame ops
    await step("add_frames", {"count": 2, "file": v2})
    await step("set_frame_durations", {"from_frame": 1, "to_frame": 3, "ms": 90, "file": v2})
    res = await step("frame_diff", {"frame_a": 1, "frame_b": 2, "file": v2})
    onion_png = os.path.join(d, "onion.png")
    await step(
        "render_onion_composite",
        {"frame": 2, "output_path": onion_png, "prev": 1, "next": 1, "file": v2},
    )
    if not os.path.isfile(onion_png):
        failures.append(("render_onion_composite", "no PNG written"))
    # --- polish: targeting, banded gradients, previews, indexed, Godot ---
    pol = os.path.join(d, "polish.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": pol})
    await step(
        "draw_gradient",
        {
            "x": 0,
            "y": 0,
            "width": 16,
            "height": 16,
            "color1": "#102040",
            "color2": "#f0a060",
            "dither": True,
            "bands": 4,
            "file": pol,
        },
    )
    await step("add_frames", {"count": 2, "file": pol})
    await step("add_layer", {"name": "top", "file": pol})
    await step("select_frame", {"number": 1, "file": pol})
    await step("select_layer", {"name": "top", "file": pol})
    await step(
        "edit_batch",
        {
            "steps": [
                {"tool": "select_frame", "args": {"number": 2}},
                {"tool": "select_layer", "args": {"name": "top"}},
                {
                    "tool": "draw_rectangle",
                    "args": {"x": 1, "y": 1, "width": 3, "height": 3, "color": "#00ff00"},
                },
            ],
            "file": pol,
        },
    )
    await step("create_tag", {"name": "walk", "from_frame": 1, "to_frame": 2, "file": pol})
    await step("set_tag_direction", {"name": "walk", "direction": "pingpong", "file": pol})
    godot_png = os.path.join(d, "godot_sheet.png")
    await step("export_godot", {"png_path": godot_png, "file": pol})
    if not os.path.isfile(godot_png[:-4] + ".tres"):
        failures.append(("export_godot", "no .tres written"))
    # tween art redrawn in a new place, with every cel left at (0, 0)
    dt = os.path.join(d, "drawn_tween.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": dt})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 2, "height": 2, "color": "#ffffff", "fill": True, "file": dt},
    )
    await step("add_frames", {"count": 1, "file": dt})
    await step(
        "edit_batch",
        {
            "steps": [
                {"tool": "select_frame", "args": {"number": 2}},
                {
                    "tool": "draw_rectangle",
                    "args": {
                        "x": 8,
                        "y": 8,
                        "width": 2,
                        "height": 2,
                        "color": "#ffffff",
                        "fill": True,
                    },
                },
            ],
            "file": dt,
        },
    )
    await step("tween_frames", {"from_frame": 1, "to_frame": 2, "count": 1, "file": dt})
    moved = await step(
        "run_lua",
        {
            "code": "local c=app.activeLayer:cel(2); return J({x=c.position.x, y=c.position.y})",
            "file": dt,
        },
    )
    if '"x":4' not in _text(moved).replace(" ", "") or '"y":4' not in _text(moved).replace(" ", ""):
        failures.append(
            ("tween_frames", f"drawn frames: expected cel at (4,4), got {_text(moved)}")
        )
    # run_lua with edit=true is capped and leaves no trace when stopped
    await step("set_safety_rails", {"max_changed_pixels": 3})
    try:
        await mcp.call_tool(
            "run_lua",
            {
                "code": "editCel(function(i) i:clear(app.pixelColor.rgba(1,2,3,255)) end) return 1",
                "edit": True,
                "save": True,
                "file": dt,
            },
        )
        failures.append(("run_lua", "edit=true went past the pixel cap"))
    except Exception as e:
        if "refused" not in str(e):
            failures.append(("run_lua", f"expected the cap to refuse it: {e}"))
    await step("add_layer", {"name": "over", "file": dt})
    await step("move_layer", {"name": "over", "direction": "bottom", "file": dt})
    await step("set_safety_rails", {"max_changed_pixels": 250000})
    # export_to_game, and the button in the extension writing identical files.
    games = {
        "godot_game": "project.godot",
        "unity_game": "Assets/x",
        "unity_game/ProjectSettings": "x",
    }
    for rel, marker in games.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel, marker)), exist_ok=True)
        open(os.path.join(d, rel, marker), "w").close()
    ext = os.path.join(
        os.path.dirname(os.path.abspath(aseprite_claude_connector.__file__)), "extension"
    )
    for game, made in (
        ("godot_game", ["sprites/polish.tres"]),
        ("unity_game", ["Assets/Sprites/polish.png.meta"]),
    ):
        root = os.path.join(d, game)
        await step("export_to_game", {"game_dir": root, "file": pol})
        await step("export_to_game", {"file": pol})  # the folder is remembered
        for rel in made:
            path = os.path.join(root, rel)
            if not os.path.isfile(path):
                failures.append(("export_to_game", f"{rel} not written"))
                continue
            before = open(path, encoding="utf-8").read()
            # Leave only the guid, so a script that quietly failed can't pass.
            keep = "".join(ln for ln in before.splitlines(True) if ln.startswith("guid:"))
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(keep)
            script = os.path.join(d, game + ".lua")
            with open(script, "w", encoding="utf-8") as f:
                f.write(
                    f"dofile({json.dumps(os.path.join(ext, 'game-export.lua'))});"
                    f"ClaudeGameExport.exportTo(app.activeSprite, {json.dumps(root)}, 'polish')"
                )
            done = subprocess.run(
                [load_config().aseprite_path, "--batch", pol, "--script", script],
                capture_output=True,
                text=True,
            )
            after = open(path, encoding="utf-8").read()
            if done.returncode or after != before:
                failures.append(
                    ("game-export.lua", f"{rel} differs from export_to_game: {done.stderr}")
                )
            else:
                print(f"  export button matches export_to_game for {rel}")
    await step(
        "draw_iso_box",
        {
            "center_x": 8,
            "center_y": 10,
            "half_width": 4,
            "height": 3,
            "color": "#6080c0",
            "preview": True,
            "file": pol,
        },
    )
    await step("set_color_mode", {"mode": "indexed", "file": pol})

    # --- phase 4: docs, summary, rails ---
    await step("describe_sprite", {"file": v2})
    await step("search_api_docs", {"query": "Image:drawImage"})
    await step("search_manual", {"query": "onion skinning"})
    await step("set_safety_rails", {"max_changed_pixels": 100000})
    await step(
        "edit_batch",
        {
            "steps": [
                {"tool": "add_layer", "args": {"name": "batched"}},
                {
                    "tool": "draw_line",
                    "args": {"x1": 0, "y1": 0, "x2": 3, "y2": 3, "color": "#ff0000"},
                },
            ],
            "label": "Smoke batch",
            "file": v2,
        },
    )
    for tool, args in (
        ("look", {"file": v2}),
        ("look", {"x": 0, "y": 0, "width": 4, "height": 4, "background": "#ffffff", "file": v2}),
        ("look_animation", {"file": v2}),
        ("look_onion", {"frame": 2, "prev": 1, "next": 1, "file": v2}),
        (
            "draw_line",
            {"x1": 0, "y1": 0, "x2": 3, "y2": 3, "color": "#ff0000", "preview": True, "file": v2},
        ),
    ):
        res = await step(tool, args)
        if res is not None and "image" not in repr(res):
            failures.append((tool, "no image returned"))
    await step("reverse_frames", {"file": v2})
    await step("set_onion_skin", {"active": True, "prev_frames": 2, "next_frames": 1, "file": v2})

    # tween easing + opacity
    tw = os.path.join(d, "tween.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "file": tw})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 4, "height": 4, "color": "#ff00ff", "fill": True, "file": tw},
    )
    await step("duplicate_frame", {"number": 1, "file": tw})
    await step("set_cel_position", {"frame": 2, "x": 10, "y": 10, "file": tw})
    await step(
        "tween_frames",
        {"from_frame": 1, "to_frame": 2, "count": 2, "easing": "smoothstep", "file": tw},
    )
    await step(
        "tween_cel_opacity",
        {"from_frame": 1, "to_frame": 4, "from_opacity": 255, "to_opacity": 60, "file": tw},
    )

    # canvas ops
    await step("expand_canvas", {"left": 2, "right": 2, "top": 0, "bottom": 4, "file": tw})
    sheet2 = os.path.join(d, "import-sheet.png")
    await step("export_spritesheet", {"out_path": sheet2, "file": tw})
    imp = os.path.join(d, "imported.aseprite")
    await step("create_sprite", {"width": 20, "height": 20, "file": imp})
    await step(
        "import_spritesheet",
        {"sheet_path": sheet2, "frame_width": 20, "frame_height": 20, "file": imp},
    )

    # palette v0.2
    await step("sort_palette", {"by": "luminance", "file": v2})
    await step("palette_from_sprite", {"max_colors": 8, "file": v2})
    gpl = os.path.join(d, "smoke.gpl")
    await step("save_palette", {"path": gpl, "file": v2})
    if not os.path.isfile(gpl):
        failures.append(("save_palette", "no palette file written"))
    await step("load_palette", {"path": gpl, "file": v2})

    # tilemaps
    tm = os.path.join(d, "tilemap.aseprite")
    await step("create_sprite", {"width": 32, "height": 16, "file": tm})
    await step(
        "create_tilemap_layer", {"name": "ground", "tile_width": 8, "tile_height": 8, "file": tm}
    )
    await step("add_tile", {"layer": "ground", "file": tm})
    await step(
        "draw_on_tile",
        {
            "layer": "ground",
            "tile_index": 1,
            "pixels": [{"x": 0, "y": 0, "color": "#3e8948"}, {"x": 7, "y": 7, "color": "#4faf5c"}],
            "file": tm,
        },
    )
    await step(
        "set_tiles",
        {
            "layer": "ground",
            "frame": 1,
            "tiles": [{"column": 0, "row": 0, "index": 1}, {"column": 3, "row": 1, "index": 1}],
            "file": tm,
        },
    )
    res = await step("get_tilemap_info", {"layer": "ground", "file": tm})
    if res is not None:
        try:
            info = _parse(res)
            grid = info.get("tiles") or info.get("grid") or []
            flat = [t for row in grid for t in row] if grid else []
            if 1 not in flat:
                failures.append(
                    ("get_tilemap_info", f"placed tile index missing: {str(info)[:120]}")
                )
        except Exception as e:
            failures.append(("get_tilemap_info", f"parse failed: {e}"))
    ts_png = os.path.join(d, "tileset.png")
    await step("export_tileset", {"layer": "ground", "output_path": ts_png, "file": tm})
    if not os.path.isfile(ts_png):
        failures.append(("export_tileset", "no tileset PNG written"))

    # session / export / transform / tags pack
    await step("open_sprite", {"path": v2})
    saved_copy = os.path.join(d, "copy.aseprite")
    await step("save_sprite", {"path": saved_copy, "file": v2})
    if not os.path.isfile(saved_copy):
        failures.append(("save_sprite", "no copy written"))
    lay_dir = os.path.join(d, "layers-out")
    await step("export_layers", {"out_dir": lay_dir, "file": v2})
    if not (os.path.isdir(lay_dir) and os.listdir(lay_dir)):
        failures.append(("export_layers", "no per-layer PNGs written"))
    await step("create_tag", {"name": "walk", "from_frame": 1, "to_frame": 2, "file": v2})
    await step("rename_tag", {"old_name": "walk", "new_name": "run", "file": v2})
    await step("set_tag_color", {"name": "run", "color": "#0ac830", "file": v2})
    await step("set_tag_range", {"name": "run", "from_frame": 1, "to_frame": 3, "file": v2})
    await step("set_tag_direction", {"name": "run", "direction": "pingpong", "file": v2})
    tag_dir = os.path.join(d, "tags-out")
    await step("export_tags", {"out_dir": tag_dir, "format": "gif", "file": v2})
    if not (os.path.isdir(tag_dir) and any(f.endswith(".gif") for f in os.listdir(tag_dir))):
        failures.append(("export_tags", "no per-tag GIF written"))
    ac = os.path.join(d, "autocrop.aseprite")
    await step("create_sprite", {"width": 40, "height": 40, "file": ac})
    await step(
        "draw_rectangle",
        {"x": 10, "y": 10, "width": 5, "height": 5, "color": "#ff0000", "fill": True, "file": ac},
    )
    res = await step("autocrop_sprite", {"file": ac})
    if res is not None and '"width": 5' not in _text(res).replace("  ", " "):
        # size json formatting varies; parse instead
        try:
            info = _parse(res)
            if info["new"]["width"] != 5 or info["new"]["height"] != 5:
                failures.append(("autocrop_sprite", f"expected 5x5, got {info['new']}"))
        except Exception as e:
            failures.append(("autocrop_sprite", f"parse failed: {e}"))
    await step("set_color_mode", {"mode": "indexed", "dithering": "ordered", "file": ac})

    # live-only tools must refuse cleanly under the headless backend
    for live_tool, args in (
        ("get_editor_state", {}),
        ("show_choice_dialog", {"message": "x", "options": ["a"]}),
        ("watch_changes", {}),
        ("set_active_sprite", {"filename": "x"}),
        ("list_sprites", {}),
    ):
        try:
            await mcp.call_tool(live_tool, args)
            failures.append((live_tool, "expected a live-backend refusal under headless"))
        except Exception as e:
            if "live backend" in str(e):
                print(f"  OK  {live_tool}: refuses cleanly under headless")
            else:
                failures.append((live_tool, f"unexpected error text: {e}"))

    # --- the cool extras ---

    def payload(res):
        """The JSON part of a result, picture or no picture."""
        if isinstance(res, tuple):
            res = res[0]
        parts = res if isinstance(res, list) else [res]
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                return json.loads(text)
        raise ValueError(f"no JSON in {res}")

    def has_picture(res):
        parts = res[0] if isinstance(res, tuple) else res
        return any(getattr(p, "type", "") == "image" for p in parts)

    def check(name, ok, detail=""):
        if ok:
            print(f"  OK  {name}")
        else:
            failures.append((name, detail or "check failed"))

    # in-betweening: two poses of different shape, one frame apart
    ib = os.path.join(d, "inbetween.aseprite")
    await step("create_sprite", {"width": 24, "height": 24, "color_mode": "rgb", "file": ib})
    await step("add_layer", {"name": "backdrop", "file": ib})
    await step("add_frame", {"file": ib})
    await step(
        "run_lua",
        {
            "file": ib,
            "edit": True,
            "save": True,
            "code": """
local s = app.activeSprite
local a = Image(24, 24, ColorMode.RGB); a:clear(Color{ r = 200, g = 40, b = 40 })
local b = Image(24, 24, ColorMode.RGB)
for x = 0, 3 do for y = 0, 5 do b:drawPixel(x + 2, y + 2, Color{ r = 200, g = 40, b = 40 }) end end
local c = Image(24, 24, ColorMode.RGB)
for x = 0, 7 do for y = 0, 1 do c:drawPixel(x + 14, y + 18, Color{ r = 40, g = 40, b = 200 }) end end
s.layers[1]:cel(1).image = b
s:newCel(s.layers[1], 2, c, Point(0, 0))
s:newCel(s.layers[2], 1, a, Point(0, 0))
s:newCel(s.layers[2], 2, a, Point(0, 0))
app.activeLayer = s.layers[1]
s.layers[2].isVisible = false
return J({ ok = true })
""",
        },
    )
    res = await step(
        "inbetween",
        {"from_frame": 1, "count": 3, "layer": "Layer 1", "smear": True, "file": ib},
    )
    made = payload(res)["result"]
    check("inbetween adds frames", made["frames"] == 5 and made["inserted"] == [2, 3, 4], made)
    check("inbetween shows the result", has_picture(res))
    colors = await step(
        "run_lua",
        {
            "file": ib,
            "code": """
local s = app.activeSprite
local seen, counts = {}, {}
for n = 1, 5 do
  local cel = s.layers[1]:cel(n)
  local solid = 0
  for it in cel.image:pixels() do
    local v = it()
    if app.pixelColor.rgbaA(v) > 0 then solid = solid + 1; seen[v] = true end
  end
  counts[n] = solid
end
local kinds = 0
for _ in pairs(seen) do kinds = kinds + 1 end
return J({ kinds = kinds, counts = counts, held = s.layers[2]:cel(3) ~= nil })
""",
        },
    )
    found = json.loads(_text(colors))
    check("inbetween invents no colors", found["kinds"] == 2, found)
    check("inbetween keeps art on every frame", min(found["counts"]) > 0, found)
    check("other layers hold through inbetween", found["held"], found)

    # walk cycle
    wk = os.path.join(d, "walk.aseprite")
    await step("create_sprite", {"width": 64, "height": 64, "color_mode": "rgb", "file": wk})
    res = await step(
        "walk_cycle_template", {"body_height": 48, "frames": 8, "gait": "run", "file": wk}
    )
    made = json.loads(_text(res))
    check(
        "walk cycle uses a blank sprite", made["first_frame"] == 1 and made["last_frame"] == 8, made
    )
    tags = json.loads(_text(await step("list_tags", {"file": wk})))
    check("walk cycle is tagged", "run" in str(tags), tags)
    loop = json.loads(_text(await step("check_loop", {"tag": "run", "file": wk})))
    check("a walk cycle loops cleanly", loop["verdict"] == "smooth", loop)
    res = await step(
        "walk_cycle_template", {"body_height": 40, "frames": 4, "facing": "left", "file": wk}
    )
    check("a second cycle goes after the first", json.loads(_text(res))["first_frame"] == 9)
    try:
        await mcp.call_tool("walk_cycle_template", {"body_height": 200, "file": wk})
        failures.append(("walk_cycle_template", "should refuse a canvas too small"))
    except Exception as e:
        check("walk cycle refuses a small canvas", "canvas" in str(e), e)

    # timing and loop checks
    res = await step("apply_timing", {"preset": "ease_in_out", "tag": "run", "file": wk})
    check("timing returns durations", len(json.loads(_text(res))["durations_ms"]) == 8)
    info = await step(
        "run_lua",
        {
            "file": wk,
            "code": "local s = app.activeSprite\n"
            "return J({ a = s.frames[1].duration, b = s.frames[4].duration })",
        },
    )
    speeds = json.loads(_text(info))
    check("timing lands on the frames", speeds["a"] > speeds["b"], speeds)

    still = os.path.join(d, "still.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": still})
    await step(
        "draw_rectangle",
        {"x": 1, "y": 1, "width": 3, "height": 3, "color": "#ff0000", "file": still},
    )
    await step("duplicate_frame", {"number": 1, "file": still})
    await step("duplicate_frame", {"number": 1, "file": still})
    verdict = json.loads(_text(await step("check_loop", {"file": still})))["verdict"]
    check("identical frames read as static", verdict == "static", verdict)

    # strays, and the extended outline
    st = os.path.join(d, "stray.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": st})
    await step(
        "draw_rectangle", {"x": 2, "y": 2, "width": 5, "height": 5, "color": "#20a040", "file": st}
    )
    await step(
        "draw_rectangle",
        {"x": 12, "y": 12, "width": 1, "height": 1, "color": "#ff00ff", "file": st},
    )
    res = await step("find_stray_pixels", {"file": st})
    report = payload(res)
    check("the stray pixel is found", report["first_isolated"] == [[12, 12]], report)
    check("strays come with a picture", has_picture(res))

    res = await step("add_outline", {"selective": True, "all_frames": True, "file": st})
    made = json.loads(_text(res))
    check("selective outline covers the cel", made["frames"] == 1 and made["pixels"] > 20, made)
    px = await step(
        "run_lua",
        {
            "file": st,
            "code": """
local s = app.activeSprite
local i = Image(s.width, s.height, ColorMode.RGB); i:drawSprite(s, 1)
local v = i:getPixel(1, 4)
local pc = app.pixelColor
return J({ r = pc.rgbaR(v), g = pc.rgbaG(v), b = pc.rgbaB(v), a = pc.rgbaA(v) })
""",
        },
    )
    edge = json.loads(_text(px))
    check(
        "selective outline darkens the art's color", edge["a"] == 255 and 0 < edge["g"] < 160, edge
    )

    # variants, GameMaker, atlas
    out_dir = os.path.join(d, "out")
    res = await step(
        "recolor_variants",
        {
            "variants": {"blue": {"#20a040": "#2040c0"}, "gold": {"#123456": "#c0a020"}},
            "output_dir": out_dir,
            "name": "gem",
            "file": st,
        },
    )
    meta = payload(res)
    check("variants are written", all(os.path.getsize(p) > 0 for p in meta["files"].values()), meta)
    check("unmatched colors are reported", meta["unmatched"] == {"gold": ["#123456"]}, meta)

    res = json.loads(
        _text(await step("export_gamemaker", {"output_dir": out_dir, "name": "runner", "file": wk}))
    )
    names = [s["file"] for s in res["strips"]]
    check("GameMaker strips follow its naming", "runner_run_strip8.png" in names, names)
    await step(
        "open_sprite",
        {
            "path": os.path.join(out_dir, "runner_run_strip8.png"),
        },
    )

    atlas = os.path.join(out_dir, "atlas.png")
    res = await step("pack_atlas", {"sprites": [wk, st], "out_png": atlas})
    made = json.loads(_text(res))
    with open(made["json"], encoding="utf-8") as f:
        mapped = json.load(f)
    check(
        "the atlas maps every frame",
        "walk 0" in mapped["frames"] and "stray 0" in mapped["frames"],
        list(mapped["frames"])[:4],
    )

    # reference layer
    await step("run_lua", {"file": st, "code": "return J({ ok = true })"})
    ref_png = os.path.join(out_dir, "gem_blue.png")
    made = json.loads(_text(await step("add_reference_image", {"image_path": ref_png, "file": wk})))
    check("the reference covers every frame", made["frames"] == 12, made)
    layers = await step(
        "run_lua",
        {
            "file": wk,
            "code": """
local s = app.activeSprite
local top = s.layers[#s.layers]
return J({ name = top.name, locked = not top.isEditable, opacity = top.opacity })
""",
        },
    )
    top = json.loads(_text(layers))
    check(
        "the reference is faded and locked",
        top == {"name": "Reference", "locked": True, "opacity": 90},
        top,
    )

    # "fix this bit": a selection can't persist in a file, so make it in the same script
    from aseprite_claude_connector.tools._common import Captured, rails, run
    from aseprite_claude_connector.tools.safety import _clipped

    fx = os.path.join(d, "fix.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": fx})
    await step(
        "draw_rectangle",
        {"x": 0, "y": 0, "width": 16, "height": 16, "color": "#101010", "file": fx},
    )
    rails.capturing = True
    try:
        tool = mcp._tool_manager.get_tool("draw_rectangle")
        tool.fn(x=0, y=0, width=16, height=16, color="#ffffff")
    except Captured as caught:
        captured = caught.body
    finally:
        rails.capturing = False
    run(
        "app.activeSprite.selection = Selection(Rectangle(4, 4, 4, 4))\n" + _clipped([captured]),
        mutates=True,
        undo_label="Fix this bit",
        file=fx,
    )
    probe = await step(
        "run_lua",
        {
            "file": fx,
            "code": """
local s = app.activeSprite
local i = Image(s.width, s.height, ColorMode.RGB); i:drawSprite(s, 1)
local pc = app.pixelColor
return J({ inside = pc.rgbaR(i:getPixel(5, 5)), outside = pc.rgbaR(i:getPixel(1, 1)),
  edge = pc.rgbaR(i:getPixel(8, 5)) })
""",
        },
    )
    clip = json.loads(_text(probe))
    check("edits land inside the selection", clip["inside"] == 255, clip)
    check(
        "edits outside the selection are put back",
        clip["outside"] == 16 and clip["edge"] == 16,
        clip,
    )
    try:
        await mcp.call_tool(
            "edit_in_selection",
            {
                "steps": [
                    {
                        "tool": "draw_pixels",
                        "args": {"pixels": [{"x": 0, "y": 0, "color": "#ffffff"}]},
                    }
                ],
                "file": fx,
            },
        )
        failures.append(("edit_in_selection", "should refuse with nothing selected"))
    except Exception as e:
        check("edit_in_selection needs a selection", "select an area" in str(e), e)

    # journal, explanations, and the timelapse
    summary = json.loads(_text(await step("change_summary", {"last": 5})))
    check("the journal names the edit", summary["summary"][-1]["edit"] == "Fix this bit", summary)
    check("the journal knows the frame", summary["summary"][-1]["frames"] == "1", summary)
    explained = json.loads(_text(await step("explain_changes", {"last": 40})))
    check(
        "explanations come back",
        any("Rectangle (U" in x["by_hand"] for x in explained["explanations"]),
        explained,
    )

    rec = os.path.join(d, "rec.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": rec})
    await step("start_recording", {"file": rec})
    for n in range(3):
        await step(
            "draw_rectangle",
            {"x": n * 4, "y": 2, "width": 3, "height": 3, "color": "#ffaa00", "file": rec},
        )
    gif = os.path.join(out_dir, "build.gif")
    made = json.loads(_text(await step("stop_recording", {"out_path": gif, "frame_ms": 200})))
    check(
        "the timelapse holds the start and each edit",
        made["frames"] == 4 and made["failed_captures"] == 0,
        made,
    )
    opened = await step(
        "run_lua",
        {
            "file": gif,
            "code": "local s = app.activeSprite\nreturn J({ w = s.width, frames = #s.frames })",
        },
    )
    shown = json.loads(_text(opened))
    check("Aseprite can open the timelapse", shown["frames"] >= 4 and shown["w"] > 16, shown)

    # --- MCP prompt renders its guidance ---
    try:
        pr = await mcp.get_prompt(
            "unity_qa_gate", {"expected_size": "64x64", "grid": "16", "max_colors": "16"}
        )
        msgs = getattr(pr, "messages", pr)
        blob = str(msgs)
        if "qa_sweep" not in blob or "export_unity" not in blob:
            failures.append(("prompt unity_qa_gate", "guidance missing expected tool references"))
        else:
            print("  prompt unity_qa_gate: renders the QA->export chain")
    except Exception as e:
        failures.append(("prompt unity_qa_gate", str(e)))

    print()
    if failures:
        print(f"SMOKE FAILED ({len(failures)}):")
        for name, err in failures:
            print(f"  - {name}: {err}")
        return 1
    print(
        f"SMOKE OK — all steps passed. frames->{sorted(os.path.basename(p) for p in produced)}, sheet={sheet}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
