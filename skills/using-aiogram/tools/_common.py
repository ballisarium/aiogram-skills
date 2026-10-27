"""Shared helpers for the ``using-aiogram`` lookup tools.

Every tool in this directory answers questions about the aiogram release that is
actually installed in the current environment. Nothing here hardcodes an API
list, so the tools stay correct across aiogram upgrades.

Exit codes used by all tools:

* ``0`` -- success
* ``1`` -- lookup failed (unknown name, drift detected, validation failure)
* ``2`` -- usage error (argparse default)
* ``3`` -- aiogram is not importable in this environment
"""

from __future__ import annotations

import ast
import difflib
import importlib
import inspect
import json
import sys
import textwrap
import types
import typing
from collections.abc import Iterable, Sequence
from typing import Any, NoReturn

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_NO_AIOGRAM = 3

_INSTALL_HINT = (
    "aiogram is not importable in this environment.\n"
    "Install it into the interpreter you are running these tools with:\n"
    "    python -m pip install 'aiogram==3.31.0'"
)


class ToolError(Exception):
    """Raised for expected failures that should become a clean CLI message."""

    def __init__(self, message: str, code: int = EXIT_NOT_FOUND) -> None:
        super().__init__(message)
        self.code = code


def die(message: str, code: int = EXIT_NOT_FOUND) -> NoReturn:
    """Print ``message`` to stderr and exit with ``code``."""
    print(message, file=sys.stderr)
    raise SystemExit(code)


def require_aiogram() -> types.ModuleType:
    """Import and return the installed :mod:`aiogram`, or exit with a clear message."""
    try:
        return importlib.import_module("aiogram")
    except ImportError as exc:  # pragma: no cover - exercised via subprocess only
        raise ToolError(f"{_INSTALL_HINT}\n\noriginal error: {exc}", EXIT_NO_AIOGRAM) from exc


def aiogram_versions() -> tuple[str, str]:
    """Return ``(aiogram_version, telegram_bot_api_version)`` from the installed package."""
    aiogram = require_aiogram()
    version = str(getattr(aiogram, "__version__", "unknown"))
    api_version = str(getattr(aiogram, "__api_version__", "unknown"))
    return version, api_version


def import_module(name: str) -> types.ModuleType:
    """Import a submodule of aiogram, converting failures into :class:`ToolError`."""
    require_aiogram()
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ToolError(
            f"cannot import {name!r} from the installed aiogram: {exc}\n"
            "the module may have been renamed or removed in this release."
        ) from exc


def public_classes(module: types.ModuleType, base: type) -> dict[str, type]:
    """Map every public subclass of ``base`` exported by ``module`` to its name."""
    found: dict[str, type] = {}
    for name in getattr(module, "__all__", None) or dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name, None)
        if inspect.isclass(obj) and issubclass(obj, base) and obj is not base:
            found[name] = obj
    return found


def field_docs(cls: type) -> dict[str, str]:
    """Extract per-attribute docstrings from a class body using :mod:`ast`.

    aiogram documents model fields with a string literal directly below each
    annotated attribute. Pydantic does not expose those, so we read them from the
    source tree rather than guessing. Returns an empty mapping when the source is
    unavailable (for example, from a zipped distribution).
    """
    try:
        source = textwrap.dedent(inspect.getsource(cls))
    except (OSError, TypeError):
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    if not tree.body or not isinstance(tree.body[0], ast.ClassDef):
        return {}

    docs: dict[str, str] = {}
    pending: str | None = None
    for node in tree.body[0].body:
        if (
            pending is not None
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            docs[pending] = " ".join(node.value.value.split())
            pending = None
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            pending = node.target.id
        else:
            pending = None
    return docs


def render_annotation(annotation: Any) -> str:
    """Render a type annotation compactly, stripping module paths from aiogram names."""
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, type):
        return annotation.__name__
    origin = typing.get_origin(annotation)
    if origin is not None:
        args = typing.get_args(annotation)
        rendered = [render_annotation(arg) for arg in args]
        if origin in (typing.Union, types.UnionType):
            return " | ".join(dict.fromkeys(rendered))
        name = getattr(origin, "__name__", str(origin))
        return f"{name}[{', '.join(rendered)}]" if rendered else name
    text = str(annotation)
    return text.replace("aiogram.types.", "").replace("aiogram.methods.", "")


