"""Generate the README tool reference from the server itself.

The section between ``<!-- TOOLS:START -->`` and ``<!-- TOOLS:END -->`` in
README.md — and the ``tools-N`` badge — are written by this script from the
actual tool registrations, so the docs can't drift from the code. CI runs
``gen_docs.py --check`` and fails if a regeneration would change the README.

Usage:
    python scripts/gen_docs.py          # rewrite README.md in place
    python scripts/gen_docs.py --check  # exit 1 if README is stale
"""

from __future__ import annotations

import os
import re
import sys

os.environ.setdefault("ASEPRITE_MCP_BACKEND", "headless")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import anyio  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from aseprite_claude_connector import server as srv  # noqa: E402

# Module -> human category (order = display order).
CATEGORIES = [
    ("inspect", "Inspect & metadata"),
    ("look", "Canvas vision"),
    ("session", "Documents & session"),
    ("canvas", "Canvas"),
    ("layers", "Layers & groups"),
    ("frames", "Frames"),
    ("cels", "Cels"),
    ("draw", "Drawing"),
    ("palette", "Palette"),
    ("color", "Color"),
    ("shading", "Shading"),
    ("filters", "Filters"),
    ("brushes", "Stamp painting"),
    ("isometric", "Isometric"),
    ("selection", "Selection"),
    ("transform", "Transform"),
    ("slices", "Slices"),
    ("tags", "Tags"),
    ("tilemaps", "Tilemaps"),
    ("animate", "Animation"),
    ("export", "Export"),
    ("unity_export", "Unity export"),
    ("artqa", "Art QA"),
    ("batch", "Batch (whole folder)"),
    ("editor", "Undo / redo"),
    ("live", "Live editor (interactive)"),
    ("lua_escape", "Advanced"),
]


def collect():
    """Register each tool module into its own FastMCP to learn which tools it owns."""
    by_module: dict[str, list] = {}
    total = 0
    for module in srv._TOOL_MODULES:
        name = module.__name__.rsplit(".", 1)[-1]
        probe = FastMCP("probe")
        module.register(probe)
        tools = anyio.run(probe.list_tools)
        by_module[name] = tools
        total += len(tools)
    # resources + prompts from the real server
    full = srv.build_server()
    resources = anyio.run(full.list_resources)
    prompts = anyio.run(full.list_prompts)
    return by_module, total, resources, prompts


def first_sentence(text: str) -> str:
    """First sentence of a docstring, without breaking on common abbreviations."""
    text = " ".join((text or "").split())
    # Mask abbreviation periods so the sentence split can't fire on them.
    masked = text
    for abbr in ("e.g.", "i.e.", "vs.", "Rec.", "approx.", "etc."):
        masked = masked.replace(abbr, abbr.replace(".", "\x00"))
    m = re.match(r"(.+?\.)(\s|$)", masked)
    out = (m.group(1) if m else masked).replace("\x00", ".")
    return out[:240]


def render(by_module: dict, total: int) -> str:
    lines = [f"## Tools ({total})", ""]
    lines.append(
        "Every tool is typed, annotated (`readOnlyHint`/`destructiveHint`/"
        "`idempotentHint`/`openWorldHint`), and — when it mutates — wrapped in a "
        "**named** `app.transaction`, so each edit is exactly one labeled undo "
        "step in the editor."
    )
    lines.append("")
    for mod_name, title in CATEGORIES:
        tools = by_module.get(mod_name)
        if not tools:
            continue
        lines.append("<details>")
        lines.append(f"<summary><b>{title}</b> ({len(tools)})</summary>")
        lines.append("")
        for t in tools:
            lines.append(f"- **`{t.name}`** — {first_sentence(t.description)}")
        lines.append("")
        lines.append("</details>")
    return "\n".join(lines)


def main() -> int:
    check = "--check" in sys.argv
    by_module, total, _resources, _prompts = collect()
    readme_path = os.path.join(REPO, "README.md")
    with open(readme_path, encoding="utf-8") as f:
        readme = f.read()

    section = render(by_module, total)
    pattern = re.compile(r"<!-- TOOLS:START -->.*?<!-- TOOLS:END -->", re.S)
    if not pattern.search(readme):
        print("README.md is missing the <!-- TOOLS:START/END --> markers", file=sys.stderr)
        return 1
    updated = pattern.sub(f"<!-- TOOLS:START -->\n{section}\n<!-- TOOLS:END -->", readme)
    # keep the tools badge honest too
    updated = re.sub(r"badge/tools-\d+-", f"badge/tools-{total}-", updated)

    if check:
        if updated != readme:
            print("README tool docs are stale — run: python scripts/gen_docs.py", file=sys.stderr)
            return 1
        print(f"README tool docs are current ({total} tools).")
        return 0

    with open(readme_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(updated)
    print(f"README.md regenerated: {total} tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
