# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/): while we're pre-1.0, minor bumps
(0.x) may change tool behavior; patch bumps are fixes only.

**How you'll know it's time to update:** the `status` tool reports your installed
version and whether a newer release exists (checked against PyPI at most once a
day; set `ASEPRITE_MCP_NO_UPDATE_CHECK=1` to disable). `uvx aseprite-live-mcp`
users pick up new releases automatically.

## [Unreleased]

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

[Unreleased]: https://github.com/oaktreegames/aseprite-live-mcp/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.1.2
[0.1.1]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/oaktreegames/aseprite-live-mcp/releases/tag/v0.1.0
