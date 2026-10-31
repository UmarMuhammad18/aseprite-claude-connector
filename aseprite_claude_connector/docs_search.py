"""Search over Aseprite's Markdown docs. Stdlib only.

Pages split into one section per heading, ranked with BM25, with extra weight on
headings so ``Sprite:newLayer`` beats a page that only mentions it in passing.

The scripting API (MIT) ships in ``api_docs/``. The user manual has no licence, so
it can't ship with this repo: ``manual_index`` downloads the user's own copy to their
cache the first time it's needed, and only for that explicit tool call.
"""

from __future__ import annotations

import io
import json
import math
import re
import tarfile
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .update_check import _cache_path

API_DIR = Path(__file__).parent / "api_docs"
API_URL = "https://www.aseprite.org/api/"
MANUAL_URL = "https://www.aseprite.org/docs/"
MANUAL_ARCHIVE = "https://codeload.github.com/aseprite/docs/tar.gz/HEAD"
MANUAL_TTL = 30 * 24 * 60 * 60
FETCH_TIMEOUT = 30.0
EXCERPT = 1000
HEADING_WEIGHT = 4
K1, B = 1.5, 0.75


@dataclass(frozen=True)
class Section:
    title: str
    url: str
    text: str


def _tokens(text: str) -> list[str]:
    """Lowercase words, keeping a camelCase name and its parts: ``newLayer`` gives
    ``newlayer``, ``new`` and ``layer``."""
    out = []
    for word in re.findall(r"[A-Za-z0-9]+", text):
        low = word.lower()
        out.append(low)
        parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", word)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
    return out


def split_sections(markdown: str, url: str) -> list[Section]:
    """One section per heading, titled with its parent headings."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []
    fenced = False

    def flush():
        text = "\n".join(lines).strip()
        if text or stack:
            title = " > ".join(h for _, h in stack)
            sections.append(Section(title, url, text))
        lines.clear()

    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else re.match(r"(#{1,6})\s+(.*\S)", line)
        if match:
            flush()
            level = len(match[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match[2].strip("# ")))
        else:
            lines.append(line)
    flush()
    return sections


class DocIndex:
    def __init__(self, sections: list[Section]):
        self.sections = sections
        self.counts: list[Counter] = []
        df: Counter = Counter()
        for sec in sections:
            count = Counter(_tokens(sec.text))
            for tok in _tokens(sec.title):
                count[tok] += HEADING_WEIGHT
            self.counts.append(count)
            df.update(count.keys())
        n = len(sections) or 1
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avg = (sum(self.lengths) / n) or 1
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, limit: int = 5) -> list[dict]:
        terms = set(_tokens(query))
        scored = []
        for i, count in enumerate(self.counts):
            score = 0.0
            norm = K1 * (1 - B + B * self.lengths[i] / self.avg)
            for term in terms:
                tf = count.get(term, 0)
                if tf:
                    score += self.idf[term] * tf * (K1 + 1) / (tf + norm)
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda item: (-item[0], item[1]))
        out = []
        for score, i in scored[:limit]:
            sec = self.sections[i]
            text = sec.text
            if len(text) > EXCERPT:
                text = text[:EXCERPT].rsplit("\n", 1)[0] + "\n[...]"
            out.append({"title": sec.title, "url": sec.url, "score": round(score, 2), "text": text})
        return out


def _index(pages: dict[str, str], base_url: str) -> DocIndex:
    sections: list[Section] = []
    for rel, text in sorted(pages.items()):
        slug = rel.removesuffix(".md")
        slug = "" if slug.lower() == "readme" else slug
        sections.extend(split_sections(text, base_url + slug))
    return DocIndex(sections)


@lru_cache(maxsize=1)
def api_index() -> DocIndex:
    pages = {
        p.relative_to(API_DIR).as_posix(): p.read_text(encoding="utf-8")
        for p in API_DIR.rglob("*.md")
    }
    return _index(pages, API_URL)


def fetch_markdown(url: str) -> dict[str, str]:
    """Read the ``.md`` files of a GitHub archive into memory, keyed by their path in
    the repo. Nothing is unpacked to disk, so archive paths can't escape anywhere."""
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
        data = r.read()
    pages = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            rel = member.name.partition("/")[2]
            if member.isfile() and rel.endswith(".md") and not rel.startswith("."):
                pages[rel] = tar.extractfile(member).read().decode("utf-8", "replace")
    return pages


def _manual_cache() -> Path:
    return Path(_cache_path()).with_name("manual.json")


def _load_manual() -> dict[str, str]:
    path = _manual_cache()
    cached = None
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            cached = None
        if cached and time.time() - path.stat().st_mtime < MANUAL_TTL:
            return cached
    try:
        pages = fetch_markdown(MANUAL_ARCHIVE)
    except OSError:
        if cached:  # stale but usable beats failing offline
            return cached
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pages), encoding="utf-8")
    return pages


@lru_cache(maxsize=1)
def manual_index() -> DocIndex:
    return _index(_load_manual(), MANUAL_URL)
