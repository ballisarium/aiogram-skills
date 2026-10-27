#!/usr/bin/env python3
"""Extract Python examples from Markdown and verify them against installed aiogram.

Every fenced ``python`` block in a skill is checked. By default a block is
*executed* in an isolated subprocess with networking disabled, which proves that
the imports resolve, the decorators accept their filters, and the builders accept
their arguments. Blocks are never executed against Telegram: the module runs
under a non-``__main__`` name, so an ``if __name__ == "__main__":`` guard keeps
``run_polling`` and friends from ever starting.

Per-block behaviour is set with an HTML comment on the line before the fence:

* ``<!-- example: run -->``    execute the block (this is the default)
* ``<!-- example: static -->`` syntax and import resolution only, no execution
* ``<!-- example: skip -->``   syntax only; use for deliberate anti-patterns
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import inspect
import re
import subprocess
import sys
import tempfile
import textwrap
import typing
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import EXIT_NOT_FOUND, EXIT_OK, ToolError, emit_json, run

FENCE = re.compile(r"^```(?P<info>[^\n]*)$")
MARKER = re.compile(r"<!--\s*example:\s*(?P<mode>run|static|skip)\s*-->")
MODES = ("run", "static", "skip")
FAKE_TOKEN = "123456:AAExampleTokenNotRealDoNotUse"
TIMEOUT_SECONDS = 60

# Executed inside the subprocess before the example. Blocks outbound sockets so a
# stray network call fails loudly instead of reaching Telegram.
PRELUDE = """
import socket
import sys


class _BlockedSocket(socket.socket):
    def connect(self, *args, **kwargs):
        raise RuntimeError("network access is blocked while validating skill examples")

    def connect_ex(self, *args, **kwargs):
        raise RuntimeError("network access is blocked while validating skill examples")


socket.socket = _BlockedSocket
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(
    RuntimeError("network access is blocked while validating skill examples")
)

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    source = handle.read()