def model_field_rows(model: type) -> list[dict[str, Any]]:
    """Describe a pydantic model's fields as plain dicts, required ones first."""
    fields = getattr(model, "model_fields", None)
    if not fields:
        return []
    docs = field_docs(model)
    rows: list[dict[str, Any]] = []
    for name, info in fields.items():
        rows.append(
            {
                "name": name,
                "required": bool(info.is_required()),
                "type": render_annotation(info.annotation),
                "alias": info.alias,
                "description": docs.get(name, ""),
            }
        )
    rows.sort(key=lambda row: (not row["required"], row["name"]))
    return rows


def print_field_rows(rows: Sequence[dict[str, Any]], indent: str = "  ") -> None:
    """Render field rows as readable text."""
    if not rows:
        print(f"{indent}(no fields)")
        return
    for row in rows:
        marker = "" if row["required"] else "?"
        alias = f"  (wire name: {row['alias']})" if row["alias"] else ""
        print(f"{indent}{row['name']}{marker}: {row['type']}{alias}")
        if row["description"]:
            print(wrap(row["description"], indent + "    "))


def wrap(text: str, indent: str) -> str:
    """Word-wrap ``text`` to roughly 96 columns with the given indent."""
    return textwrap.fill(
        text,
        width=96,
        initial_indent=indent,
        subsequent_indent=indent,
    )


def resolve(name: str, candidates: Iterable[str], alias: dict[str, str] | None = None) -> str:
    """Resolve ``name`` against ``candidates``, tolerating case and separator noise.

    ``alias`` maps a candidate to the canonical name it stands for. Several
    candidates that share a canonical name are not an ambiguity -- ``sendPhoto``
    and ``SendPhoto`` are two spellings of one method -- so only genuinely
    different targets are reported as ambiguous.

    Raises :class:`ToolError` with suggestions when nothing matches, so callers
    never have to guess whether a name exists.
    """
    pool = list(candidates)
    if name in pool:
        return name

    def normalize(value: str) -> str:
        return value.replace("_", "").replace("-", "").lower()

    def canonical(value: str) -> str:
        return alias.get(value, value) if alias else value

    target = normalize(name)
    exact = [c for c in pool if normalize(c) == target]
    if exact:
        distinct = {canonical(c) for c in exact}
        if len(distinct) == 1:
            return exact[0]
        raise ToolError(f"{name!r} is ambiguous: {', '.join(sorted(distinct))}")

    close = difflib.get_close_matches(name, pool, n=8, cutoff=0.6)
    substring = sorted(c for c in pool if target and target in normalize(c))
    hints = list(dict.fromkeys(close + substring))[:8]
    message = f"unknown name: {name!r}"
    if hints:
        message += "\n\ndid you mean:\n" + "\n".join(f"  {h}" for h in hints)
    else:
        message += "\n\nrun the same tool with --list to see every available name."
    raise ToolError(message)


def emit_json(payload: Any) -> None:
    """Print ``payload`` as indented JSON."""
    print(json.dumps(payload, indent=2, default=str))


def run(main: typing.Callable[[], int]) -> NoReturn:
    """Execute a tool entry point, mapping :class:`ToolError` to a clean exit."""
    try:
        raise SystemExit(main())
    except ToolError as exc:
        die(str(exc), exc.code)
    except BrokenPipeError:  # pragma: no cover - only when piped into head(1)
        raise SystemExit(EXIT_OK) from None
