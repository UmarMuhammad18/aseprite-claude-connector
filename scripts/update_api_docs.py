"""Refresh the bundled scripting API docs from github.com/aseprite/api (MIT).

    python scripts/update_api_docs.py

Only the API docs are bundled. The user manual has no licence, so ``search_manual``
downloads it to the user's cache instead of this repo shipping a copy.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aseprite_claude_connector.docs_search import fetch_markdown  # noqa: E402

URL = "https://codeload.github.com/aseprite/api/tar.gz/refs/heads/main"
LICENSE_URL = "https://raw.githubusercontent.com/aseprite/api/main/LICENSE.txt"
OUT = Path(__file__).resolve().parent.parent / "aseprite_claude_connector" / "api_docs"


def main() -> int:
    import urllib.request

    pages = fetch_markdown(URL)
    pages = {k: v for k, v in pages.items() if k.startswith("api/")}
    if not pages:
        print("no API pages found", file=sys.stderr)
        return 1
    shutil.rmtree(OUT, ignore_errors=True)
    for rel, text in pages.items():
        path = OUT / rel.removeprefix("api/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    with urllib.request.urlopen(LICENSE_URL, timeout=30) as r:
        (OUT / "LICENSE.txt").write_bytes(r.read())
    print(f"wrote {len(pages)} pages to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