namespace = {"__name__": "__skill_example__", "__file__": path}
exec(compile(source, path, "exec"), namespace)
"""


@dataclass
class Block:
    """One fenced Python block lifted out of a Markdown file."""

    path: Path
    line: int
    mode: str
    source: str

    @property
    def label(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class Result:
    """Outcome of checking a single block."""

    block: Block
    status: str
    detail: str = ""


@dataclass
class Summary:
    """Aggregate outcome across every checked block."""

    results: list[Result] = field(default_factory=list)

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if r.status == "FAIL"]

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts


def extract(path: Path) -> list[Block]:
    """Pull every fenced ``python`` block out of a Markdown file."""
    blocks: list[Block] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    pending_mode = "run"
    while index < len(lines):
        line = lines[index]
        marker = MARKER.search(line)
        if marker:
            pending_mode = marker.group("mode")
            index += 1
            continue
        match = FENCE.match(line)
        if not match:
            if line.strip():
                pending_mode = "run"
            index += 1
            continue

        info = match.group("info").strip()
        start = index + 1
        end = start
        while end < len(lines) and not lines[end].startswith("```"):
            end += 1
        if info.split()[0:1] == ["python"]:
            blocks.append(
                Block(
                    path=path,
                    line=index + 1,
                    mode=pending_mode,
                    source="\n".join(lines[start:end]) + "\n",
                )
            )
        pending_mode = "run"
        index = end + 1
    return blocks


def check_syntax(block: Block) -> str | None:
    """Compile the block; return an error string on failure."""
    try:
        compile(block.source, block.label, "exec")
    except SyntaxError as exc:
        return f"syntax error on block line {exc.lineno}: {exc.msg}"
    return None


def imported_names(source: str) -> list[tuple[str, str | None]]:
    """Collect ``(module, attribute)`` pairs for every import in the block."""
    pairs: list[tuple[str, str | None]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            pairs.extend((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            pairs.extend((node.module, alias.name) for alias in node.names)
    return pairs


def check_imports(block: Block) -> str | None:
    """Verify that every imported module and name actually exists."""
    problems: list[str] = []
    for module_name, attribute in imported_names(block.source):
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            problems.append(f"cannot import module {module_name!r}: {exc}")
            continue
        if attribute is None or attribute == "*":
            continue
        if hasattr(module, attribute):
            continue
        if importlib.util.find_spec(f"{module_name}.{attribute}") is not None:
            continue
        problems.append(f"{module_name!r} has no attribute {attribute!r}")
    return "; ".join(problems) if problems else None


def _known_symbols(source: str) -> dict[str, type]:
    """Map local names bound by imports to the aiogram classes they refer to."""
    symbols: dict[str, type] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not node.module or not node.module.startswith("aiogram") or node.level:
            continue
        try:
            module = importlib.import_module(node.module)
        except ImportError:
            continue
        for alias in node.names:
            obj = getattr(module, alias.name, None)
            if isinstance(obj, type):
                symbols[alias.asname or alias.name] = obj
    return symbols


def _model_fields(cls: type) -> dict[str, Any]:
    """The pydantic ``model_fields`` mapping of ``cls``, or an empty dict."""
    fields = getattr(cls, "model_fields", None)
    return fields if isinstance(fields, dict) else {}


def _field_type(cls: type, attribute: str) -> type | None:
    """The aiogram class a model field resolves to, ignoring ``| None``.

    Returns ``None`` when the field is absent, is not a model, or is a union of
    several models -- in those cases the chain walk stops rather than guessing.
    """
    fields = _model_fields(cls)
    if attribute not in fields:
        return None
    annotation = fields[attribute].annotation
    candidates = [
        arg
        for arg in (typing.get_args(annotation) or [annotation])
        if isinstance(arg, type) and arg is not type(None)
    ]
    if len(candidates) != 1:
        return None
    resolved = candidates[0]
    return resolved if _model_fields(resolved) else None


@cache
def _instance_members(cls: type) -> frozenset[str]:
    """Read constructor assignments without instantiating a bot, session or storage."""
    members: set[str] = set()
    for base in cls.__mro__:
        constructor = base.__dict__.get("__init__")
        if constructor is None:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(constructor)))
        except (OSError, TypeError, IndentationError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
            ):
                members.add(node.attr)
    return frozenset(members)


def _member_exists(cls: type, attribute: str) -> bool:
    """True when ``attribute`` is a real field, shortcut, or class member of ``cls``.

    Pydantic v2 keeps declared fields out of the class namespace, so ``hasattr`` alone
    reports false negatives for things like ``Message.text``. Check ``model_fields`` too.
    """
    if hasattr(cls, attribute) or attribute in _instance_members(cls):
        return True
    return any(attribute in _model_fields(base) for base in cls.__mro__)


def check_attributes(block: Block) -> str | None:
    """Verify attribute access on aiogram-annotated parameters.

    Handler bodies are not executed by :func:`execute` -- the decorator only registers
    them -- so a typo like ``message.answr(...)`` would otherwise slip through. This
    resolves each parameter annotated with an imported aiogram class and checks every
    attribute read against the real class. Parameters that are reassigned inside the
    function are skipped, so shadowing cannot produce a false positive.
    """
    tree = ast.parse(block.source)
    symbols = _known_symbols(block.source)
    if not symbols:
        return None

    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        typed: dict[str, type] = {}
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        for argument in arguments:
            annotation = argument.annotation
            if isinstance(annotation, ast.Name) and annotation.id in symbols:
                typed[argument.arg] = symbols[annotation.id]
        if not typed:
            continue

        for inner in ast.walk(node):
            # Reassignment rebinds the name to an unknown type.
            target = None
            if isinstance(inner, ast.Assign):
                target = inner.targets
            elif isinstance(inner, ast.AnnAssign | ast.AugAssign):
                target = [inner.target]
            for item in target or []:
                if isinstance(item, ast.Name):
                    typed.pop(item.id, None)

            # isinstance() narrowing means later attribute access is against the
            # narrowed type, not the annotation. Stop tracking rather than guess.
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "isinstance"
                and inner.args
                and isinstance(inner.args[0], ast.Name)
            ):
                typed.pop(inner.args[0].id, None)

        for inner in ast.walk(node):
            if not isinstance(inner, ast.Attribute):
                continue

            # Flatten `a.b.c` into (base_name, ["b", "c"]).
            chain: list[str] = []
            cursor: ast.expr = inner
            while isinstance(cursor, ast.Attribute):
                chain.append(cursor.attr)
                cursor = cursor.value
            if not isinstance(cursor, ast.Name):
                continue
            chain.reverse()

            cls = typed.get(cursor.id)
            if cls is None:
                continue

            path = cursor.id
            for attribute in chain:
                if not _member_exists(cls, attribute):
                    problems.append(
                        f"{node.name}(): {path}.{attribute} does not exist on "
                        f"{cls.__name__} (block line {inner.lineno})"
                    )
                    break
                path = f"{path}.{attribute}"
                next_cls = _field_type(cls, attribute)
                if next_cls is None:
                    break  # not a model field; stop rather than guess
                cls = next_cls
    return "; ".join(dict.fromkeys(problems)) if problems else None


def execute(block: Block) -> str | None:
    """Run the block in a subprocess with networking blocked."""
    with tempfile.TemporaryDirectory() as tmp:
        example = Path(tmp) / "example.py"
        example.write_text(block.source, encoding="utf-8")
        driver = Path(tmp) / "driver.py"
        driver.write_text(PRELUDE, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(driver), str(example)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=tmp,
                env=_child_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"execution exceeded {TIMEOUT_SECONDS}s (did the example start polling?)"
    if completed.returncode == 0:
        return None
    tail = (completed.stderr or completed.stdout).strip().splitlines()
    return "\n".join(tail[-12:]) if tail else f"exited with code {completed.returncode}"


def _child_env() -> dict[str, str]:
    """Environment for the example subprocess: fake secrets, no real ones."""
    import os

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.endswith(("TOKEN", "SECRET", "KEY", "PASSWORD"))
    }
    env["BOT_TOKEN"] = FAKE_TOKEN
    env["TELEGRAM_BOT_TOKEN"] = FAKE_TOKEN
    env["PYTHONPATH"] = os.pathsep.join([*sys.path[:1], env.get("PYTHONPATH", "")]).strip(
        os.pathsep
    )
    return env


def check(block: Block) -> Result:
    """Apply the checks appropriate to the block's mode."""
    syntax_error = check_syntax(block)
    if syntax_error:
        return Result(block, "FAIL", syntax_error)
    if block.mode == "skip":
        return Result(block, "SKIPPED", "syntax only (marked skip)")

    import_error = check_imports(block)
    if import_error:
        return Result(block, "FAIL", import_error)

    attribute_error = check_attributes(block)
    if attribute_error:
        return Result(block, "FAIL", attribute_error)

    if block.mode == "static":
        return Result(block, "PASS", "syntax + imports + attributes (marked static)")

    runtime_error = execute(block)
    if runtime_error:
        return Result(block, "FAIL", runtime_error)
    return Result(block, "PASS", "syntax + imports + attributes + execution")


