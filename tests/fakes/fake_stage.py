"""Fake program for testing — NOT imported by production code.

This standalone script simulates the behaviour of an external program
so that later stages can test process supervision without needing
real MuMu / ADB / SRP / MAA / AALC executables.

Usage::

    python tests/fakes/fake_stage.py [--exit-code 0] [--stdout "hello"] [--stderr "oops"] [--write-file path/contents]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake stage program for testing.")
    parser.add_argument("--exit-code", type=int, default=0, help="Exit code to return (default: 0).")
    parser.add_argument("--stdout", type=str, default="", help="Text to write to stdout.")
    parser.add_argument("--stderr", type=str, default="", help="Text to write to stderr.")
    parser.add_argument(
        "--write-file",
        type=str,
        default="",
        help="Write text to a file, format: path::contents",
    )

    args = parser.parse_args()

    if args.stdout:
        sys.stdout.write(args.stdout)
    if args.stderr:
        sys.stderr.write(args.stderr)

    if args.write_file:
        parts = args.write_file.split("::", 1)
        if len(parts) == 2:
            path = Path(parts[0])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(parts[1], encoding="utf-8")

    sys.exit(args.exit_code)


if __name__ == "__main__":
    main()
