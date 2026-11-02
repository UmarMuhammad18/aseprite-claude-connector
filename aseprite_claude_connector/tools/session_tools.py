"""Working alongside the artist: references, a change log, a timelapse, and lessons.

- ``add_reference_image`` — a sketch on a faded, locked guide layer.
- ``change_summary`` — what Claude changed this session, frame by frame.
- ``start_recording`` / ``stop_recording`` — the build as a GIF timelapse.
- ``explain_changes`` — the Aseprite tool or shortcut behind each recent edit.

The change log and recording live in this server process and reset when it restarts.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ..raster import Raster, blit, encode_gif, fit_factor, over_background, resized
from ._common import ToolError, after_edit, journal, rails, run
from .look import _snapshot, _take, image_loader

_MAX_RECORDED = 300

_REFERENCE = """
local s = app.activeSprite
if not s then error("no active sprite (create or open one first)") end
local img = load_image()
if not img then error("could not load image: " .. PATH) end
if FIT and (img.width > s.width or img.height > s.height) then
  local k = math.min(s.width / img.width, s.height / img.height)
  img:resize{ width = math.max(1, math.floor(img.width * k)),
              height = math.max(1, math.floor(img.height * k)) }
end
local keep = app.activeLayer
local l = s:newLayer()
l.name = NAME
l.opacity = OPACITY
local at = Point(math.floor((s.width - img.width) / 2), math.floor((s.height - img.height) / 2))
for _, f in ipairs(s.frames) do s:newCel(l, f, img, at) end
l.isEditable = false
if keep then app.activeLayer = keep end
return J({ layer = l.name, width = img.width, height = img.height, frames = #s.frames })
"""

# label -> how to do the same by hand. Shortcuts and menu paths are Aseprite's defaults,
# taken from its own gui.xml.
EXPLANATIONS = {
    "Draw pixels": "Pencil (B): click a pixel at a time.",
    "Draw line": "Line (L): drag from end to end. Hold Shift to snap the angle.",
    "Draw polyline": "Pencil (B): click a point, then Shift+click the next one to join them.",
    "Draw rectangle": "Rectangle (U, press again for filled): drag out the box.",
    "Draw circle": "Ellipse (Shift+U, press again for filled): drag, holding Shift for a circle.",
    "Draw ellipse": "Ellipse (Shift+U, press again for filled): drag out the shape.",
    "Draw gradient": "Gradient (Shift+G): drag across the area, using the two active colors.",
    "Fill": "Paint Bucket (G): click inside the area.",
    "Fill polygon": "Polygon (Shift+D): click round the shape.",
    "Add outline": "Edit > FX > Outline (Shift+O).",
    "Erase area": "Select the area with Rectangular Marquee (M), then press Del.",
    "Replace color": "Edit > Replace Color (Shift+R).",
    "Invert colors": "Edit > Invert.",
    "Adjust HSL": "Edit > Adjustments > Hue/Saturation (Ctrl+U, Cmd+U on Mac).",
    "Brightness/contrast": "Edit > Adjustments > Brightness/Contrast.",
    "Flip": "Edit > Flip Horizontal (Shift+H) or Flip Vertical (Shift+V).",
    "Rotate": "Sprite > Rotate Canvas.",
    "Resize": "Sprite > Sprite Size (Ctrl+Alt+I, Cmd+Alt+I on Mac).",
    "Expand canvas": "Sprite > Canvas Size (C).",
    "Crop": "Select the area with Rectangular Marquee (M), then Sprite > Crop.",
    "Autocrop": "Sprite > Trim.",
    "Color mode": "Sprite > Color Mode.",
    "Add layer": "Layer > New > New Layer (Shift+N).",
    "Duplicate layer": "Layer > Duplicate.",
    "Merge layer down": "Layer > Merge Down.",
    "Flatten": "Layer > Flatten.",
    "Layer opacity": "Layer > Properties, then the Opacity slider.",
    "Layer blend mode": "Layer > Properties, then the Mode list.",
    "Layer visibility": "Shift+X, or the eye icon in the timeline.",
    "Add frame": "Frame > New Frame (Alt+N).",
    "Add frames": "Frame > New Frame (Alt+N), once per frame.",
    "Duplicate frame": "Frame > New Frame (Alt+N) copies the current frame.",
    "Delete frame": "Frame > Delete Frame (Alt+C).",
    "Reverse frames": "Frame > Reverse Frames (Alt+I).",
    "Frame duration": "Frame > Frame Properties (P).",
    "Frame durations": "Select the frames in the timeline, then Frame > Frame Properties (P).",
    "Apply timing": "Select each frame, then Frame > Frame Properties (P) and type its time.",
    "Create tag": "Select the frames in the timeline, then Frame > Tags > New Tag.",
    "Tween frames": "No single command: duplicate the frame (Alt+N), then nudge the art with "
    "Move (V).",
    "In-between": "No single command: turn on the onion skin (F3) and draw the frames between "
    "your key poses.",
    "AI edits in selection": "Select the area with Rectangular Marquee (M) or Lasso (Q) first: "
    "Aseprite's drawing tools then stay inside it.",
    "Add reference image": "Layer > New > New Reference Layer from File.",
    "Walk cycle template": "No single command: draw contact, down, passing, and up poses over "
    "the onion skin (F3).",
}


class _Recorder:
    """Keeps a picture after each edit. When it fills up it drops every other picture
    and takes half as many from then on, so a long session still spans start to end."""

    def __init__(self) -> None:
        self.frames: list[Raster] = []
        self.active = False
        self.limit = _MAX_RECORDED
        self.every = 1
        self.edits = 0
        self.failed = 0

    def start(self, limit: int) -> None:
        self.__init__()
        self.active = True
        self.limit = limit

    def capture(self, file: str | None) -> None:
        if not self.active:
            return
        self.edits += 1
        if self.edits % self.every:
            return
        try:
            frame = _take(_snapshot(file))
        except ToolError:
            self.failed += 1
            return
        if self.frames and self.frames[-1] == frame:
            return
        self.frames.append(frame)
        if len(self.frames) >= self.limit:
            self.frames = self.frames[::2]
            self.every *= 2


recorder = _Recorder()
after_edit.append(recorder.capture)


def frame_ranges(frames: list[int]) -> str:
    """``[1, 2, 3, 7]`` as ``1-3, 7``."""
    spans: list[list[int]] = []
    for n in sorted(frames):
        if spans and n == spans[-1][1] + 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


def summarize(entries: list[dict]) -> list[dict]:
    """Merge runs of the same edit on the same layers into one line each."""
    out: list[dict] = []
    for e in entries:
        layers = e.get("layers")
        last = out[-1] if out else None
        if last and last["edit"] == e["label"] and last["_layers"] == layers:
            last["times"] += 1
            last["_frames"].update(e.get("frames") or [])
            last["pixels"] = (last["pixels"] or 0) + (e.get("pixels") or 0) or None
            continue
        out.append(
            {
                "edit": e["label"],
                "times": 1,
                "pixels": e.get("pixels"),
                "_layers": layers,
                "_frames": set(e.get("frames") or []),
            }
        )
    for line in out:
        line["layers"] = line.pop("_layers")
        line["frames"] = frame_ranges(line.pop("_frames")) or None
    return out


def explanation(label: str) -> str:
    if label.startswith("Preset palette"):
        return "Open the palette options menu above the palette, then Load Palette."
    return EXPLANATIONS.get(label) or (
        "No single Aseprite command does this; it was done by script. Search the manual "
        "with search_manual if you'd like the nearest technique."
    )


def pad_to_largest(frames: list[Raster]) -> list[Raster]:
    """Center every picture on the biggest canvas, in case the sprite was resized."""
    w = max(f.width for f in frames)
    h = max(f.height for f in frames)
    out = []
    for f in frames:
        if (f.width, f.height) == (w, h):
            out.append(f)
            continue
        canvas = bytearray(w * h * 4)
        blit(canvas, w, f, (w - f.width) // 2, (h - f.height) // 2)
        out.append(Raster(w, h, bytes(canvas)))
    return out


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Add reference image"))
    def add_reference_image(
        image_path: str,
        opacity: int = 90,
        fit: bool = True,
        layer_name: str = "Reference",
        file: str | None = None,
    ) -> dict:
        """Put a sketch or reference on a faded, locked layer on top of the sprite, across
        every frame, and keep the active layer as it was, so drawing lands on the art.
        ``image_path`` is a file on disk; a picture pasted into chat needs saving first.
        ``fit`` shrinks a larger image to the canvas. ``opacity`` is 0-255. Hide or delete
        the layer when done. Saving to a flat format would merge it in, so hide it first.
        One undo step. Headless: pass ``file``."""
        if not 0 <= opacity <= 255:
            raise ToolError("opacity must be 0..255")
        if not os.path.isfile(image_path):
            raise ToolError(f"no file at {image_path}")
        body = (
            image_loader(image_path)
            + lua_locals(PATH=image_path, OPACITY=int(opacity), FIT=bool(fit), NAME=layer_name)
            + _REFERENCE
        )
        return run(body, mutates=True, undo_label="Add reference image", file=file, capped=False)

    @mcp.tool(annotations=ToolAnnotations(title="Change summary", readOnlyHint=True))
    def change_summary(last: int | None = None) -> dict:
        """A short list of what Claude changed this session, oldest first: each edit, how
        many times in a row, the frames and layers it touched, and pixels changed. Repeats
        on the same layer are merged. ``last`` limits it to the most recent edits. It
        covers the most recent 500 edits since the server started, and frames are missing
        for edits made with the pixel cap off, or that can't lose pixels."""
        if last is not None and last < 1:
            raise ToolError("last must be 1 or more")
        entries = journal[-last:] if last else journal
        return {"edits": len(entries), "summary": summarize(entries)}

    @mcp.tool(annotations=ToolAnnotations(title="Explain recent edits", readOnlyHint=True))
    def explain_changes(last: int = 5) -> dict:
        """Say which Aseprite tool, menu, or shortcut would do what Claude just did, so you
        pick up the technique. Covers the ``last`` most recent edits, newest repeats
        merged. Shortcuts are Aseprite's defaults."""
        if last < 1:
            raise ToolError("last must be 1 or more")
        lines = summarize(journal[-last:])
        return {
            "explanations": [
                {"edit": x["edit"], "times": x["times"], "by_hand": explanation(x["edit"])}
                for x in lines
            ]
        }

    @mcp.tool(annotations=ToolAnnotations(title="Start recording", idempotentHint=True))
    def start_recording(max_frames: int = _MAX_RECORDED, file: str | None = None) -> dict:
        """Start recording this session: a picture of the active frame is kept after every
        edit, for ``stop_recording`` to turn into a GIF timelapse. Each picture is one more
        read of the sprite, so edits run a little slower while it's on. Starting again
        throws away what's recorded. Headless: pass ``file``."""
        if not 2 <= max_frames <= 1000:
            raise ToolError("max_frames must be 2..1000")
        recorder.start(max_frames)
        recorder.edits = -1
        recorder.capture(file)  # the starting point, not counted as an edit
        return {"recording": True, "frames": len(recorder.frames)}

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Stop recording", destructiveHint=False, openWorldHint=True
        )
    )
    def stop_recording(out_path: str, frame_ms: int = 150, max_size: int = 320) -> dict:
        """Stop recording and write the timelapse GIF to ``out_path``. It's zoomed with
        sharp pixels to fit ``max_size``, and the final picture holds for a beat before it
        loops. Larger GIFs take longer to encode, so raise ``max_size`` with care."""
        if not 16 <= max_size <= 1024:
            raise ToolError("max_size must be 16..1024")
        if not 20 <= frame_ms <= 5000:
            raise ToolError("frame_ms must be 20..5000")
        if rails.dry_run:
            raise ToolError("dry run: stop_recording writes a file, so it was not run.")
        if not recorder.active:
            raise ToolError("not recording: call start_recording first")
        recorder.active = False
        if not recorder.frames:
            raise ToolError("nothing was recorded")
        frames = pad_to_largest(recorder.frames)
        k = fit_factor(frames[0].width, frames[0].height, None, max_size)
        shown = [over_background(resized(f, k), (32, 32, 32)) for f in frames]
        hold = max(1, 1000 // frame_ms)
        data = encode_gif(shown + [shown[-1]] * hold, frame_ms)
        folder = os.path.dirname(out_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        return {
            "gif": out_path,
            "frames": len(frames),
            "width": shown[0].width,
            "height": shown[0].height,
            "failed_captures": recorder.failed,
            "bytes": len(data),
        }
