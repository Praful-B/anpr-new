"""Static audit for RAKSHAK Python sources.

Walks a directory tree, parses each module with ``ast`` and reports missing
module/function/class docstrings plus functions whose code body exceeds the
configured line budget. Blank lines, comments and the docstring block are not
counted towards that budget, because §12 of PROJECT_INFO.md requires a
purpose/Args/Returns/Raises docstring on every function; the reported span is
still printed so reviewers can see the full footprint.

Exits non-zero when any violation is found so it can gate CI.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
from pathlib import Path
from typing import Iterator

MAX_FUNCTION_CODE_LINES = 40
EXCLUDED_DIRECTORY_NAMES = frozenset({"__pycache__", ".venv", "venv", "node_modules"})
LOGGER_NAME = "rakshak.audit"

LOGGER = logging.getLogger(LOGGER_NAME)


class _JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the record serialized as a JSON string.

        Args:
            record: Log record emitted by the audit run.

        Returns:
            JSON object containing the log level and message.
        """
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def configure_logging() -> None:
    """Install a JSON logging handler on the module logger.

    Returns:
        None.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    LOGGER.handlers = [handler]
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def iter_python_files(root: Path) -> Iterator[Path]:
    """Yield every Python file under ``root`` in deterministic order.

    Args:
        root: Directory to search recursively.

    Yields:
        Paths to ``*.py`` files, excluding vendored and cache directories.
    """
    for candidate in sorted(root.rglob("*.py")):
        if EXCLUDED_DIRECTORY_NAMES.intersection(candidate.parts):
            continue
        yield candidate


def has_docstring(node: ast.AST) -> bool:
    """Report whether an AST node carries a non-empty docstring.

    Args:
        node: Module, class or function node to inspect.

    Returns:
        True when the first statement is a non-empty string literal.
    """
    body = getattr(node, "body", None)
    if not body:
        return False
    first_statement = body[0]
    if not isinstance(first_statement, ast.Expr):
        return False
    value = first_statement.value
    return (
        isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and bool(value.value.strip())
    )


def docstring_lines(node: ast.AST) -> set[int]:
    """Collect the source line numbers occupied by a node's docstring.

    Args:
        node: Class or function node whose docstring should be located.

    Returns:
        set[int]: One-based line numbers belonging to the docstring.
    """
    body = getattr(node, "body", None)
    if not body:
        return set()
    first_statement = body[0]
    if not isinstance(first_statement, ast.Expr) or not isinstance(
        first_statement.value, ast.Constant
    ):
        return set()
    if not isinstance(first_statement.value.value, str):
        return set()
    start = first_statement.lineno
    end = getattr(first_statement, "end_lineno", start)
    return set(range(start, end + 1))


def count_code_lines(node: ast.AST, source_lines: list[str]) -> int:
    """Count the meaningful code lines of a function definition.

    The signature, body statements and closing bracket count; blank lines,
    comment-only lines and the docstring block do not.

    Args:
        node: Function node exposing ``lineno`` and ``end_lineno``.
        source_lines: Every line of the module, indexed from zero.

    Returns:
        int: Number of code lines in the definition.
    """
    end_line = getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)
    ignored = docstring_lines(node)
    counted = 0
    for line_number in range(getattr(node, "lineno", 0), end_line + 1):
        if line_number in ignored:
            continue
        text = source_lines[line_number - 1].strip()
        if not text or text.startswith("#"):
            continue
        counted += 1
    return counted


def function_span(node: ast.AST) -> int:
    """Measure the inclusive line span of a function definition.

    Args:
        node: Function node that exposes ``lineno`` and ``end_lineno``.

    Returns:
        Number of source lines the definition occupies.
    """
    end_line = getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)
    return end_line - getattr(node, "lineno", 0) + 1


def audit_definition(node: ast.AST, path: Path, source_lines: list[str]) -> list[str]:
    """Check a single class or function definition for violations.

    Args:
        node: The class or function node to inspect.
        path: File the node was parsed from, used in messages.
        source_lines: Every line of the module, indexed from zero.

    Returns:
        list[str]: Violation strings for the definition, empty when clean.
    """
    is_class = isinstance(node, ast.ClassDef)
    kind = "class" if is_class else "function"
    violations: list[str] = []

    if not has_docstring(node):
        violations.append(f"{path}:{node.lineno}: missing {kind} docstring ({node.name})")

    if not is_class:
        code_lines = count_code_lines(node, source_lines)
        if code_lines > MAX_FUNCTION_CODE_LINES:
            violations.append(
                f"{path}:{node.lineno}: function too long "
                f"({node.name}={code_lines} > {MAX_FUNCTION_CODE_LINES} code lines, "
                f"span={function_span(node)})"
            )
    return violations


def audit_file(path: Path) -> list[str]:
    """Collect every violation found in a single Python module.

    Args:
        path: File to parse and inspect.

    Returns:
        Human-readable violation strings, empty when the module is clean.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return [f"{path}: unreadable ({error})"]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return [f"{path}:{error.lineno}: syntax error ({error.msg})"]

    source_lines = source.splitlines()
    violations: list[str] = []
    if not has_docstring(tree):
        violations.append(f"{path}:1: missing module docstring")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            violations.extend(audit_definition(node, path, source_lines))
    return violations


def audit_roots(roots: list[Path]) -> tuple[list[str], int]:
    """Audit every Python file reachable from the given roots.

    Args:
        roots: Directories to scan.

    Returns:
        tuple[list[str], int]: Aggregated violation strings across all roots
        and the number of modules that were actually parsed.
    """
    violations: list[str] = []
    scanned_files = 0
    for root in roots:
        if not root.is_dir():
            violations.append(f"{root}: not a directory")
            continue
        for module_path in iter_python_files(root):
            scanned_files += 1
            violations.extend(audit_file(module_path))
    return violations, scanned_files


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments for the audit.

    Args:
        argv: Argument list, typically ``sys.argv[1:]``.

    Returns:
        Namespace holding the resolved root directories.
    """
    parser = argparse.ArgumentParser(
        description="Audit RAKSHAK Python docstrings and function lengths."
    )
    parser.add_argument(
        "roots",
        nargs="*",
        default=["backend"],
        help="Directories to audit (default: backend).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the audit and report the outcome through structured logging.

    Args:
        argv: Command-line arguments excluding the program name.

    Returns:
        Process exit code: 0 when clean, 1 when violations were found.
    """
    configure_logging()
    arguments = parse_arguments(argv)
    roots = [Path(root) for root in arguments.roots]
    violations, scanned_files = audit_roots(roots)
    for violation in violations:
        LOGGER.error(violation)
    LOGGER.info(
        f"roots={len(roots)} files_scanned={scanned_files} "
        f"violations={len(violations)}"
    )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
