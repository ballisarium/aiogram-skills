#!/usr/bin/env python3
"""Look up an aiogram exception and its position in the exception hierarchy."""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    EXIT_OK,
    aiogram_versions,
    emit_json,
    import_module,
    resolve,
    run,
    wrap,
)


def exception_classes() -> dict[str, type]:
    """Every exception class defined in ``aiogram.exceptions``."""
    module = import_module("aiogram.exceptions")
    found: dict[str, type] = {}
    for name, obj in vars(module).items():
        if name.startswith("_"):
            continue
        if inspect.isclass(obj) and issubclass(obj, BaseException):
            found[name] = obj
    return found


def describe(cls: type, pool: dict[str, type]) -> dict[str, Any]:
    """Describe one exception: bases, aiogram-local subclasses, and constructor."""
    try:
        # Signature of the class itself: already excludes `self`.
        signature = str(inspect.signature(cls))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        signature = "(...)"
    subclasses = sorted(
        name for name, other in pool.items() if other is not cls and issubclass(other, cls)
    )
    return {
        "name": cls.__name__,
        "summary": " ".join((cls.__doc__ or "").split()),
        "bases": [base.__name__ for base in cls.__bases__],
        "mro": [base.__name__ for base in cls.__mro__ if base is not object],
        "subclasses": subclasses,
        "signature": signature,
        "attributes": sorted(
            name
            for name, member in inspect.getmembers(cls)
            if not name.startswith("_") and isinstance(member, property)
        ),
    }


def print_tree(pool: dict[str, type]) -> None:
    """Render the aiogram exception hierarchy as an indented tree."""
    roots = [
        cls
        for cls in pool.values()
        if not any(other is not cls and issubclass(cls, other) for other in pool.values())
    ]

    def walk(cls: type, depth: int) -> None:
        print(f"{'  ' * depth}{cls.__name__}")
        children = sorted(
            (other for other in pool.values() if other is not cls and cls in other.__bases__),
            key=lambda item: item.__name__,
        )
        for child in children:
            walk(child, depth + 1)

    for root in sorted(dict.fromkeys(roots), key=lambda item: item.__name__):
        walk(root, 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="get-exception.py",
        description=(
            "Describe an aiogram exception from the installed package: its base "
            "classes, its aiogram subclasses, its constructor, and the attributes it "
            "carries (for example TelegramRetryAfter.retry_after)."
        ),
        epilog=(
            "examples:\n"
            "  python using-aiogram/tools/get-exception.py TelegramRetryAfter\n"
            "  python using-aiogram/tools/get-exception.py --tree\n"
            "  python using-aiogram/tools/get-exception.py --list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", nargs="?", help="exception name, e.g. TelegramBadRequest")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable record")
    parser.add_argument("--list", action="store_true", help="print every exception name and exit")
    parser.add_argument("--tree", action="store_true", help="print the full hierarchy and exit")
    args = parser.parse_args()

    pool = exception_classes()

    if args.list:
        for name in sorted(pool):
            print(name)
        return EXIT_OK

    if args.tree:
        print_tree(pool)
        return EXIT_OK

    if not args.name:
        parser.print_help()
        return EXIT_OK

    matched = resolve(args.name, list(pool))
    record = describe(pool[matched], pool)

    if args.json:
        emit_json(record)
        return EXIT_OK

    version, api_version = aiogram_versions()
    print(f"aiogram.exceptions.{record['name']}")
    print(f"aiogram {version} | telegram bot api {api_version}")
    print()
    print(f"bases:      {', '.join(record['bases'])}")
    print(f"mro:        {' -> '.join(record['mro'])}")
    print(f"signature:  {record['name']}{record['signature']}")
    if record["attributes"]:
        print(f"properties: {', '.join(record['attributes'])}")
    if record["subclasses"]:
        print(f"subclasses: {', '.join(record['subclasses'])}")
    if record["summary"]:
        print()
        print(wrap(record["summary"], "  "))
    print()
    print("catch with:")
    print(f"  from aiogram.exceptions import {record['name']}")
    print(f"  except {record['name']} as error:")
    print()
    print("route to an error handler with:")
    print("  from aiogram.filters import ExceptionTypeFilter")
    print(f"  @router.error(ExceptionTypeFilter({record['name']}))")
    return EXIT_OK


if __name__ == "__main__":
    run(main)
