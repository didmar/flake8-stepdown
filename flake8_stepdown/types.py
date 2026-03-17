"""Shared data structures for flake8-stepdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import libcst as cst


@dataclass(frozen=True, slots=True)
class Statement:
    """A module-level statement with its bindings and references."""

    node: cst.CSTNode
    """The LibCST syntax tree node for this statement."""
    start_line: int
    """1-based line number where the statement starts in the source file."""
    end_line: int
    """1-based line number where the statement ends."""
    bindings: frozenset[str]
    """Names defined by this statement (e.g. function/class names, assignment targets)."""
    immediate_refs: frozenset[str]
    """Names referenced at definition time (decorators, defaults, annotations, class/assignment bodies)."""
    deferred_refs: frozenset[str]
    """Names referenced inside function bodies, only resolved at call time."""
    is_overload_group: bool
    """Whether this statement is a merged group of @overload stubs plus their implementation."""


@dataclass(frozen=True, slots=True)
class Violation:
    """An ordering violation to report."""

    code: str
    """The flake8 error code (e.g. 'TDP001')."""
    lineno: int
    """1-based line number where the violation occurs."""
    col_offset: int
    """0-based column offset where the violation occurs."""
    name: str
    """Name of the symbol that is out of order."""
    message: str
    """Human-readable description of the violation."""
    dependency: str | None
    """Name of the dependency that should appear after this symbol, or None."""


@dataclass(frozen=True, slots=True)
class OrderingResult:
    """Result of ordering analysis for a module."""

    violations: list[Violation]
    """List of ordering violations found in the module."""
    reordered_source: str | None
    """The rewritten source code with corrected ordering, or None if unchanged."""
    mutual_recursion_groups: list[list[str]]
    """Groups of mutually recursive names that cannot be topologically ordered."""

    @property
    def changed(self) -> bool:
        """Whether the reordered source differs from the original."""
        return self.reordered_source is not None


@dataclass(frozen=True, slots=True)
class SegmentedModule:
    """A module split into preamble, interstitial, and postamble zones."""

    module: cst.Module
    """The parsed LibCST module tree."""
    preamble: list[cst.CSTNode]
    """Leading statements before the first reorderable block (imports, __all__, etc.)."""
    interstitials: list[cst.CSTNode]
    """Non-reorderable statements interspersed between functions (module-level constants, etc.)."""
    postamble: list[cst.CSTNode]
    """Trailing statements after the last reorderable block (if __name__ guard, etc.)."""
