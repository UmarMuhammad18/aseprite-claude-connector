import sys


def main() -> None:
    if sys.argv[1:2] == ["setup"]:
        from .setup import main as setup

        raise SystemExit(setup(sys.argv[2:]))
    from .server import main as serve

    serve()


if __name__ == "__main__":
    main()
