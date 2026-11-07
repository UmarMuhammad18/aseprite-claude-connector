"""Making characters act, and keeping a cast consistent.

- ``draw_eyes`` — eyes redrawn per frame: where they look, blinks, lids, brows,
  smiles. The quickest way to give a pose an expression.
- ``swing_part`` — a wing, arm or tail cut out by an outline and swung about its
  joint across frames, with no gaps where it meets the body.
- ``bob_body`` — breathing, hops and sways: the body above the feet moves, the feet
  stay planted.
- ``lift_symbols`` — floating "!", "?", Zzz or hearts moved to their own layer and
  animated there.
- ``check_consistency`` / ``match_palettes`` — near-duplicate colours and size
  differences across sprites found, and merged onto one palette.

The keyed tools take ``keys``, one per frame, and make any frames that don't exist
yet (copies of the last one), so a whole animation is one call; a tag that ended on
the last frame grows to cover them. Each works on the
frame's current pixels, so they stack: bob the body, then swing the wings, then draw
the eyes. The image work is in ``character.py``; pixels travel inside the script.
"""

from __future__ import annotations

from collections import Counter

from mcp.types import ToolAnnotations

from ..backends import get_backend
from ..character import (
    Grid,
    bobbed,
    drawn_eye,
    eye_style,
    free_pixels,
    merged_palette,
    over,
    swung,
    taken,
)
from ..lua import lua_locals
from ._common import ToolError, parse_color, run
from .scene import _FIND, _read, _strip, _target

_MAX_FRAMES = 256

_WRITE = """
local __last = #s.frames
local __grow = {}
for _, tg in ipairs(s.tags) do
  if tg.toFrame.frameNumber == __last then __grow[#__grow + 1] = tg end
end
while #s.frames < MAXF do s:newFrame(#s.frames) end
for _, tg in ipairs(__grow) do tg.toFrame = s.frames[#s.frames] end
local done, i = {}, 0
for n in FRAMES:gmatch("%d+") do
  n = tonumber(n)
  s:newCel(layer, n, Image(strip, Rectangle(i * W, 0, W, H)), Point(0, 0))
  done[#done + 1] = n
  i = i + 1
end
for f, ms in DURS:gmatch("(%d+):(%d+)") do
  s.frames[tonumber(f)].duration = tonumber(ms) / 1000
end
return J({ layer = layer.name, frames = done, total = #s.frames })
"""

_LIFT = """
for f = 1, EXISTING do
  s:newCel(layer, f, Image(strip, Rectangle((f - 1) * W, H, W, H)), Point(0, 0))
end
local __last = #s.frames
local __grow = {}
for _, tg in ipairs(s.tags) do
  if tg.toFrame.frameNumber == __last then __grow[#__grow + 1] = tg end
end
while #s.frames < TOTAL do s:newFrame(#s.frames) end
for _, tg in ipairs(__grow) do tg.toFrame = s.frames[#s.frames] end
local fx = s:newLayer()
fx.name = NAME
fx.parent = layer.parent
fx.stackIndex = layer.stackIndex + 1
for f = 1, TOTAL do
  s:newCel(fx, f, Image(strip, Rectangle((f - 1) * W, 0, W, H)), Point(0, 0))
end
for f, ms in DURS:gmatch("(%d+):(%d+)") do
  s.frames[tonumber(f)].duration = tonumber(ms) / 1000
end
app.activeLayer = layer  -- later tools should keep working on the character
return J({ layer = fx.name, frames = TOTAL, from_layer = layer.name })
"""

