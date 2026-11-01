"""The cool extras: pose and timing maths, stray finding, GIF, atlases, and the journal."""

from __future__ import annotations

import struct

import pytest

from aseprite_claude_connector.lua import CHANGES_MARK, build_lua
from aseprite_claude_connector.raster import Raster, encode_gif, remap, strip
from aseprite_claude_connector.tools import _common
from aseprite_claude_connector.tools.atlas import build_atlas, gamemaker_strips, pack_shelves
from aseprite_claude_connector.tools.cleanup import marked, stray_report
from aseprite_claude_connector.tools.motion import (
    GAITS,
    foot_path,
    loop_verdict,
    timing_durations,
    walk_segments,
)
from aseprite_claude_connector.tools.session_tools import (
    EXPLANATIONS,
    explanation,
    frame_ranges,
    pad_to_largest,
    summarize,
)


def raster(rows: list[str], colors: dict[str, tuple]) -> Raster:
    data = bytearray()
    for row in rows:
        for ch in row:
            data += bytes(colors.get(ch, (0, 0, 0, 0)))
    return Raster(len(rows[0]), len(rows), bytes(data))


RED, BLUE = (200, 0, 0, 255), (0, 0, 200, 255)


@pytest.mark.parametrize("gait", ["walk", "run"])
def test_a_foot_on_the_ground_travels_backward(gait):
    g = GAITS[gait]
    steps = [i / 100 * g["stance"] for i in range(100)]
    xs = [foot_path(p, g, 10, 4) for p in steps]
    assert all(y == 0 for _, y in xs)
    assert all(a[0] > b[0] for a, b in zip(xs, xs[1:], strict=False))


@pytest.mark.parametrize("gait", ["walk", "run"])
def test_a_foot_in_the_air_swings_forward_and_lands_where_it_starts(gait):
    g = GAITS[gait]
    n = 100
    path = [foot_path(g["stance"] + (1 - g["stance"]) * i / n, g, 10, 4) for i in range(n + 1)]
    assert all(b[0] >= a[0] for a, b in zip(path, path[1:], strict=False))
    assert max(y for _, y in path) == pytest.approx(4, abs=0.01)
    assert path[-1][0] == pytest.approx(foot_path(0, g, 10, 4)[0])


@pytest.mark.parametrize("facing", [1, -1])
@pytest.mark.parametrize("gait", ["walk", "run"])
def test_the_skeleton_walks_the_way_it_faces(gait, facing):
    frames = walk_segments(48, 8, gait, facing)
    assert len(frames) == 8
    # the near foot is the end of the second near line; toes point where the figure faces
    feet = [[s for s in lines if s[4] == "near"][1][2:4] for lines in frames]
    toes = [[s for s in lines if s[4] == "near"][2] for lines in frames]
    assert all((t[2] - t[0]) * facing > 0 for t in toes)
    assert max(y for _, y in feet) == 0  # stands on the ground, never below it
    grounded = [x for x, y in feet if y == 0]
    assert grounded == sorted(grounded, key=lambda x: -x * facing)


def test_the_two_feet_are_half_a_cycle_apart():
    frames = walk_segments(48, 8, "walk", 1)
    near = [[s for s in lines if s[4] == "near"][1][2:4] for lines in frames]
    far = [[s for s in lines if s[4] == "far"][1][2:4] for lines in frames]
    assert near[0] == far[4]


def test_timing_presets_shape_the_durations():
    assert timing_durations("ease_in", 4, 50, 3) == sorted(
        timing_durations("ease_in", 4, 50, 3), reverse=True
    )
    assert timing_durations("ease_out", 4, 50, 3) == sorted(timing_durations("ease_out", 4, 50, 3))
    assert timing_durations("hold", 3, 50, 4) == [50, 50, 200]
    assert timing_durations("ease_in_out", 3, 50, 3) == [150, 50, 150]
    assert timing_durations("bounce", 3, 50, 3) == [50, 150, 50]
    assert timing_durations("bounce", 1, 50, 3) == [50]


@pytest.mark.parametrize(
    "seam,steps,direction,verdict",
    [
        (100, [90, 110, 100], "forward", "smooth"),
        (900, [90, 110, 100], "forward", "jump"),
        (0, [90, 110], "forward", "duplicate"),
        (0, [0, 0], "forward", "static"),
        (900, [90], "pingpong", "pingpong"),
    ],
)
def test_loop_verdicts(seam, steps, direction, verdict):
    assert loop_verdict(seam, steps, direction)["verdict"] == verdict


