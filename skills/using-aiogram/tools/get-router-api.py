#!/usr/bin/env python3
"""Report the Router/Dispatcher surface of the installed aiogram."""

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


def observer_names() -> list[str]:
    """The update types a Router can observe, read from a live Router instance.

    This is the authoritative list of ``@router.<name>()`` decorators, and it is
    exactly what ``Dispatcher.resolve_used_update_types()`` reports on.
    """
    router_cls = import_module("aiogram").Router
    return sorted(router_cls().observers)


def public_methods(cls: type) -> list[dict[str, str]]:
    """Public methods declared on ``cls`` or its aiogram bases, with signatures."""
    rows: list[dict[str, str]] = []
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        if not getattr(member, "__module__", "").startswith("aiogram."):
            continue
        try:
            signature = (
                str(inspect.signature(member)).replace("(self, ", "(").replace("(self)", "()")
            )
        except (TypeError, ValueError):  # pragma: no cover - defensive
            signature = "(...)"
        rows.append({"name": name, "signature": signature})
    return sorted(rows, key=lambda row: row["name"])


def build_report() -> dict[str, Any]:
    """Collect the routing surface in one structured record."""
    aiogram = import_module("aiogram")
    return {
        "observers": observer_names(),
        "router_init": str(inspect.signature(aiogram.Router.__init__)).replace("(self, ", "("),
        "router_methods": public_methods(aiogram.Router),
        "dispatcher_init": str(inspect.signature(aiogram.Dispatcher.__init__)).replace(
            "(self, ", "("
        ),
        "dispatcher_methods": public_methods(aiogram.Dispatcher),
        "bot_init": str(inspect.signature(aiogram.Bot.__init__)).replace("(self, ", "("),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="get-router-api.py",
        description=(
            "Report the routing surface of the installed aiogram: every observer a "
            "Router exposes (the valid @router.<name>() decorators), plus the "
            "constructor and public methods of Router, Dispatcher, and Bot."
        ),
        epilog=(
            "examples:\n"
            "  python using-aiogram/tools/get-router-api.py\n"
            "  python using-aiogram/tools/get-router-api.py --observers\n"
            "  python using-aiogram/tools/get-router-api.py --observer callback_query"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable record")
    parser.add_argument("--observers", action="store_true", help="print observer names only")
    parser.add_argument(
        "--observer",
        metavar="NAME",
        help="check one observer name and show the decorator form",
    )
    args = parser.parse_args()

    report = build_report()

    if args.observer:
        matched = resolve(args.observer, report["observers"])
        print(f"observer:  {matched}")
        print(f"decorator: @router.{matched}(*filters)")
        print(f"registrar: router.{matched}.register(handler, *filters)")
        print(f"middleware: router.{matched}.middleware(MyMiddleware())")
        print(f"outer:     router.{matched}.outer_middleware(MyMiddleware())")
        print()
        print(
            wrap(f"'{matched}' is a valid key for allowed_updates and for Update.event_type.", "")
        )
        return EXIT_OK

    if args.observers:
        for name in report["observers"]:
            print(name)
        return EXIT_OK

    if args.json:
        emit_json(report)
        return EXIT_OK

    version, api_version = aiogram_versions()
    print(f"aiogram {version} | telegram bot api {api_version}")
    print()
    print(f"Router observers ({len(report['observers'])}) - valid @router.<name>() decorators:")
    for name in report["observers"]:
        print(f"  {name}")
    print()
    print(f"Bot{report['bot_init']}")
    print()
    print(f"Router{report['router_init']}")
    for row in report["router_methods"]:
        print(f"  .{row['name']}{row['signature']}")
    print()
    print(f"Dispatcher{report['dispatcher_init']}")
    for row in report["dispatcher_methods"]:
        print(f"  .{row['name']}{row['signature']}")
    return EXIT_OK


if __name__ == "__main__":
    run(main)