# Colours in use per sprite, and how tall its subject stands on frame 1.
_STATS_FN = """
local pc = app.pixelColor
local function stats(sp)
  if sp.colorMode ~= ColorMode.RGB then return { rgb = false } end
  local counts = {}
  for _, c in ipairs(sp.cels) do
    for it in c.image:pixels() do
      local v = it()
      if pc.rgbaA(v) > 0 then
        local k = string.format("%02x%02x%02x", pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v))
        counts[k] = (counts[k] or 0) + 1
      end
    end
  end
  local top, bottom, left, right = math.huge, -1, math.huge, -1
  for _, c in ipairs(sp.cels) do
    if c.frameNumber == 1 and c.layer.isVisible then
      local img, p = c.image, c.position
      for it in img:pixels() do
        if pc.rgbaA(it()) > 0 then
          local x, y = it.x + p.x, it.y + p.y
          if y < top then top = y end
          if y > bottom then bottom = y end
          if x < left then left = x end
          if x > right then right = x end
        end
      end
    end
  end
  local name = sp.filename ~= "" and app.fs.fileName(sp.filename) or "(unsaved)"
  if #sp.tags > 0 and app.fs.fileExtension(sp.filename) == "" then name = sp.tags[1].name end
  local tags = {}
  for _, tg in ipairs(sp.tags) do tags[#tags + 1] = tg.name end
  return { rgb = true, name = name, file = app.fs.fileName(sp.filename), tags = tags,
    colors = counts, width = sp.width, height = sp.height,
    subject = bottom >= 0 and { width = right - left + 1, height = bottom - top + 1 } or nil }
end
"""

_STATS_ALL = (
    _STATS_FN
    + """
local out = {}
for i, sp in ipairs(app.sprites) do out[i] = stats(sp) end
return J(out)
"""
)

_STATS_ONE = (
    _STATS_FN
    + """
return J({ stats(app.activeSprite) })
"""
)

_ACTIVATE = """
app.activeSprite = app.sprites[INDEX]
return 1
"""

_REMAP = """
local pc = app.pixelColor
local map = {}
for a, b in MAP:gmatch("(%x+):(%x+)") do map[tonumber(a, 16)] = tonumber(b, 16) end
local s = app.activeSprite
local changed = 0
for _, c in ipairs(s.cels) do
  local img = c.image:clone()
  local hit = false
  for it in img:pixels() do
    local v = it()
    local a = pc.rgbaA(v)
    if a > 0 then
      local to = map[pc.rgbaR(v) * 65536 + pc.rgbaG(v) * 256 + pc.rgbaB(v)]
      if to then
        it(pc.rgba(to // 65536, (to // 256) % 256, to % 256, a))
        hit = true
        changed = changed + 1
      end
    end
  end
  if hit then c.image = img end
end
return J({ pixels = changed })
"""


def _hex(c) -> str:
    return "#" + bytes(c[:3]).hex()


def _rgba(c: str) -> tuple[int, int, int, int]:
    return (*parse_color(c)[:3], 255)


def _keys(keys: list[dict] | None, active: int) -> list[dict]:
    keys = keys or [{"frame": active}]
    seen = set()
    for k in keys:
        f = k.get("frame")
        if not isinstance(f, int) or not 1 <= f <= _MAX_FRAMES:
            raise ToolError(f"each key needs a frame 1..{_MAX_FRAMES}: {k}")
        if f in seen:
            raise ToolError(f"frame {f} has two keys")
        seen.add(f)
        ms = k.get("ms")
        if ms is not None and not (isinstance(ms, int) and 1 <= ms <= 65535):
            raise ToolError(f"ms must be a whole number of milliseconds: {k}")
    return sorted(keys, key=lambda k: k["frame"])


def _sources(layer: str, keys: list[dict], file: str | None) -> dict[int, Grid]:
    """Each keyed frame's current pixels; frames that don't exist yet start as the
    last frame, the copy they'll be made from."""
    count = int(run("return #app.activeSprite.frames", file=file))
    cache: dict[int, Grid] = {}
    out = {}
    for k in keys:
        src = min(k["frame"], count)
        if src not in cache:
            cache[src] = Grid.of(_read(layer, src, file)[0])
        out[k["frame"]] = cache[src].copy()
    return out


