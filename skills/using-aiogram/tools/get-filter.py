#!/usr/bin/env python3
"""Look up an aiogram filter, its constructor signature, and what it injects."""

from __future__ import annotations

import argparse
import contextlib
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
    render_annotation,
    resolve,
    run,
    wrap,
)


def filter_exports() -> dict[str, Any]:
    """Everything ``aiogram.filters`` exports, filters and sentinel constants alike."""
    module = import_module("aiogram.filters")
    names = getattr(module, "__all__", None) or [n for n in dir(module) if not n.startswith("_")]
    return {name: getattr(module, name) for name in names if hasattr(module, name)}


def describe(name: str, obj: Any) -> dict[str, Any]:
    """Describe one export: a filter class, a helper function, or a constant."""
    doc = " ".join((obj.__doc__ or "").split()) if inspect.isclass(obj) else ""
    record: dict[str, Any] = {
        "name": name,
        "kind": "class" if inspect.isclass(obj) else type(obj).__name__,
        "summary": doc,
        "signature": None,
        "value": None,
        "bases": [],
    }
    if inspect.isclass(obj):
        record["bases"] = [base.__name__ for base in obj.__bases__]
        try:
            record["signature"] = f"{name}{inspect.signature(obj.__init__)}".replace("(self, ", "(")
        except (TypeError, ValueError):
            record["signature"] = f"{name}(...)"
        # Read __call__ off the class itself so we inspect the filter's own
        # signature, not the metaclass's. getattr_static avoids the descriptor
        # protocol, which would otherwise bind and hide the annotations.
        call = inspect.getattr_static(obj, "__call__", None)
        if call is not None and getattr(call, "__module__", "").startswith("aiogram."):
            with contextlib.suppress(TypeError, ValueError):
                record["returns"] = render_annotation(inspect.signature(call).return_annotation)
    elif callable(obj):
        try:
            record["signature"] = f"{name}{inspect.signature(obj)}"
        except (TypeError, ValueError):  # pragma: no cover - defensive
            record["signature"] = f"{name}(...)"
    else:
        record["value"] = repr(obj)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="get-filter.py",
        description=(
            "Describe an aiogram filter from the installed package: constructor "
            "signature, base classes, and (for filters that inject data into handlers) "
            "the object the handler receives. Also covers the exported sentinel "
            "constants used with ChatMemberUpdatedFilter."
        ),
        epilog=(
            "examples:\n"
            "  python using-aiogram/tools/get-filter.py Command\n"
            "  python using-aiogram/tools/get-filter.py StateFilter\n"
            "  python using-aiogram/tools/get-filter.py --list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", nargs="?", help="filter name, e.g. Command")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable record")
    parser.add_argument("--list", action="store_true", help="print every export and exit")
    args = parser.parse_args()

    exports = filter_exports()

    if args.list:
        for name in sorted(exports):
            obj = exports[name]
            kind = "class" if inspect.isclass(obj) else type(obj).__name__
            print(f"{name}  ({kind})")
        return EXIT_OK

    if not args.name:
        parser.print_help()
        return EXIT_OK

    matched = resolve(args.name, list(exports))
    record = describe(matched, exports[matched])

    if args.json:
        emit_json(record)
        return EXIT_OK

    version, api_version = aiogram_versions()
    print(f"aiogram.filters.{record['name']}  ({record['kind']})")
    print(f"aiogram {version} | telegram bot api {api_version}")
    print()
    if record["bases"]:
        print(f"bases:     {', '.join(record['bases'])}")
    if record["signature"]:
        print(f"signature: {record['signature']}")
    if record.get("returns"):
        print(f"returns:   {record['returns']}")
    if record["value"] is not None:
        print(f"value:     {record['value']}")
    if record["summary"]:
        print()
        print(wrap(record["summary"], "  "))
    return EXIT_OK


if __name__ == "__main__":
    run(main)
