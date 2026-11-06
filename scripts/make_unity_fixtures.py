"""Write the files the Unity check imports: a sprite sheet with its sliced ``.meta``,
and an autotile set with its Rule Tile, made by the same code as the real exports.

Needs no Aseprite: the pictures are drawn here and the export files come from
``unity_export`` and ``tiles``. Also writes which sprite each painted cell should show,
for the check to compare. Usage: ``python scripts/make_unity_fixtures.py <folder>``.
"""

from __future__ import annotations

import json
import os
import sys

from aseprite_claude_connector.raster import Raster, encode_png
from aseprite_claude_connector.tiles import NE, NW, SE, SW, E, N, S, W, autotiles, blob_masks
from aseprite_claude_connector.tools.tiles import _unity_files
from aseprite_claude_connector.tools.unity_export import _gen_meta, _guid_for

FRAME, FRAMES, TILE = 16, 4, 16
# The block a map painter would paint, in Unity's cells (y runs up), plus a lone cell.
CELLS = [(x, y) for y in range(3) for x in range(4)] + [(6, 1)]


def _sheet() -> Raster:
    colours = [(200, 50, 50), (50, 200, 50), (50, 50, 200), (200, 200, 50)]
    rows = []
    for _ in range(FRAME):
        rows.append(b"".join(bytes((*c, 255)) * FRAME for c in colours))
    return Raster(FRAME * FRAMES, FRAME, b"".join(rows))


def _expected(masks: list[int]) -> list[dict]:
    painted = set(CELLS)
    out = []
    for x, y in CELLS:
        want = 0
        for bit, dx, dy in ((N, 0, 1), (E, 1, 0), (S, 0, -1), (W, -1, 0)):
            if (x + dx, y + dy) in painted:
                want |= bit
        for bit, dx, dy, a, b in (
            (NE, 1, 1, N, E),
            (SE, 1, -1, S, E),
            (SW, -1, -1, S, W),
            (NW, -1, 1, N, W),
        ):
            if (x + dx, y + dy) in painted and want & a and want & b:
                want |= bit
        out.append({"x": x, "y": y, "sprite": f"terrain_{masks.index(want)}"})
    return out


def main(folder: str) -> int:
    os.makedirs(folder, exist_ok=True)
    hero = os.path.join(folder, "hero.png")
    with open(hero, "wb") as f:
        f.write(encode_png(_sheet()))
    meta, _ = _gen_meta(_guid_for(hero + ".meta"), 100, FRAMES, FRAME, FRAME, "hero", 0.5, 0.5, 9)
    with open(hero + ".meta", "w", encoding="utf-8", newline="\n") as f:
        f.write(meta)

    fill = Raster(TILE, TILE, bytes((76, 154, 60, 255)) * (TILE * TILE))
    base = Raster(TILE, TILE, bytes((106, 74, 48, 255)) * (TILE * TILE))
    sheet, masks = autotiles(fill, TILE, base)
    assert masks == blob_masks()
    terrain = os.path.join(folder, "terrain.png")
    with open(terrain, "wb") as f:
        f.write(encode_png(sheet))
    _unity_files(folder, "terrain", terrain, TILE, masks, sheet.height // TILE)
    with open(os.path.join(folder, "terrain_expected.json"), "w", encoding="utf-8") as f:
        json.dump({"cells": _expected(masks)}, f, indent=1)
    print(f"wrote the Unity fixtures to {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