def test_stray_report_tells_the_kinds_apart():
    src = raster(
        [
            "RRRR.....",
            "RBRR...R.",
            "RRRR.....",
        ],
        {"R": RED, "B": BLUE},
    )
    report = stray_report(src, rare=1, near=0)
    assert report["isolated"] == [(7, 1)]
    assert report["orphans"] == [(1, 1)]
    assert report["rare_colors"] == ["#0000c8"]
    assert report["rare_pixels"] == [(1, 1)]
    picture = marked(src, report)
    assert picture.rgba[(1 * 9 + 7) * 4 : (1 * 9 + 7) * 4 + 3] == bytes((255, 60, 60))


def test_near_duplicates_point_at_the_commoner_color():
    src = raster(["AAAAAAAAB"], {"A": (100, 100, 100, 255), "B": (104, 100, 100, 255)})
    found = stray_report(src, rare=0, near=8)["near_duplicates"]
    assert found == [{"color": "#686464", "count": 1, "close_to": "#646464"}]


def test_remap_keeps_alpha_and_leaves_other_colors():
    src = raster(["AB."], {"A": (10, 20, 30, 128), "B": (1, 2, 3, 255)})
    out = remap(src, {(10, 20, 30): (9, 9, 9)})
    assert out.rgba[:8] == bytes((9, 9, 9, 128, 1, 2, 3, 255))


def test_strip_lays_frames_side_by_side():
    a = raster(["A"], {"A": RED})
    b = raster(["B"], {"B": BLUE})
    assert strip([a, b]).rgba == a.rgba + b.rgba


def _gif_frames(data: bytes) -> tuple[int, int, list[list[int]]]:
    """A small GIF decoder, so the encoder is checked against the format itself."""
    assert data[:6] == b"GIF89a"
    w, h, flags = struct.unpack("<HHB", data[6:11])
    pos = 13 + 3 * (1 << ((flags & 7) + 1))
    frames = []
    while data[pos] != 0x3B:
        if data[pos] == 0x21:
            pos += 2
            while data[pos]:
                pos += data[pos] + 1
            pos += 1
            continue
        assert data[pos] == 0x2C
        pos += 10
        min_code = data[pos]
        pos += 1
        blob = bytearray()
        while data[pos]:
            blob += data[pos + 1 : pos + 1 + data[pos]]
            pos += data[pos] + 1
        pos += 1
        frames.append(_lzw_decode(bytes(blob), min_code))
    return w, h, frames


def _lzw_decode(blob: bytes, min_code: int) -> list[int]:
    clear, stop = 1 << min_code, (1 << min_code) + 1
    bits = int.from_bytes(blob, "little")
    at, width, out, table, prev = 0, min_code + 1, [], {}, None
    while True:
        code = (bits >> at) & ((1 << width) - 1)
        at += width
        if code == clear:
            table = {i: [i] for i in range(clear)}
            width, prev = min_code + 1, None
            continue
        if code == stop:
            return out
        if prev is None:
            entry = table[code]
        else:
            entry = table[code] if code in table else prev + prev[:1]
            table[len(table) + 2] = prev + entry[:1]
        out += entry
        prev = entry
        if len(table) + 2 == (1 << width) - 1 + 1 and width < 12 and prev is not None:
            width += 1


def test_gif_round_trips_through_a_decoder():
    a = raster(["ABAB", "BBAA"], {"A": (1, 2, 3, 255), "B": (4, 5, 6, 255)})
    b = raster(["BBBB", "AAAA"], {"A": (1, 2, 3, 255), "B": (4, 5, 6, 255)})
    w, h, frames = _gif_frames(encode_gif([a, b], 100))
    assert (w, h) == (4, 2)
    assert frames == [[0, 1, 0, 1, 1, 1, 0, 0], [1, 1, 1, 1, 0, 0, 0, 0]]


def test_gif_table_reset_survives_a_long_noisy_frame():
    pixels = bytearray()
    for i in range(20000):
        v = (i * i * 2654435761 >> 7) % 200
        pixels += bytes((v, v, v, 255))
    frame = Raster(200, 100, bytes(pixels))
    _, _, frames = _gif_frames(encode_gif([frame], 100))
    assert len(frames[0]) == 20000


