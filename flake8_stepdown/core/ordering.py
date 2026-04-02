"""Orchestrator: parse -> segment -> bindings -> refs -> graph -> sort -> violations."""

from __future__ import annotations

from flake8_stepdown.core.bindings import extract_bindings
from flake8_stepdown.core.graph import (
    attach_no_binding_stmts,
    build_normalized_graph,
    find_sccs,
    topological_sort,
)
from flake8_stepdown.core.parser import compute_line_numbers, parse_source, segment
from flake8_stepdown.core.references import detect_future_annotations, extract_refs
from flake8_stepdown.rewriter import rewrite
from flake8_stepdown.types import OrderingResult, Statement, Violation

_EMPTY_RESULT = OrderingResult(violations=[], reordered_source=None, mutual_recursion_groups=[])


def order_module(source: str, *, compute_rewrite: bool = True) -> OrderingResult:
    """Analyze and determine the correct ordering for a Python module.

    Args:
        source: Python source code.
        compute_rewrite: Whether to compute the reordered source (default True).
            Set to False when only violations are needed (e.g. flake8 plugin, check command).

    Returns:
        OrderingResult with violations and optionally reordered source.

    """
    if not source.strip():
        return _EMPTY_RESULT

    module = parse_source(source)
    positions = compute_line_numbers(source, module)
    seg = segment(module)

    if not seg.interstitials:
        return _EMPTY_RESULT

    # Extract bindings
    statements = extract_bindings(seg.interstitials, positions)

    # Extract references
    has_future = detect_future_annotations(seg.preamble)
    statements = extract_refs(statements, has_future_annotations=has_future)

    # Attach no-binding statements
    groups = attach_no_binding_stmts(statements)

    # Build merged statements for graph (one per group)
    merged: list[Statement] = []
    for group in groups:
        # Merge bindings and refs from all statements in the group
        all_bindings: frozenset[str] = frozenset().union(*(s.bindings for s in group))
        all_immediate: frozenset[str] = frozenset().union(*(s.immediate_refs for s in group))
        all_deferred: frozenset[str] = frozenset().union(*(s.deferred_refs for s in group))
        merged.append(
            Statement(
                node=group[0].node,
                start_line=group[0].start_line,
                end_line=group[-1].end_line,
                bindings=all_bindings,
                immediate_refs=all_immediate,
                deferred_refs=all_deferred,
                is_overload_group=group[0].is_overload_group,
            ),
        )

    # Build graph and sort
    graph = build_normalized_graph(merged)
    num_nodes = len(merged)

    # Detect SCCs
    sccs = find_sccs(graph, num_nodes)

    # For SCCs: remove internal edges and preserve original order
    for scc in sccs:
        scc_set = set(scc)
        for node in scc:
            graph[node] = {s for s in graph[node] if s not in scc_set}

    # Topological sort
    new_order = topological_sort(graph, num_nodes)

    if new_order is None:
        # Remaining cycles after SCC removal — shouldn't happen but handle gracefully
        new_order = list(range(num_nodes))

    # Check if order changed
    changed = new_order != list(range(num_nodes))

    # Generate violations and mutual recursion info
    violations = _generate_violations(merged, new_order)
    mutual_recursion_groups = _extract_mutual_recursion_groups(merged, sccs)

    # Rewrite source if order changed and rewrite requested
    reordered_source = None
    if changed and compute_rewrite:
        # Expand group order back to individual statement order
        expanded_order: list[int] = []
        offsets = []
        offset = 0
        for group in groups:
            offsets.append(offset)
            offset += len(group)

        for group_idx in new_order:
            group = groups[group_idx]
            base = offsets[group_idx]
            expanded_order.extend(base + j for j in range(len(group)))

        all_nodes = [s.node for group in groups for s in group]

        reordered_source = rewrite(
            seg.module,
            seg.preamble,
            all_nodes,
            seg.postamble,
            expanded_order,
        )

    return OrderingResult(
        violations=violations,
        reordered_source=reordered_source,
        mutual_recursion_groups=mutual_recursion_groups,
    )


def _generate_violations(
    statements: list[Statement],
    new_order: list[int],
) -> list[Violation]:
    """Generate TDP001 violations from ordering differences."""
    violations: list[Violation] = []

    # Map from original index to new position
    new_position = {orig_idx: new_pos for new_pos, orig_idx in enumerate(new_order)}

    for orig_idx, stmt in enumerate(statements):
        new_pos = new_position[orig_idx]
        if new_pos != orig_idx:
            # Find what it should come before
            name = next(iter(stmt.bindings), "<unnamed>")
            # Find the first statement that this one should precede
            for other_idx in new_order:
                if other_idx == orig_idx:
                    break
                other = statements[other_idx]
                other_name = next(iter(other.bindings), "<unnamed>")
                violations.append(
                    Violation(
                        code="TDP001",
                        lineno=stmt.start_line,
                        col_offset=0,
                        name=name,
                        message=f"{name} should appear after {other_name}",
                        dependency=other_name,
                    ),
                )
                break

    return violations


def _extract_mutual_recursion_groups(
    statements: list[Statement],
    sccs: list[list[int]],
) -> list[list[str]]:
    """Extract mutual recursion groups from SCCs as lists of function names."""
    groups: list[list[str]] = []
    for scc in sccs:
        names = sorted(
            {n for idx in scc for n in statements[idx].bindings},
        )
        if names:
            groups.append(names)
    return groups