def _write(
    layer: str, made: dict[int, Grid], keys: list[dict], label: str, file: str | None
) -> dict:
    frames = sorted(made)
    first = made[frames[0]]
    body = (
        _pixels(_strip([made[f].raster() for f in frames]))
        + lua_locals(
            LAYER=layer,
            W=first.w,
            H=first.h,
            MAXF=frames[-1],
            FRAMES=",".join(map(str, frames)),
            DURS=",".join(f"{k['frame']}:{k['ms']}" for k in keys if k.get("ms")),
        )
        + _FIND
        + _WRITE
    )
    return run(body, mutates=True, undo_label=label, file=file)


def _pixels(r):
    from .look import pixels_loader

    return pixels_loader(r)


def _point(p, what: str) -> tuple[float, float]:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise ToolError(f"{what} must be [x, y]")
    return float(p[0]), float(p[1])


def _sprite_stats(files: list[str] | None, only: list[str] | None) -> list[tuple[int, dict]]:
    """(index in app.sprites, stats) for each sprite compared."""
    if files:
        out = []
        for n, f in enumerate(files, start=1):
            out += [(n, s) for s in run(_STATS_ONE, file=f)]
        return out
    if get_backend().name != "live":
        raise ToolError("headless: pass files, the sprites to compare")
    stats = list(enumerate(run(_STATS_ALL, follow_pin=False), start=1))
    if only:
        wanted = set(only)
        stats = [
            (i, s)
            for i, s in stats
            if wanted & {s.get("name"), s.get("file"), *(s.get("tags") or [])}
        ]
    return stats


