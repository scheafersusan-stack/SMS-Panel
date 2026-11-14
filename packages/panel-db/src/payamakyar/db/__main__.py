"""``python -m payamakyar.db upgrade|downgrade <rev>`` (URL from PAYAMAKYAR_DATABASE_URL)."""

import argparse
import sys

from payamakyar.db import migrate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m payamakyar.db")
    parser.add_argument("action", choices=["upgrade", "downgrade"])
    parser.add_argument("revision", nargs="?", default=None)
    args = parser.parse_args(argv)
    if args.action == "upgrade":
        migrate.upgrade(None, args.revision or "head")
    else:
        migrate.downgrade(None, args.revision or "-1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
