#!/usr/bin/env python3
"""Look up a Telegram Bot API method as the installed aiogram models it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    EXIT_OK,
    ToolError,
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


def method_classes() -> dict[str, type]:
    """Every ``TelegramMethod`` subclass exported by ``aiogram.methods``."""
    methods = import_module("aiogram.methods")
    base = import_module("aiogram.methods.base").TelegramMethod
    return public_classes(methods, base)


def api_names(classes: dict[str, type]) -> dict[str, str]:
    """Map the wire method name (``sendMessage``) to the class name (``SendMessage``)."""
    mapping: dict[str, str] = {}
    for class_name, cls in classes.items():
        wire = getattr(cls, "__api_method__", None)
        if isinstance(wire, str):
            mapping[wire] = class_name
    return mapping


def describe(cls: type) -> dict[str, Any]:
    """Build a structured description of one method class."""
    doc = " ".join((cls.__doc__ or "").split())
    source = ""
    if "Source: " in doc:
        doc, _, source = doc.partition("Source: ")
    return {
        "class": cls.__name__,
        "api_method": getattr(cls, "__api_method__", None),
        "returns": render_annotation(getattr(cls, "__returning__", None)),
        "summary": doc.strip(),
        "documentation": source.strip(),
        "fields": model_field_rows(cls),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="get-method.py",
        description=(
            "Describe a Telegram Bot API method using the aiogram release installed in "
            "this environment: required and optional arguments, their types, per-field "
            "documentation, and the return type."
        ),
        epilog=(
            "examples:\n"
            "  python using-aiogram/tools/get-method.py sendMessage\n"
            "  python using-aiogram/tools/get-method.py SendPhoto\n"
            "  python using-aiogram/tools/get-method.py --list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", nargs="?", help="method name, e.g. sendMessage or SendMessage")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable record")
    parser.add_argument("--list", action="store_true", help="print every method name and exit")
    args = parser.parse_args()

    classes = method_classes()
    wire_to_class = api_names(classes)

    if args.list:
        for wire in sorted(wire_to_class):
            print(f"{wire}  ({wire_to_class[wire]})")
        return EXIT_OK

    if not args.name:
        parser.print_help()
        return EXIT_OK

    # Both spellings are accepted: the wire name (sendMessage) and the class name
    # (SendMessage). They alias to the same method, so neither is ambiguous.
    candidates = list(wire_to_class) + list(classes)
    alias = {wire: class_name for wire, class_name in wire_to_class.items()}
    matched = resolve(args.name, candidates, alias=alias)
    class_name = wire_to_class.get(matched, matched)
    cls = classes.get(class_name)
    if cls is None:  # pragma: no cover - resolve() guarantees membership
        raise ToolError(f"{args.name!r} resolved to {class_name!r}, which is not a method class")

    record = describe(cls)
    if args.json:
        emit_json(record)
        return EXIT_OK

    version, api_version = aiogram_versions()
    print(f"{record['api_method']}  ->  aiogram.methods.{record['class']}")
    print(f"aiogram {version} | telegram bot api {api_version}")
    if record["documentation"]:
        print(record["documentation"])
    print()
    if record["summary"]:
        print(wrap(record["summary"], "  "))
        print()

    required = [row for row in record["fields"] if row["required"]]
    optional = [row for row in record["fields"] if not row["required"]]
    print(f"required arguments ({len(required)}):")
    print_field_rows(required)
    print()
    print(f"optional arguments ({len(optional)}):")
    print_field_rows(optional)
    print()
    print(f"returns: {record['returns']}")
    print()
    print("call styles:")
    print(f"  await bot.{_snake(record['api_method'])}(...)          # Bot shortcut")
    print(f"  await bot(aiogram.methods.{record['class']}(...))   # explicit method object")
    return EXIT_OK


def _snake(name: str | None) -> str:
    """Convert ``sendMessage`` to ``send_message`` for the Bot-shortcut hint."""
    if not name:
        return "<method>"
    out: list[str] = []
    for char in name:
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)


if __name__ == "__main__":
    run(main)
