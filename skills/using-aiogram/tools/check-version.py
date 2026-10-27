#!/usr/bin/env python3
"""Report the installed aiogram version and flag drift against the skill pin."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    EXIT_NOT_FOUND,
    EXIT_OK,
    aiogram_versions,
    emit_json,
    require_aiogram,
    run,
)

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def read_pins() -> dict[str, str]:
    """Read the ``aiogram``/``bot_api`` pins from the sibling SKILL.md frontmatter."""
    if not SKILL_MD.exists():
        return {}
    pins: dict[str, str] = {}
    in_frontmatter = False
    for raw in SKILL_MD.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if not in_frontmatter:
            continue
        for key in ("aiogram", "bot_api"):
            prefix = f"{key}:"
            if line.startswith(prefix):
                pins[key] = line[len(prefix) :].strip().strip('"').strip("'")
    return pins


def build_report() -> dict[str, Any]:
    """Collect installed versions, the skill pins, and whether they have drifted."""
    version, api_version = aiogram_versions()
    pins = read_pins()
    drift: list[str] = []
    if pins.get("aiogram") and pins["aiogram"] != version:
        drift.append(f"aiogram: skill pins {pins['aiogram']}, environment has {version}")
    if pins.get("bot_api") and pins["bot_api"] != api_version:
        drift.append(f"bot api: skill pins {pins['bot_api']}, environment has {api_version}")
    return {
        "aiogram": version,
        "bot_api": api_version,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "aiogram_path": str(Path(require_aiogram().__file__ or "").parent),
        "pinned_aiogram": pins.get("aiogram"),
        "pinned_bot_api": pins.get("bot_api"),
        "drift": drift,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check-version.py",
        description=(
            "Report the installed aiogram version, the Telegram Bot API version it "
            "targets, and whether either has drifted from the version this skill was "
            "written against. Exits 1 on drift so it can guard a CI step."
        ),
        epilog="example: python using-aiogram/tools/check-version.py --json",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        emit_json(report)
        return EXIT_NOT_FOUND if report["drift"] else EXIT_OK

    print(f"aiogram:        {report['aiogram']}")
    print(f"telegram bot api: {report['bot_api']}")
    print(f"python:         {report['python']}")
    print(f"package path:   {report['aiogram_path']}")
    print()
    if report["pinned_aiogram"] is None and report["pinned_bot_api"] is None:
        print("skill pin:      (none found in SKILL.md frontmatter)")
        return EXIT_OK
    print(f"skill pins:     aiogram {report['pinned_aiogram']}, bot api {report['pinned_bot_api']}")
    if report["drift"]:
        print()
        print("DRIFT DETECTED:")
        for item in report["drift"]:
            print(f"  - {item}")
        print()
        print("Re-verify examples against the installed version before trusting the skill.")
        return EXIT_NOT_FOUND
    print("status:         in sync")
    return EXIT_OK


if __name__ == "__main__":
    run(main)