def test_gif_over_256_colors_falls_back_to_the_cube():
    pixels = bytearray()
    for i in range(400):
        pixels += bytes((i % 256, i // 2 % 256, 255 - i % 256, 255))
    data = encode_gif([Raster(20, 20, bytes(pixels))], 100)
    assert len(_gif_frames(data)[2][0]) == 400


def test_gamemaker_strip_names_carry_the_frame_count():
    tags = [{"name": "walk left", "from": 1, "to": 4}, {"name": "idle", "from": 5, "to": 6}]
    strips = gamemaker_strips("hero", [100, 100, 100, 100, 200, 100], tags)
    assert [s["file"] for s in strips] == ["hero_walk_left_strip4.png", "hero_idle_strip2.png"]
    assert strips[0]["fps"] == 10 and strips[0]["even_timing"] is True
    assert strips[1]["even_timing"] is False
    assert gamemaker_strips("hero", [100, 100], [])[0]["file"] == "hero_strip2.png"


def test_shelf_packing_never_overlaps():
    sizes = [(8, 8), (16, 4), (4, 12), (8, 8), (20, 3)]
    width, height, places = pack_shelves(sizes, 1)
    boxes = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(places, sizes, strict=False)]
    assert all(b[2] <= width and b[3] <= height for b in boxes)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_atlas_shares_repeated_frames():
    a = raster(["AA"], {"A": RED})
    b = raster(["BB"], {"B": BLUE})
    sheets = [
        {"name": "x", "frames": [a, a], "durations": [100, 120], "tags": []},
        {
            "name": "y",
            "frames": [b],
            "durations": [90],
            "tags": [{"name": "t", "from": 1, "to": 1}],
        },
    ]
    atlas, data = build_atlas(sheets, "a.png", 1)
    assert data["frames"]["x 0"]["frame"] == data["frames"]["x 1"]["frame"]
    assert data["frames"]["x 1"]["duration"] == 120
    assert data["frames"]["y 0"]["frame"] != data["frames"]["x 0"]["frame"]
    assert data["meta"]["frameTags"][0]["name"] == "y/t"
    assert atlas.width * atlas.height * 4 == len(atlas.rgba)


def test_frame_ranges():
    assert frame_ranges([7, 1, 3, 2]) == "1-3, 7"
    assert frame_ranges([]) == ""


def test_summary_merges_repeats_on_a_layer():
    lines = summarize(
        [
            {"label": "Draw line", "frames": [1], "layers": ["ink"], "pixels": 4},
            {"label": "Draw line", "frames": [2], "layers": ["ink"], "pixels": 6},
            {"label": "Draw line", "frames": [2], "layers": ["paint"], "pixels": 1},
            {"label": "Fill"},
        ]
    )
    assert lines[0] == {
        "edit": "Draw line",
        "times": 2,
        "pixels": 10,
        "layers": ["ink"],
        "frames": "1-2",
    }
    assert [x["edit"] for x in lines] == ["Draw line", "Draw line", "Fill"]
    assert lines[2]["frames"] is None


def test_explanations_cover_the_common_edits():
    assert "Shift+O" in EXPLANATIONS["Add outline"]
    assert "No single" in explanation("Something unusual")


def test_journal_report_is_split_from_the_result():
    report = '{"frames":[1],"layers":["a"],"pixels":3}'
    changes, rest = _common._split_changes(f'{CHANGES_MARK}{report}{CHANGES_MARK}{{"ok":true}}')
    assert changes == {"frames": [1], "layers": ["a"], "pixels": 3}
    assert rest == '{"ok":true}'
    assert _common._split_changes('{"ok":true}') == (None, '{"ok":true}')
    assert _common._split_changes(None) == (None, None)


def test_only_railed_edits_carry_the_report():
    assert "CHANGES_MARK" in build_lua("return 1", mutates=True, max_pixels=10)
    assert "CHANGES_MARK" not in build_lua("return 1", mutates=True)


def test_pad_to_largest_centers_smaller_pictures():
    small = raster(["A"], {"A": RED})
    big = raster(["BBB", "BBB", "BBB"], {"B": BLUE})
    out = pad_to_largest([small, big])
    assert (out[0].width, out[0].height) == (3, 3)
    assert out[0].rgba[(1 * 3 + 1) * 4 : (1 * 3 + 1) * 4 + 4] == bytes(RED)
