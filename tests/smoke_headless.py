"""End-to-end smoke test of the headless backend and the MCP dispatch layer.

Runs real tool calls through the FastMCP server against a throwaway .aseprite,
collecting pass/fail per step, then checks the exported PNG is non-empty.

    ASEPRITE_MCP_BACKEND=headless python tests/smoke_headless.py

Requires Aseprite installed (auto-detected, or set ASEPRITE_PATH).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

os.environ.setdefault("ASEPRITE_MCP_BACKEND", "headless")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aseprite_live_mcp.server import build_server  # noqa: E402


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
        "status", "get_sprite_info", "create_sprite", "draw_rectangle", "export_sprite",
        "add_layer", "delete_layer", "rename_layer", "set_layer_visibility",
        "set_layer_opacity", "flatten_sprite",
        "add_frame", "duplicate_frame", "delete_frame", "set_frame_duration",
        "export_spritesheet",
        "draw_line", "draw_circle", "fill_area",
        "get_palette", "set_palette_color", "add_palette_color", "set_palette", "apply_preset_palette",
        "get_pixel", "get_pixels", "select_rectangle", "select_all", "deselect", "run_lua",
        "flip_sprite", "resize_sprite", "crop_sprite", "undo", "redo",
        "measure_padding", "qa_sweep", "export_unity_sprite",
        "create_tag", "delete_tag", "list_tags",
        "clear_cel", "set_cel_position", "set_cel_opacity",
        "apply_shading", "palette_ramp_walk",
        "tween_frames", "smear_frame",
        "draw_iso_box", "draw_iso_cylinder", "fill_polygon", "iso_recessed_panel",
        "rotate_sprite", "draw_ellipse", "draw_gradient", "apply_dither", "add_outline",
        "generate_color_ramp", "extract_palette_from_image",
        "replace_color", "quantize_to_palette", "adjust_hsl", "get_color_stats",
        "set_layer_blend_mode", "duplicate_layer", "merge_layer_down", "move_layer",
        "import_image_as_layer",
        "create_slice", "set_slice_pivot", "set_slice_center", "list_slices", "delete_slice",
        "export_unity_slices",
        "batch_export", "batch_resize", "batch_apply_palette",
    }
    missing = required - set(tools)
    assert not missing, f"missing tools: {missing}"

    # MCP-native integration layer: prompts + resources (unique to this server).
    prompt_names = sorted(p.name for p in await mcp.list_prompts())
    resource_uris = sorted(str(r.uri) for r in await mcp.list_resources())
    print(f"registered prompts ({len(prompt_names)}):", prompt_names)
    print(f"registered resources ({len(resource_uris)}):", resource_uris)
    assert len(prompt_names) == 5, f"expected 5 prompts, got {prompt_names}"
    assert len(resource_uris) == 5, f"expected 5 resources, got {resource_uris}"

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
    await step("draw_rectangle", {"x": 8, "y": 8, "width": 16, "height": 16, "color": "#ff0000", "file": ase})
    await step("draw_line", {"x1": 0, "y1": 0, "x2": 31, "y2": 31, "color": "#00ff00", "file": ase})
    await step("draw_circle", {"center_x": 16, "center_y": 16, "radius": 6, "color": "#0000ff", "fill": True, "file": ase})
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
    await step("run_lua", {"code": "return J({ w = app.activeSprite.width, layers = #app.activeSprite.layers })", "file": ase})
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
    await step("export_spritesheet", {"out_path": sheet, "data_path": data, "sheet_type": "packed", "file": ase})
    if not os.path.isfile(sheet) or os.path.getsize(sheet) == 0:
        failures.append(("export_spritesheet", "sheet PNG missing/empty"))
    if not os.path.isfile(data):
        failures.append(("export_spritesheet", "JSON atlas missing"))

    # --- differentiator: transparent-padding measurement + QA sweep ---
    import json
    pad_ase = os.path.join(d, "pad.aseprite")
    await step("create_sprite", {"width": 20, "height": 20, "color_mode": "rgb", "file": pad_ase})
    await step("draw_rectangle", {"x": 7, "y": 7, "width": 6, "height": 6, "color": "#ffffff", "file": pad_ase})
    pad_res = await step("measure_padding", {"file": pad_ase})
    try:
        pad = json.loads(_text(pad_res))["padding"]
        if not (pad["left"] == pad["right"] == pad["top"] == pad["bottom"] == 7):
            failures.append(("measure_padding", f"expected 7px all sides, got {pad}"))
        else:
            print("  padding check: 7px symmetric — correct")
    except Exception as e:
        failures.append(("measure_padding", f"parse failed: {e}"))
    qa_res = await step("qa_sweep", {
        "expected_width": 20, "expected_height": 20, "grid_multiple": 4,
        "max_colors": 4, "require_symmetric_padding": True, "file": pad_ase,
    })
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
    await step("draw_rectangle", {"x": 2, "y": 2, "width": 12, "height": 12, "color": "#ff8800", "file": uni_ase})
    await step("add_frame", {"file": uni_ase})
    await step("add_frame", {"file": uni_ase})  # 3 frames total
    await step("create_tag", {"name": "walk", "from_frame": 1, "to_frame": 3, "file": uni_ase})
    await step("list_tags", {"file": uni_ase})
    await step("delete_tag", {"name": "walk", "file": uni_ase})
    uni_res = await step("export_unity_sprite", {"png_path": uni_png, "pixels_per_unit": 16, "file": uni_ase})
    try:
        u = json.loads(_text(uni_res))
        xs = [sp["x"] for sp in u["sprites"]]
        ok = u["frames"] == 3 and xs == [0, 16, 32] and u["png_exists"] and os.path.isfile(u["meta"])
        if not ok:
            failures.append(("export_unity_sprite", f"frames={u.get('frames')} xs={xs} meta={os.path.isfile(u.get('meta',''))}"))
        else:
            with open(u["meta"], encoding="utf-8") as mf:
                mtext = mf.read()
            if "spriteMode: 2" not in mtext or mtext.count("name: uni_") < 3:
                failures.append(("export_unity_sprite", "meta missing spriteMode:2 or sprite names"))
            else:
                try:
                    import yaml  # optional
                    yaml.safe_load(mtext)
                    print(f"  unity export: 3 sprites sliced, rects {xs}, .meta valid YAML")
                except ImportError:
                    print(f"  unity export: 3 sprites sliced, rects {xs}, .meta structure ok (PyYAML absent)")
    except Exception as e:
        failures.append(("export_unity_sprite", f"parse failed: {e}"))

    # --- cel ops ---
    cel_ase = os.path.join(d, "cel.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": cel_ase})
    await step("draw_rectangle", {"x": 0, "y": 0, "width": 8, "height": 8, "color": "#ffffff", "file": cel_ase})
    await step("set_cel_position", {"x": 2, "y": 2, "file": cel_ase})
    await step("set_cel_opacity", {"opacity": 128, "file": cel_ase})
    await step("clear_cel", {"file": cel_ase})

    # --- differentiator: index-adjacency palette ramp-walk ---
    ramp_ase = os.path.join(d, "ramp.aseprite")
    ramp = ["#202020", "#606060", "#a0a0a0", "#e0e0e0"]  # dark -> light ramp
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": ramp_ase})
    await step("set_palette", {"colors": ramp, "file": ramp_ase})
    await step("draw_rectangle", {"x": 0, "y": 0, "width": 8, "height": 8, "color": "#606060", "file": ramp_ase})
    await step("palette_ramp_walk", {"x": 0, "y": 0, "width": 8, "height": 8, "light_direction": "top_left", "steps": 2, "file": ramp_ase})
    tl = await step("get_pixel", {"x": 0, "y": 0, "file": ramp_ase})
    br = await step("get_pixel", {"x": 7, "y": 7, "file": ramp_ase})
    try:
        tl_c = json.loads(_text(tl))["color"][:7]
        br_c = json.loads(_text(br))["color"][:7]
        if tl_c != "#e0e0e0" or br_c != "#202020":
            failures.append(("palette_ramp_walk", f"TL={tl_c} (want #e0e0e0), BR={br_c} (want #202020)"))
        else:
            print(f"  ramp-walk: lit corner {tl_c} (lightest idx), shadow corner {br_c} (darkest idx) — correct")
    except Exception as e:
        failures.append(("palette_ramp_walk", f"parse failed: {e}"))
    await step("apply_shading", {"x": 0, "y": 0, "width": 8, "height": 8, "light_direction": "right", "intensity": 0.6, "file": ramp_ase})

    # --- tween (parity) + smear (stretch) ---
    tw_ase = os.path.join(d, "tween.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": tw_ase})
    await step("draw_rectangle", {"x": 0, "y": 0, "width": 2, "height": 2, "color": "#ffffff", "file": tw_ase})
    await step("duplicate_frame", {"number": 1, "file": tw_ase})
    await step("set_cel_position", {"x": 6, "y": 6, "frame": 2, "file": tw_ase})
    await step("tween_frames", {"from_frame": 1, "to_frame": 2, "count": 1, "file": tw_ase})
    tw = await step("run_lua", {"code": "local c=app.activeLayer:cel(2); return J({x=c.position.x, y=c.position.y})", "file": tw_ase})
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
    await step("draw_rectangle", {"x": 0, "y": 0, "width": 4, "height": 4, "color": "#ffffff", "file": sm_ase})
    await step("duplicate_frame", {"number": 1, "file": sm_ase})
    await step("set_cel_position", {"x": 4, "y": 4, "frame": 2, "file": sm_ase})
    await step("smear_frame", {"from_frame": 1, "to_frame": 2, "file": sm_ase})
    sm = await step("run_lua", {"code": "local s=app.activeSprite; local img=Image(s.width,s.height,ColorMode.RGB); img:drawSprite(s,3); return J({a11=app.pixelColor.rgbaA(img:getPixel(1,1)), a55=app.pixelColor.rgbaA(img:getPixel(5,5))})", "file": sm_ase})
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
    boxres = await step("draw_iso_box", {"center_x": 48, "center_y": 60, "half_width": 30, "height": 34, "color": "#8a94a0", "file": iso_ase})
    try:
        se = json.loads(_text(boxres))["face_se"]
        await step("iso_recessed_panel", {"points": se, "file": iso_ase})
        print("  iso box drawn; recessed port stamped on returned SE face")
    except Exception as e:
        failures.append(("draw_iso_box/iso_recessed_panel", f"{e}"))
    await step("draw_iso_cylinder", {"center_x": 40, "top_y": 18, "radius": 7, "height": 18, "color": "#b07850", "file": iso_ase})
    await step("fill_polygon", {"points": [[8, 10], [30, 14], [26, 30], [6, 26]], "color": "#40c080", "file": iso_ase})
    await step("export_sprite", {"out_path": os.path.join(d, "iso.png"), "file": iso_ase})

    # --- parity additions: draw / color / transform ---
    add_ase = os.path.join(d, "add.aseprite")
    await step("create_sprite", {"width": 32, "height": 32, "color_mode": "rgb", "file": add_ase})
    await step("draw_ellipse", {"center_x": 16, "center_y": 16, "radius_x": 10, "radius_y": 6, "color": "#ff00ff", "fill": True, "file": add_ase})
    await step("draw_gradient", {"x": 0, "y": 0, "width": 32, "height": 8, "color1": "#000000", "color2": "#ffffff", "direction": "horizontal", "dither": True, "file": add_ase})
    await step("apply_dither", {"x": 0, "y": 24, "width": 32, "height": 8, "color1": "#101020", "color2": "#3040a0", "density": 0.5, "file": add_ase})
    await step("add_outline", {"color": "#000000", "diagonal": False, "file": add_ase})
    await step("replace_color", {"from_color": "#ff00ff", "to_color": "#00ffcc", "tolerance": 0, "file": add_ase})
    await step("adjust_hsl", {"hue_shift": 40, "saturation": 1.1, "lightness": 0.05, "file": add_ase})
    await step("get_color_stats", {"top": 5, "file": add_ase})
    await step("rotate_sprite", {"degrees": 90, "file": add_ase})
    await step("generate_color_ramp", {"base_color": "#3060c0", "count": 5, "hue_shift": True, "file": add_ase})
    await step("quantize_to_palette", {"file": add_ase})

    # --- layer parity ---
    ly_ase = os.path.join(d, "layers.aseprite")
    await step("create_sprite", {"width": 16, "height": 16, "color_mode": "rgb", "file": ly_ase})
    await step("draw_rectangle", {"x": 0, "y": 0, "width": 16, "height": 16, "color": "#804020", "file": ly_ase})
    await step("add_layer", {"name": "top", "file": ly_ase})
    await step("set_layer_blend_mode", {"name": "top", "mode": "multiply", "file": ly_ase})
    await step("duplicate_layer", {"name": "top", "file": ly_ase})
    await step("move_layer", {"name": "top", "direction": "top", "file": ly_ase})
    await step("merge_layer_down", {"name": "top", "file": ly_ase})  # top has a layer beneath -> valid
    await step("import_image_as_layer", {"image_path": os.path.join(d, "iso.png"), "layer_name": "ref", "x": 0, "y": 0, "file": ly_ase})

    # --- extract palette from an external PNG ---
    ep_ase = os.path.join(d, "extract.aseprite")
    await step("create_sprite", {"width": 8, "height": 8, "color_mode": "rgb", "file": ep_ase})
    ep_res = await step("extract_palette_from_image", {"image_path": os.path.join(d, "iso.png"), "max_colors": 8, "replace": True, "file": ep_ase})
    try:
        ep = json.loads(_text(ep_res))
        if ep.get("count", 0) < 2:
            failures.append(("extract_palette_from_image", f"expected >=2 colors, got {ep.get('count')}"))
        else:
            print(f"  extract palette: {ep['count']} colors from iso.png")
    except Exception as e:
        failures.append(("extract_palette_from_image", f"parse failed: {e}"))

    # --- regression: replace_color must PRESERVE source alpha for an #rrggbb target ---
    ra_ase = os.path.join(d, "replace_alpha.aseprite")
    await step("create_sprite", {"width": 4, "height": 4, "color_mode": "rgb", "file": ra_ase})
    await step("draw_rectangle", {"x": 0, "y": 0, "width": 4, "height": 4, "color": "#00ff0080", "file": ra_ase})  # alpha 128
    await step("replace_color", {"from_color": "#00ff00", "to_color": "#0000ff", "tolerance": 0, "file": ra_ase})  # no alpha given
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
    await step("draw_rectangle", {"x": 4, "y": 2, "width": 8, "height": 8, "color": "#ffcc00", "file": sl_ase})
    await step("create_slice", {"name": "gizmo", "x": 4, "y": 2, "width": 8, "height": 8, "file": sl_ase})
    await step("set_slice_pivot", {"name": "gizmo", "pivot_x": 4, "pivot_y": 8, "file": sl_ase})
    await step("set_slice_center", {"name": "gizmo", "x": 2, "y": 2, "width": 4, "height": 4, "file": sl_ase})
    await step("list_slices", {"file": sl_ase})
    sl_res = await step("export_unity_slices", {"png_path": sl_png, "pixels_per_unit": 16, "file": sl_ase})
    try:
        su = json.loads(_text(sl_res))
        sp = su["sprites"][0]
        # slice top-left (4,2) size 8x8 in a 16-tall texture -> Unity y = 16-(2+8) = 6
        # pivot (4,8) px -> Unity (0.5, 0.0)
        ok = sp["y"] == 6 and sp["x"] == 4 and abs(sp["pivot"][0] - 0.5) < 1e-6 and abs(sp["pivot"][1] - 0.0) < 1e-6
        if not ok:
            failures.append(("export_unity_slices", f"expected y=6 x=4 pivot[0.5,0.0], got x={sp['x']} y={sp['y']} pivot={sp['pivot']}"))
        else:
            print(f"  unity slices: '{sp['name']}' rect y-flipped to {sp['y']}, pivot {sp['pivot']} — correct")
    except Exception as e:
        failures.append(("export_unity_slices", f"parse failed: {e}"))
    # regression: a YAML-unsafe slice name must be quoted in the .meta (valid YAML)
    await step("create_slice", {"name": "turret: base", "x": 0, "y": 0, "width": 4, "height": 4, "file": sl_ase})
    yq_res = await step("export_unity_slices", {"png_path": os.path.join(d, "slices2.png"), "pixels_per_unit": 16, "file": sl_ase})
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
        await step("draw_rectangle", {"x": 2, "y": 2, "width": 12, "height": 12, "color": "#3388cc", "file": bf})
    bx = await step("batch_export", {"folder": bdir, "out_dir": bout, "format": "png", "scale": 2})
    try:
        b = json.loads(_text(bx))
        pngs = glob.glob(os.path.join(bout, "*.png"))
        if b.get("succeeded") != 3 or len(pngs) != 3:
            failures.append(("batch_export", f"expected 3 PNGs, got succeeded={b.get('succeeded')} files={len(pngs)}"))
        else:
            print(f"  batch_export: 3/3 sprites -> {len(pngs)} PNGs at 2x")
    except Exception as e:
        failures.append(("batch_export", f"parse failed: {e}"))
    await step("batch_resize", {"folder": bdir, "out_dir": os.path.join(d, "batchrs"), "scale": 1.5})
    bp = await step("batch_apply_palette", {"folder": bdir, "out_dir": os.path.join(d, "batchpal"), "preset": "gameboy"})
    try:
        bpr = json.loads(_text(bp))
        if bpr.get("succeeded") != 3:
            failures.append(("batch_apply_palette", f"expected 3 succeeded, got {bpr.get('succeeded')}"))
        else:
            print("  batch_apply_palette: 3/3 sprites palette-locked to gameboy")
    except Exception as e:
        failures.append(("batch_apply_palette", f"parse failed: {e}"))

    # --- MCP resources read back the cached QA + export state ---
    async def read_res(uri):
        try:
            contents = await mcp.read_resource(uri)
            parts = list(contents) if not isinstance(contents, (str, bytes)) else [contents]
            txt = " ".join(getattr(p, "content", getattr(p, "text", str(p))) if not isinstance(p, (str, bytes)) else str(p) for p in parts)
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

    # --- MCP prompt renders its guidance ---
    try:
        pr = await mcp.get_prompt("unity_qa_gate", {"expected_size": "64x64", "grid": "16", "max_colors": "16"})
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
    print(f"SMOKE OK — all steps passed. frames->{sorted(os.path.basename(p) for p in produced)}, sheet={sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
