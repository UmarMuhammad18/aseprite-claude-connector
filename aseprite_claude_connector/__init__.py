"""aseprite-claude-connector — a Unity-first MCP server for the live Aseprite editor.

The same typed tools run against the artist's *running* Aseprite (via the local
relay, one undo step per edit) or a headless ``aseprite --batch`` process, because
``aseprite --batch FILE`` makes FILE the ``app.activeSprite`` — the same idiom the
editor exposes for the active document.
"""

__version__ = "0.2.0"
