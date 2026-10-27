#!/usr/bin/env python3
"""Look up a Telegram Bot API object (aiogram type) and its shortcut methods."""

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
    model_field_rows,
    print_field_rows,
    public_classes,
    render_annotation,
    resolve,
    run,
    wrap,
)


def type_classes() -> dict[str, type]:
    """Every ``TelegramObject`` subclass exported by ``aiogram.types``."""
    types_module = import_module("aiogram.types")
    base = import_module("aiogram.types.base").TelegramObject
    return public_classes(types_module, base)


def shortcuts(cls: type) -> list[dict[str, str]]:
    """List the convenience methods aiogram adds on top of the raw Bot API object.

    These are the ``message.answer()`` / ``callback_query.answer()`` helpers: methods
    defined on the aiogram class itself rather than inherited from pydantic.
    """
    skip = {"model_copy", "model_dump", "model_dump_json", "model_post_init", "dict", "json"}
    found: list[dict[str, str]] = []
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_") or name in skip:
            continue
        module = getattr(member, "__module__", "")
        if not module.startswith("aiogram."):
            continue
        try:
            signature = str(inspect.signature(member))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            signature = "(...)"
        returns = render_annotation(inspect.signature(member).return_annotation)
        found.append({"name": name, "signature": signature, "returns": returns})
    return sorted(found, key=lambda row: row["name"])


def describe(cls: type) -> dict[str, Any]:
    """Build a structured description of one type class."""
    doc = " ".join((cls.__doc__ or "").split())
    source = ""
    if "Source: " in doc:
        doc, _, source = doc.partition("Source: ")
    return {
        "class": cls.__name__,
        "summary": doc.strip(),
        "documentation": source.strip(),
        "fields": model_field_rows(cls),
        "shortcuts": shortcuts(cls),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="get-type.py",
        description=(
            "Describe an aiogram type: its pydantic fields (required vs optional, with "
            "wire aliases such as from_user -> from) and the shortcut methods aiogram "
            "attaches to it, read from the installed package."
        ),
        epilog=(
            "examples:\n"
            "  python using-aiogram/tools/get-type.py Message\n"
            "  python using-aiogram/tools/get-type.py CallbackQuery --shortcuts\n"
            "  python using-aiogram/tools/get-type.py --list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", nargs="?", help="type name, e.g. Message")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable record")
    parser.add_argument("--list", action="store_true", help="print every type name and exit")
    parser.add_argument(
        "--shortcuts",
        action="store_true",
        help="print only the shortcut methods (message.answer, callback.answer, ...)",
    )
    parser.add_argument(
        "--fields-only",
        action="store_true",
        help="print only the pydantic fields, skipping shortcuts",
    )
    args = parser.parse_args()

    classes = type_classes()

    if args.list:
        for name in sorted(classes):
            print(name)
        return EXIT_OK

    if not args.name:
        parser.print_help()
        return EXIT_OK

    matched = resolve(args.name, list(classes))
    record = describe(classes[matched])

    if args.json:
        emit_json(record)
        return EXIT_OK

    version, api_version = aiogram_versions()
    print(f"aiogram.types.{record['class']}")
    print(f"aiogram {version} | telegram bot api {api_version}")
    if record["documentation"]:
        print(record["documentation"])
    print()
    if record["summary"]:
        print(wrap(record["summary"], "  "))
        print()

    if not args.shortcuts:
        required = [row for row in record["fields"] if row["required"]]
        optional = [row for row in record["fields"] if not row["required"]]
        print(f"required fields ({len(required)}):")
        print_field_rows(required)
        print()
        print(f"optional fields ({len(optional)}):")
        print_field_rows(optional)
        print()

    if not args.fields_only:
        rows = record["shortcuts"]
        print(f"shortcut methods ({len(rows)}):")
        if not rows:
            print("  (none - this type has no aiogram shortcuts)")
        for row in rows:
            print(f"  {row['name']}{_trim(row['signature'])} -> {row['returns']}")
    return EXIT_OK


def _trim(signature: str, limit: int = 110) -> str:
    """Shorten long signatures so the listing stays readable."""
    if len(signature) <= limit:
        return signature
    return signature[: limit - 4] + " ...)"


if __name__ == "__main__":
    run(main)
