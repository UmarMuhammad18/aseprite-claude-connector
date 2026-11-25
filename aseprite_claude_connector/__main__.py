import sys

HELP = """\
usage: aseprite-claude-connector [setup [options] | --help | --version]

With no arguments, runs the MCP server on stdio. Your MCP client (Claude Code or the
Claude desktop app) starts it this way; you don't run it by hand.

  setup        register the server with Claude Code and install the Aseprite
               extension (run `aseprite-claude-connector setup --help` for options)
  --help, -h   show this help
  --version    show the installed version
"""


def main() -> None:
    first = sys.argv[1:2]
    if first == ["setup"]:
        from .setup import main as setup

        raise SystemExit(setup(sys.argv[2:]))
    if first in (["--help"], ["-h"]):
        # Help goes to stdout like any CLI: this only happens when a person types it,
        # never when an MCP client starts the server (clients pass no arguments).
        print(HELP, end="")
        return
    if first in (["--version"], ["-V"]):
        from . import __version__

        print(f"aseprite-claude-connector {__version__}")
        return
    from .server import main as serve

    serve()


if __name__ == "__main__":
    main()
