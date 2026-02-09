from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cli", action="store_true")
    parser.add_argument("--gui", action="store_true")
    return parser.parse_known_args(argv)[0]


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.cli:
        from app.cli import main as cli_main

        raise SystemExit(cli_main(sys.argv[1:]))

    if args.gui or not args.cli:
        from app.main import main as gui_main

        gui_main()


if __name__ == "__main__":
    main()
