#!/usr/bin/env python3
"""Search the installed aiogram source tree for a symbol or literal."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    EXIT_NOT_FOUND,
    EXIT_OK,
    ToolError,
    aiogram_versions,
    emit_json,
    require_aiogram,
    run,
)

MAX_LINE = 200


def aiogram_root() -> Path:
    """Directory of the installed aiogram package."""
    module_file = require_aiogram().__file__
    if not module_file:  # pragma: no cover - namespace package edge case
        raise ToolError("cannot locate the installed aiogram package directory")
    return Path(module_file).parent


def search(
    pattern: str,
    root: Path,
    *,
    regex: bool,
    ignore_case: bool,
    subpath: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan every ``.py`` file under ``root`` and collect matching lines."""
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile(pattern if regex else re.escape(pattern), flags)

    hits: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in relative:
            continue
        if subpath and subpath not in relative:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                hits.append(
                    {
                        "file": f"aiogram/{relative}",
                        "line": number,
                        "text": line.rstrip()[:MAX_LINE],
                    }
                )
                if len(hits) >= limit:
                    return hits
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="search-source.py",
        description=(
            "Grep the installed aiogram source tree. Use this to settle questions the "
            "other tools cannot answer, such as where a default is applied or how a "
            "middleware chain is assembled. Searches only the installed package, never "
            "the network."
        ),
        epilog=(
            "examples:\n"
            "  python using-aiogram/tools/search-source.py resolve_used_update_types\n"
            "  python using-aiogram/tools/search-source.py 'class .*Middleware' --regex\n"
            "  python using-aiogram/tools/search-source.py retry_after --in fsm"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pattern", help="literal text to find, or a regex with --regex")
    parser.add_argument("--regex", action="store_true", help="treat the pattern as a regex")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="case-insensitive search")
    parser.add_argument(
        "--in", dest="subpath", metavar="PART", help="restrict to paths containing PART"
    )
    parser.add_argument("--limit", type=int, default=80, help="stop after N matches (default: 80)")
    parser.add_argument("--files", action="store_true", help="print matching file names only")
    parser.add_argument("--json", action="store_true", help="emit machine-readable matches")
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        hits = search(
            args.pattern,
            aiogram_root(),
            regex=args.regex,
            ignore_case=args.ignore_case,
            subpath=args.subpath,
            limit=args.limit,
        )
    except re.error as exc:
        raise ToolError(f"invalid regex {args.pattern!r}: {exc}") from exc

    if args.json:
        emit_json({"pattern": args.pattern, "matches": hits})
        return EXIT_OK if hits else EXIT_NOT_FOUND

    if not hits:
        print(f"no matches for {args.pattern!r} in the installed aiogram source", file=sys.stderr)
        return EXIT_NOT_FOUND

    if args.files:
        for name in dict.fromkeys(hit["file"] for hit in hits):
            print(name)
        return EXIT_OK

    version, _ = aiogram_versions()
    print(f"{len(hits)} match(es) in aiogram {version}")
    print()
    for hit in hits:
        print(f"{hit['file']}:{hit['line']}: {hit['text']}")
    return EXIT_OK


if __name__ == "__main__":
    run(main)