def collect(paths: list[Path]) -> list[Path]:
    """Expand directories into the Markdown files they contain."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.md") if ".venv" not in p.parts))
        elif path.suffix == ".md":
            files.append(path)
        else:
            raise ToolError(f"not a Markdown file or directory: {path}")
    if not files:
        raise ToolError("no Markdown files found in the given paths")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="validate-example.py",
        description=(
            "Extract fenced python blocks from Markdown and verify them against the "
            "installed aiogram: syntax, import resolution, and (by default) execution "
            "in a subprocess with networking blocked. Exits 1 if any block fails."
        ),
        epilog=(
            "block modes, set with an HTML comment above the fence:\n"
            "  <!-- example: run -->     execute the block (default)\n"
            "  <!-- example: static -->  syntax and imports only\n"
            "  <!-- example: skip -->    syntax only, for deliberate anti-patterns\n"
            "\n"
            "examples:\n"
            "  python using-aiogram/tools/validate-example.py .\n"
            "  python using-aiogram/tools/validate-example.py aiogram-fsm/SKILL.md -v"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown files or directories")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print every block, not just failures"
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="downgrade every 'run' block to 'static' (fast pre-check)",
    )
    args = parser.parse_args()

    blocks: list[Block] = []
    for path in collect(args.paths):
        blocks.extend(extract(path))

    if args.no_run:
        blocks = [
            Block(b.path, b.line, "static" if b.mode == "run" else b.mode, b.source) for b in blocks
        ]

    summary = Summary([check(block) for block in blocks])

    if args.json:
        emit_json(
            {
                "counts": summary.counts(),
                "results": [
                    {
                        "file": str(r.block.path),
                        "line": r.block.line,
                        "mode": r.block.mode,
                        "status": r.status,
                        "detail": r.detail,
                    }
                    for r in summary.results
                ],
            }
        )
        return EXIT_NOT_FOUND if summary.failures else EXIT_OK

    for result in summary.results:
        if result.status == "FAIL" or args.verbose:
            print(f"{result.status:8} {result.block.label}  [{result.block.mode}]")
            if result.detail and (args.verbose or result.status == "FAIL"):
                for line in result.detail.splitlines():
                    print(f"         {line}")

    counts = summary.counts()
    print()
    print(
        f"{len(summary.results)} block(s): "
        + ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    )
    return EXIT_NOT_FOUND if summary.failures else EXIT_OK


if __name__ == "__main__":
    run(main)
