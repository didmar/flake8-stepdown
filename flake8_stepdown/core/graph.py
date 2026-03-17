"""Dependency graph construction, topological sort, and SCC detection."""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from flake8_stepdown.core.parser import is_docstring, is_simple_assignment

if TYPE_CHECKING:
    from flake8_stepdown.types import Statement


def build_normalized_graph(statements: list[Statement]) -> dict[int, set[int]]:
    """Build a normalized dependency graph where edge A->B means "A must appear before B".

    - Deferred ref: A calls B -> edge A->B (caller before callee)
    - Immediate ref: A uses @B -> edge B->A (dependency before dependent)
    """
    # Build name -> index mapping
    name_to_idx: dict[str, int] = {}
    for idx, stmt in enumerate(statements):
        for name in stmt.bindings:
            name_to_idx[name] = idx

    graph: dict[int, set[int]] = {i: set() for i in range(len(statements))}

    for idx, stmt in enumerate(statements):
        # Deferred refs: caller before callee -> edge idx -> target
        for ref in stmt.deferred_refs:
            if ref in name_to_idx:
                target = name_to_idx[ref]
                if target != idx:
                    graph[idx].add(target)

        # Immediate refs: dependency before dependent -> edge target -> idx
        for ref in stmt.immediate_refs:
            if ref in name_to_idx:
                target = name_to_idx[ref]
                if target != idx:
                    graph[target].add(idx)

    return graph


def topological_sort(graph: dict[int, set[int]], num_nodes: int) -> list[int] | None:
    """Kahn's topological sort with min-heap stability tie-breaking.

    Returns ordered list of node indices, or None if a cycle is detected.
    """
    # Compute in-degrees
    in_degree = [0] * num_nodes
    for successors in graph.values():
        for s in successors:
            in_degree[s] += 1

    # Initialize min-heap with zero in-degree nodes (keyed by original index for stability)
    heap: list[int] = [i for i in range(num_nodes) if in_degree[i] == 0]
    heapq.heapify(heap)

    result: list[int] = []
    while heap:
        node = heapq.heappop(heap)
        result.append(node)
        for successor in graph.get(node, set()):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                heapq.heappush(heap, successor)

    if len(result) != num_nodes:
        return None  # Cycle detected

    return result


def find_sccs(graph: dict[int, set[int]], num_nodes: int) -> list[list[int]]:  # noqa: C901
    """Find strongly connected components with size > 1 using Tarjan's algorithm."""
    index_counter = [0]
    stack: list[int] = []
    on_stack = [False] * num_nodes
    indices = [-1] * num_nodes
    lowlinks = [-1] * num_nodes
    result: list[list[int]] = []

    def strongconnect(v: int) -> None:
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, set()):
            if indices[w] == -1:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack[w]:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            scc: list[int] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                result.append(scc)

    for v in range(num_nodes):
        if indices[v] == -1:
            strongconnect(v)

    return result


def attach_no_binding_stmts(statements: list[Statement]) -> list[list[Statement]]:
    """Group statements so that those with no bindings attach to their neighbor.

    A statement with no bindings attaches to the next statement with bindings.
    If it's the last statement, it attaches to the preceding one.

    Returns a list of groups, where each group is one or more statements
    that move together.
    """
    if not statements:
        return []

    groups: list[list[Statement]] = []
    pending: list[Statement] = []

    for stmt in statements:
        if stmt.bindings:
            # This statement has bindings — flush pending no-binding stmts as prefix
            groups.append([*pending, stmt])
            pending = []
        elif (
            groups
            and not pending
            and is_docstring(stmt.node)
            and is_simple_assignment(groups[-1][-1].node)
        ):
            # Docstring immediately after a constant — attach to the constant's group
            groups[-1].append(stmt)
        else:
            pending.append(stmt)

    # Handle trailing no-binding statements: attach to last group
    if pending:
        if groups:
            groups[-1].extend(pending)
        else:
            # All statements have no bindings — just return them as one group
            groups.append(pending)

    return groups
