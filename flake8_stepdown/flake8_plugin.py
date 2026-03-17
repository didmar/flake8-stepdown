"""Flake8 plugin for top-down function ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flake8_stepdown import __version__
from flake8_stepdown.core.ordering import order_module

if TYPE_CHECKING:
    import ast
    from collections.abc import Generator


class TopDownChecker:
    """Flake8 checker for top-down function ordering."""

    name = "flake8-stepdown"
    version = __version__

    def __init__(
        self,
        tree: ast.AST,  # noqa: ARG002
        filename: str,
        lines: list[str],
    ) -> None:
        """Initialize the checker."""
        self.filename = filename
        self.lines = lines

    def run(self) -> Generator[tuple[int, int, str, type]]:
        """Yield violations as (line, col, message, type) tuples."""
        source = "".join(self.lines)
        result = order_module(source, compute_rewrite=False)

        for violation in result.violations:
            yield (
                violation.lineno,
                violation.col_offset,
                f"{violation.code} {violation.message}",
                type(self),
            )
