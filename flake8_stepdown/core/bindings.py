"""Extract bindings (defined names) from module-level statements."""

from __future__ import annotations

from typing import TYPE_CHECKING

import libcst as cst
import libcst.matchers as m

from flake8_stepdown.types import Statement

if TYPE_CHECKING:
    from collections.abc import Mapping


def extract_bindings(
    statements: list[cst.CSTNode],
    positions: Mapping[cst.CSTNode, cst.metadata.CodeRange],
) -> list[Statement]:
    """Extract bindings from module-level statements.

    Args:
        statements: The module-level CST nodes to analyze (functions, classes,
            and assignments from the reorderable zone between preamble and postamble).
        positions: Position mapping from MetadataWrapper.resolve(PositionProvider).

    Groups consecutive @overload stubs with their implementation into a single Statement.
    Returns Statement objects with empty refs (to be populated by references module).

    """
    result: list[Statement] = []
    i = 0
    nodes = list(statements)

    while i < len(nodes):
        node = nodes[i]

        # Check for @overload grouping
        if isinstance(node, cst.FunctionDef) and _has_overload_decorator(node):
            func_name = node.name.value
            group_nodes: list[cst.CSTNode] = [node]

            # Collect consecutive same-name functions
            j = i + 1
            while j < len(nodes):
                next_node = nodes[j]
                if isinstance(next_node, cst.FunctionDef) and next_node.name.value == func_name:
                    group_nodes.append(next_node)
                    if not _has_overload_decorator(next_node):
                        j += 1
                        break
                    j += 1
                else:
                    break

            # Merge if stubs + implementation (>1 node and last is not overload)
            last_node = group_nodes[-1]
            if (
                len(group_nodes) > 1
                and isinstance(last_node, cst.FunctionDef)
                and not _has_overload_decorator(last_node)
            ):
                first_pos = positions.get(group_nodes[0])
                last_pos = positions.get(last_node)
                result.append(
                    Statement(
                        node=last_node,
                        start_line=first_pos.start.line if first_pos else 0,
                        end_line=last_pos.end.line if last_pos else 0,
                        bindings=frozenset({func_name}),
                        immediate_refs=frozenset(),
                        deferred_refs=frozenset(),
                        is_overload_group=True,
                    ),
                )
                i = j
                continue

            # Not a complete overload group — fall through to normal handling

        # Normal statement
        pos = positions.get(node)
        start_line = pos.start.line if pos else 0
        end_line = pos.end.line if pos else 0

        bindings = (
            _extract_binding_names(node) if isinstance(node, cst.BaseStatement) else frozenset()
        )
        result.append(
            Statement(
                node=node,
                start_line=start_line,
                end_line=end_line,
                bindings=bindings,
                immediate_refs=frozenset(),
                deferred_refs=frozenset(),
                is_overload_group=False,
            ),
        )
        i += 1

    return result


def _extract_binding_names(node: cst.BaseStatement) -> frozenset[str]:
    """Extract the names defined by a single statement."""
    if isinstance(node, cst.FunctionDef):
        return frozenset({node.name.value})

    if isinstance(node, cst.ClassDef):
        return frozenset({node.name.value})

    if isinstance(node, cst.SimpleStatementLine):
        names: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, cst.Assign):
                for target in stmt.targets:
                    names |= _collect_names(target.target)
            elif isinstance(stmt, cst.AnnAssign) and stmt.value is not None:
                names |= _collect_names(stmt.target)
        return frozenset(names)

    return frozenset()


def _collect_names(target: cst.BaseExpression) -> set[str]:
    """Recursively collect all Name identifiers from an assignment target."""
    if isinstance(target, cst.Name):
        return {target.value}
    if isinstance(target, cst.Tuple):
        names: set[str] = set()
        for element in target.elements:
            names |= _collect_names(element.value)
        return names
    return set()


def _has_overload_decorator(node: cst.FunctionDef) -> bool:
    """Check if a FunctionDef has @typing.overload or @overload."""
    for decorator in node.decorators:
        dec = decorator.decorator
        if m.matches(dec, m.Name("overload")):
            return True
        if m.matches(dec, m.Attribute(value=m.Name("typing"), attr=m.Name("overload"))):
            return True
    return False
