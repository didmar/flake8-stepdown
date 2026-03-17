"""Extract immediate and deferred references from statements."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import libcst as cst
import libcst.matchers as m

if TYPE_CHECKING:
    from flake8_stepdown.types import Statement


def detect_future_annotations(preamble: list[cst.CSTNode]) -> bool:
    """Check if ``from __future__ import annotations`` is in the preamble."""
    for node in preamble:
        if m.matches(
            node,
            m.SimpleStatementLine(
                body=[
                    m.ImportFrom(
                        module=m.Attribute(value=m.Name("__future__"), attr=m.Name())
                        | m.Name("__future__"),
                    ),
                ],
            ),
        ):
            stmt = node
            if isinstance(stmt, cst.SimpleStatementLine):
                imp = stmt.body[0]
                if isinstance(imp, cst.ImportFrom) and isinstance(imp.names, (list, tuple)):
                    for alias in imp.names:
                        if isinstance(alias, cst.ImportAlias):
                            name = alias.name
                            if isinstance(name, cst.Name) and name.value == "annotations":
                                return True
    return False


def extract_refs(
    statements: list[Statement],
    *,
    has_future_annotations: bool,
) -> list[Statement]:
    """Populate immediate and deferred refs for each statement.

    Args:
        statements: Statements with bindings already extracted.
        has_future_annotations: Whether ``from __future__ import annotations`` is active.

    Returns:
        New list of Statement objects with refs populated.

    """
    # Build lookup: name -> (statement_index, kind)
    all_bindings: dict[str, tuple[int, str]] = {}
    for idx, stmt in enumerate(statements):
        kind = _binding_kind(stmt.node)
        for name in stmt.bindings:
            all_bindings[name] = (idx, kind)

    result: list[Statement] = []
    for idx, stmt in enumerate(statements):
        node = stmt.node

        if isinstance(node, cst.FunctionDef):
            immediate, deferred = _extract_function_refs(
                node,
                idx,
                all_bindings,
                has_future_annotations=has_future_annotations,
            )
        elif isinstance(node, cst.ClassDef):
            immediate, deferred = _extract_class_refs(node, idx, all_bindings)
        elif isinstance(node, cst.SimpleStatementLine):
            immediate = _extract_non_function_refs(node, idx, all_bindings)
            deferred = set()
        else:
            immediate = set()
            deferred = set()

        # Filter to only known bindings (not self-referencing)
        immediate = {n for n in immediate if n in all_bindings and all_bindings[n][0] != idx}
        deferred = {n for n in deferred if n in all_bindings and all_bindings[n][0] != idx}

        result.append(
            replace(stmt, immediate_refs=frozenset(immediate), deferred_refs=frozenset(deferred)),
        )

    return result


def _binding_kind(node: cst.CSTNode) -> str:
    """Determine whether a node defines a function, class, or constant."""
    if isinstance(node, cst.FunctionDef):
        return "function"
    if isinstance(node, cst.ClassDef):
        return "class"
    return "constant"


def _extract_function_refs(
    node: cst.FunctionDef,
    idx: int,
    all_bindings: dict[str, tuple[int, str]],
    *,
    has_future_annotations: bool,
) -> tuple[set[str], set[str]]:
    """Extract immediate and deferred refs from a FunctionDef."""
    immediate: set[str] = set()
    deferred: set[str] = set()

    immediate.update(_collect_decorator_refs(node))
    immediate.update(_collect_default_refs(node))

    if not has_future_annotations:
        immediate.update(_collect_annotation_refs(node))

    _classify_body_refs(node, idx, all_bindings, immediate, deferred)

    return immediate, deferred


def _extract_class_refs(
    node: cst.ClassDef,
    idx: int,
    all_bindings: dict[str, tuple[int, str]],
) -> tuple[set[str], set[str]]:
    """Extract immediate and deferred refs from a ClassDef.

    Immediate: decorators, base classes, metaclass kwargs, and direct class-body statements.
    Deferred: refs inside method bodies (function refs → deferred, constant refs → immediate).
    """
    immediate: set[str] = set()
    deferred: set[str] = set()

    immediate.update(_collect_decorator_refs(node))
    for arg in node.bases:
        immediate.update(_collect_names(arg.value))
    for kw in node.keywords:
        immediate.update(_collect_names(kw.value))

    body = node.body
    if isinstance(body, cst.IndentedBlock):
        for stmt in body.body:
            if isinstance(stmt, cst.FunctionDef):
                # Method signature parts execute at class definition time → immediate
                immediate.update(_collect_decorator_refs(stmt))
                immediate.update(_collect_default_refs(stmt))
                immediate.update(_collect_annotation_refs(stmt))
                # Method body refs: function → deferred, constant/class → immediate
                _classify_body_refs(stmt, idx, all_bindings, immediate, deferred)
            else:
                # Direct class-body statements (class variables, etc.) → immediate
                immediate.update(_collect_names(stmt))

    return immediate, deferred


def _classify_body_refs(
    node: cst.CSTNode,
    idx: int,
    all_bindings: dict[str, tuple[int, str]],
    immediate: set[str],
    deferred: set[str],
) -> None:
    """Classify body refs as immediate or deferred based on binding kind."""
    for name in _collect_body_refs(node):
        if name not in all_bindings or all_bindings[name][0] == idx:
            continue
        _, kind = all_bindings[name]
        if kind == "function":
            deferred.add(name)
        else:
            immediate.add(name)


def _collect_decorator_refs(node: cst.FunctionDef | cst.ClassDef) -> set[str]:
    """Collect name references from decorators."""
    names: set[str] = set()
    for decorator in node.decorators:
        names.update(_collect_names(decorator.decorator))
    return names


def _collect_default_refs(func: cst.FunctionDef) -> set[str]:
    """Collect name references from default argument values."""
    names: set[str] = set()
    for param in func.params.params:
        if param.default is not None:
            names.update(_collect_names(param.default))
    for param in func.params.kwonly_params:
        if param.default is not None:
            names.update(_collect_names(param.default))
    if func.params.star_kwarg and func.params.star_kwarg.default:
        names.update(_collect_names(func.params.star_kwarg.default))
    return names


def _collect_annotation_refs(func: cst.FunctionDef) -> set[str]:
    """Collect name references from type annotations in signature."""
    names: set[str] = set()
    for param in (*func.params.params, *func.params.kwonly_params, *func.params.posonly_params):
        if param.annotation is not None:
            names.update(_collect_annotation_names(param.annotation.annotation))
    if func.params.star_kwarg and func.params.star_kwarg.annotation:
        names.update(_collect_annotation_names(func.params.star_kwarg.annotation.annotation))
    star_arg = func.params.star_arg
    if isinstance(star_arg, cst.Param) and star_arg.annotation:
        names.update(_collect_annotation_names(star_arg.annotation.annotation))
    if func.returns is not None:
        names.update(_collect_annotation_names(func.returns.annotation))
    return names


def _collect_annotation_names(node: cst.CSTNode) -> set[str]:
    """Collect name references from an annotation node, including string annotations."""
    names = _collect_names(node)
    if isinstance(node, cst.SimpleString):
        value = node.evaluated_value
        if isinstance(value, str) and value.isidentifier():
            names.add(value)
    return names


def _extract_non_function_refs(
    node: cst.SimpleStatementLine,
    idx: int,
    all_bindings: dict[str, tuple[int, str]],
) -> set[str]:
    """Extract immediate refs from a simple statement line."""
    body_names: set[str] = set()
    for s in node.body:
        if isinstance(s, (cst.Assign, cst.AnnAssign)) and s.value is not None:
            body_names.update(_collect_names(s.value))
    return {n for n in body_names if n in all_bindings and all_bindings[n][0] != idx}


def _collect_body_refs(node: cst.CSTNode) -> set[str]:
    """Collect all name references from a function/class body."""
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)):
        return _collect_names(node.body)
    return set()


def _collect_names(node: cst.CSTNode) -> set[str]:
    """Collect all Name references from a CST subtree via recursive traversal."""
    names: set[str] = set()
    _walk_for_names(node, names)
    return names


def _walk_for_names(node: cst.CSTNode, names: set[str]) -> None:
    """Recursively walk a CST node tree collecting Name values."""
    if isinstance(node, cst.Name):
        names.add(node.value)
        return
    for child in node.children:
        _walk_for_names(child, names)