def _counts(stats: list[dict]) -> list[Counter]:
    return [
        Counter({tuple(bytes.fromhex(k)): n for k, n in (s.get("colors") or {}).items()})
        for s in stats
    ]


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Draw eyes with an expression"))
    def draw_eyes(
        eyes: list[dict],
        keys: list[dict] | None = None,
        layer: str | None = None,
        style: dict | None = None,
        file: str | None = None,
    ) -> dict:
        """Redraw a character's eyes, frame by frame, to give it an expression:
        where it looks, blinks, sleepy or angry lids, a smile. ``eyes`` lists each
        eye's socket, the area INSIDE its ring, in canvas pixels: ``{"x": 44, "y":
        27.5, "rx": 6.5, "ry": 6.3}``, optionally ``"pupil": [rx, ry]`` (about half
        the socket by default), ``"look_scale"`` (0.7 for a far eye in a 3/4 view) and
        ``"inner": "left"|"right"`` (the side toward the beak or nose, for brows).
        Measure sockets with ``look`` first. ``keys``, one per frame (frames are made
        as needed): ``{"frame": 1, "look": [dx, dy], "lid": 0..1, "arc": 0..1,
        "brow": -0.6..0.6, "smile": 0..0.6, "closed": false, "ms": 120}``. ``lid``
        lowers the upper lid; ``arc`` curves it (relaxed, happy); ``brow`` > 0 slants
        it down toward the inner side (angry, focused), < 0 the other way (worried,
        sad); ``smile`` pushes up a lower lid; ``closed`` shuts the eye. Expression is
        easy to misread: when unsure, draw 3-4 options and ask. Colours come from the
        eyes already there; pass the returned ``style`` back on every sprite of the
        same character so all its eyes match. The area round each eye is repainted
        in skin colour. One undo step. Headless: pass ``file``."""
        if not eyes:
            raise ToolError("give at least one eye")
        layer, active = _target(layer, file)
        keys = _keys(keys, active)
        sockets = []
        for e in eyes:
            try:
                sockets.append((float(e["x"]), float(e["y"]), float(e["rx"]), float(e["ry"])))
            except (KeyError, TypeError, ValueError):
                raise ToolError(f"each eye needs x, y, rx, ry: {e}") from None
            if sockets[-1][2] < 1.5 or sockets[-1][3] < 1.5:
                raise ToolError("an eye socket must be at least 1.5 px in radius")
        mid = sum(s[0] for s in sockets) / len(sockets)
        inner = [
            e.get("inner") or ("right" if len(sockets) == 1 or s[0] < mid else "left")
            for e, s in zip(eyes, sockets, strict=True)
        ]
        made = _sources(layer, keys, file)
        first = made[keys[0]["frame"]]
        styles = []
        for s in sockets:
            found = eye_style(first, s)
            if style:
                found.update({k: _rgba(v) for k, v in style.items() if k in found})
            styles.append(found)
        for k in keys:
            lid, smile = float(k.get("lid", 0)), float(k.get("smile", 0))
            brow, arc = float(k.get("brow", 0)), float(k.get("arc", 0))
            if not (0 <= lid <= 1 and 0 <= smile <= 0.8 and 0 <= arc <= 1 and -1 <= brow <= 1):
                raise ToolError(f"lid and arc are 0..1, smile 0..0.8, brow -1..1: {k}")
            look = _point(k.get("look", [0, 0]), "look")
            for e, s, st, side in zip(eyes, sockets, styles, inner, strict=True):
                scale = float(e.get("look_scale", 1))
                size = e.get("pupil")
                pupil = None
                if size:
                    pupil = _point(size, "pupil")
                pscale = float(k.get("pupil_scale", 1))
                if pupil is None:
                    pupil = (max(1.2, s[2] * 0.5), max(1.5, s[3] * 0.62))
                pupil = (pupil[0] * pscale, pupil[1] * pscale)
                drawn_eye(
                    made[k["frame"]],
                    s,
                    st,
                    (look[0] * scale, look[1]),
                    pupil,
                    lid=lid,
                    arc=arc,
                    slant=brow * (1 if side == "right" else -1),
                    smile=smile,
                    closed=bool(k.get("closed", False)),
                    catch=2 if min(pupil) >= 2.2 else 1,
                )
        result = _write(layer, made, keys, "Draw eyes", file)
        shared = {k: _hex(v) for k, v in styles[0].items()}
        return {**result, "style": shared}

    @mcp.tool(annotations=ToolAnnotations(title="Swing a part about its joint"))
    def swing_part(
        outline: list[list[float]],
        pivot: list[float],
        keys: list[dict],
        layer: str | None = None,
        band: int = 3,
        shadow: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Swing a wing, arm, tail or ear about its joint across frames. ``outline``
        is a polygon round the part, in canvas pixels ``[[x, y], ...]``; keep it to
        the part itself (not the face or chest beside it). ``pivot`` is the joint.
        ``keys``, one per frame (frames are made as needed): ``{"frame": 2,
        "angle": 10, "dx": 0, "dy": -1, "ms": 90}``, angle in degrees clockwise.
        Where the part met the body, a ``band`` of ``shadow`` (the part's darkest
        colour by default) stays underneath, so turning never opens a gap, and the
        part's light outer halo is dropped so it doesn't streak. Small angles (up to
        about 15) look best. One undo step. Headless: pass ``file``."""
        if len(outline) < 3:
            raise ToolError("outline needs at least 3 points")
        points = [_point(p, "each outline point") for p in outline]
        joint = _point(pivot, "pivot")
        if not 0 <= band <= 8:
            raise ToolError("band must be 0..8")
        layer, active = _target(layer, file)
        keys = _keys(keys, active)
        made = _sources(layer, keys, file)
        shade = _rgba(shadow) if shadow else None
        for k in keys:
            made[k["frame"]] = swung(
                made[k["frame"]],
                points,
                joint,
                float(k.get("angle", 0)),
                float(k.get("dx", 0)),
                float(k.get("dy", 0)),
                band,
                shade,
            )
        return _write(layer, made, keys, "Swing part", file)

    @mcp.tool(annotations=ToolAnnotations(title="Bob the body, feet planted"))
    def bob_body(
        feet_y: int,
        keys: list[dict],
        layer: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Breathing, hops and sways: everything above the row ``feet_y`` moves while
        the feet below it stay planted. Put ``feet_y`` at the top of the feet.
        ``keys``, one per frame (frames are made as needed): ``{"frame": 1, "dy":
        -1, "dx": 0, "ms": 160}``; -1 rises a pixel (the legs stretch), +1 sinks.
        Breathing is 0/-1; a hop -2..-4; a sway dx -1/+1. One undo step. Headless:
        pass ``file``."""
        layer, active = _target(layer, file)
        keys = _keys(keys, active)
        made = _sources(layer, keys, file)
        for k in keys:
            dy, dx = int(k.get("dy", 0)), int(k.get("dx", 0))
            if abs(dy) > 16 or abs(dx) > 16:
                raise ToolError(f"dy and dx are -16..16: {k}")
            made[k["frame"]] = bobbed(made[k["frame"]], feet_y, dy, dx)
        return _write(layer, made, keys, "Bob body", file)

    @mcp.tool(annotations=ToolAnnotations(title="Lift symbols onto their own layer"))
    def lift_symbols(
        boxes: list[list[int]],
        keys: list[dict] | None = None,
        layer: str | None = None,
        name: str = "Effects",
        from_frame: int = 1,
        file: str | None = None,
    ) -> dict:
        """Move floating symbols ("!", "?", Zzz, hearts, sparkles) off a character's
        layer onto a new layer, and animate them there. ``boxes`` are ``[x, y, w, h]``
        round each symbol (or group); only pixels not joined to the body are taken,
        so a box can overlap a wing. They're found on ``from_frame`` and erased from
        every frame of ``layer``. ``keys``, one per frame (frames are made as
        needed): ``{"frame": 2, "symbols": [[dx, dy], null], "ms": 100}``, an offset
        per box, or null to hide it. Frames without a key show them in place. One
        undo step. Headless: pass ``file``."""
        if not boxes:
            raise ToolError("give at least one box")
        for b in boxes:
            if len(b) != 4 or b[2] < 1 or b[3] < 1:
                raise ToolError(f"each box is [x, y, w, h]: {b}")
        layer, active = _target(layer, file)
        keys = _keys(keys, active) if keys else []
        existing = int(run("return #app.activeSprite.frames", file=file))
        if not 1 <= from_frame <= existing:
            raise ToolError(f"from_frame must be 1..{existing}")
        src = Grid.of(_read(layer, from_frame, file)[0])
        work = src.copy()
        symbols = [taken(work, free_pixels(work, tuple(b))) for b in boxes]
        if not any(s.opaque(*p) for s in symbols for p in s.cells()):
            raise ToolError("no floating pixels in those boxes; check them with look")
        cleaned = []
        for f in range(1, existing + 1):
            g = Grid.of(_read(layer, f, file)[0]) if f != from_frame else src.copy()
            for sym in symbols:
                for x, y in sym.cells():
                    if sym.opaque(x, y) and g.get(x, y) == sym.get(x, y):
                        g.set(x, y, (0, 0, 0, 0))
            cleaned.append(g)
        total = max([existing] + [k["frame"] for k in keys])
        by_frame = {k["frame"]: k for k in keys}
        effects = []
        for f in range(1, total + 1):
            fx = Grid(src.w, src.h)
            spots = by_frame.get(f, {}).get("symbols")
            for i, sym in enumerate(symbols):
                spot = [0, 0] if spots is None or i >= len(spots) else spots[i]
                if spot is not None:
                    dx, dy = _point(spot, "each symbol offset")
                    over(fx, sym, int(dx), int(dy))
            effects.append(fx)
        blank = Grid(src.w, src.h)
        rows = [g.raster() for g in effects] + [g.raster() for g in cleaned]
        rows += [blank.raster()] * (total - existing)
        body = (
            _pixels(_strip(rows, rows=2))
            + lua_locals(
                LAYER=layer,
                W=src.w,
                H=src.h,
                EXISTING=existing,
                TOTAL=total,
                NAME=name,
                DURS=",".join(f"{k['frame']}:{k['ms']}" for k in keys if k.get("ms")),
            )
            + _FIND
            + _LIFT
        )
        return run(body, mutates=True, undo_label="Lift symbols", file=file)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Check a set of sprites for consistency", readOnlyHint=True
        )
    )
    def check_consistency(
        tolerance: float = 0.045, only: list[str] | None = None, files: list[str] | None = None
    ) -> dict:
        """Compare sprites of one character or set: the open sprites (live; ``only``
        picks them by filename or tag), or ``files``. Reports colours so close they should be one (the drift you get
        from pixelating poses separately), the colours only one sprite uses, and how
        tall the subject stands on frame 1 of each, so differences in scale show.
        Close colours every sprite uses side by side are shading steps, not drift.
        Poses lying down or crouching are shorter by nature. Fix colours with
        ``match_palettes``. Read-only."""
        rgb = [s for _, s in _sprite_stats(files, only) if s.get("rgb")]
        if len(rgb) < 2:
            raise ToolError("need at least two RGB sprites to compare")
        counts = _counts(rgb)
        _, groups = merged_palette(counts, tolerance)
        names = [s["name"] for s in rgb]
        drift = [
            {
                "keep": _hex(g["keep"]),
                "merge": [_hex(m) for m in g["merge"]],
                "in": [names[i] for i in g["sprites"]],
            }
            for g in groups
            if g["drift"] and len(g["sprites"]) > 1
        ]
        only = {}
        for i, c in enumerate(counts):
            others = Counter()
            for j, d in enumerate(counts):
                if j != i:
                    others.update(d)
            mine = [k for k in c if k not in others]
            if mine:
                only[names[i]] = [_hex(k) for k in mine][:24]
        heights = {s["name"]: (s.get("subject") or {}).get("height") for s in rgb}
        known = [h for h in heights.values() if h]
        return {
            "sprites": names,
            "near_duplicate_colors": drift,
            "colors_only_in_one_sprite": only,
            "subject_heights": heights,
            "height_spread": (max(known) - min(known)) if known else None,
            "verdict": "consistent"
            if not drift
            else f"{len(drift)} colour groups drift between sprites",
        }

    @mcp.tool(annotations=ToolAnnotations(title="Merge sprites onto one palette"))
    def match_palettes(
        tolerance: float = 0.045, only: list[str] | None = None, files: list[str] | None = None
    ) -> dict:
        """Put sprites of one character or set on one shared palette: colours closer
        than ``tolerance`` that stand in for each other (one sprite uses one, another
        sprite the other) merge into whichever is used most, across the open
        sprites (live; ``only`` picks them by filename or tag) or ``files``. Alpha is kept. One undo step per sprite. Check
        first with ``check_consistency``."""
        stats = [(i, s) for i, s in _sprite_stats(files, only) if s.get("rgb")]
        counts = _counts([s for _, s in stats])
        mapping, groups = merged_palette(counts, tolerance)
        if not mapping:
            return {"changed": [], "merged_groups": 0}
        table = ",".join(bytes(a).hex() + ":" + bytes(b).hex() for a, b in mapping.items())
        body = lua_locals(MAP=table) + _REMAP
        changed = []
        if files:
            for f in files:
                res = run(body, mutates=True, undo_label="Match palettes", file=f)
                changed.append({"sprite": f, **res})
        else:
            for i, s in stats:
                run(lua_locals(INDEX=i) + _ACTIVATE, follow_pin=False)
                res = run(body, mutates=True, undo_label="Match palettes", follow_pin=False)
                changed.append({"sprite": s["name"], **res})
        return {"changed": changed, "merged_groups": sum(1 for g in groups if g["drift"])}
