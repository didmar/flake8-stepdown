"""Violation formatting for text, JSON, and diff output."""

from __future__ import annotations

import difflib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flake8_stepdown.types import Violation


def format_violations(
    violations: list[Violation],
    *,
    filename: str,
    fmt: str = "text",
) -> str:
    """Format violations for output.

    Args:
        violations: List of violations to format.
        filename: Source filename for output.
        fmt: Output format ("text" or "json").

    Returns:
        Formatted string.

    """
    if not violations:
        return ""

    if fmt == "json":
        return json.dumps(
            [
                {
                    "code": v.code,
                    "filename": filename,
                    "lineno": v.lineno,
                    "col_offset": v.col_offset,
                    "name": v.name,
                    "message": v.message,
                    "dependency": v.dependency,
                }
                for v in violations
            ],
        )

    # Text format
    lines = [f"{filename}:{v.lineno}:{v.col_offset}: {v.code} {v.message}" for v in violations]
    return "\n".join(lines)


def format_diff(original: str, rewritten: str, *, filename: str) -> str:
    """Produce a unified diff between original and rewritten source.

    Args:
        original: Original source code.
        rewritten: Rewritten source code.
        filename: Filename for diff headers.

    Returns:
        Unified diff string, or empty string if no differences.

    """
    original_lines = original.splitlines(keepends=True)
    rewritten_lines = rewritten.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        rewritten_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)
