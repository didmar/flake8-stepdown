"""Generate a Graphviz DOT dependency graph from a Python source file.

Uses the flake8-stepdown pipeline to extract bindings and references,
then produces a DOT file that distinguishes deferred vs immediate edges
and highlights mutual recursion (SCC) groups.

Usage:
    uv run python scripts/depgraph.py mymodule.py > graph.dot
    dot -Tpng graph.dot -o graph.png
"""

from __future__ import annotations

import argparse
import sys
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from flake8_stepdown.core.bindings import extract_bindings
from flake8_stepdown.core.graph import (
    attach_no_binding_stmts,
    build_normalized_graph,
    find_sccs,
    topological_sort,
)
from flake8_stepdown.core.parser import parse_source, segment
from flake8_stepdown.core.references import detect_future_annotations, extract_refs
from flake8_stepdown.types import Statement


class EdgeKind(Enum):
    DEFERRED = "deferred"
    IMMEDIATE = "immediate"


class TypedEdge(NamedTuple):
    source: int
    target: int
    kind: EdgeKind
    ref_name: str


def _extract_merged_statements(source: str) -> list[Statement]:
    """Run the pipeline up to merged statements (mirrors ordering.py)."""
    from flake8_stepdown.core.parser import compute_line_numbers

    module = parse_source(source)
    positions = compute_line_numbers(source, module)
    seg = segment(module)

    if not seg.interstitials:
        return []

    statements = extract_bindings(seg.interstitials, positions)
    has_future = detect_future_annotations(seg.preamble)
    statements = extract_refs(statements, has_future_annotations=has_future)
    groups = attach_no_binding_stmts(statements)

    merged: list[Statement] = []
    for group in groups:
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
    return merged


def _build_typed_edges(statements: list[Statement]) -> list[TypedEdge]:
    """Build edges preserving the deferred/immediate distinction.

    Edge direction is normalized: source -> target means "source before target".
    - Deferred ref (call): caller -> callee
    - Immediate ref (decorator, default): dependency -> dependent
    """
    name_to_idx: dict[str, int] = {}
    for idx, stmt in enumerate(statements):
        for name in stmt.bindings:
            name_to_idx[name] = idx

    edges: list[TypedEdge] = []
    seen: set[tuple[int, int, EdgeKind]] = set()

    for idx, stmt in enumerate(statements):
        for ref in stmt.deferred_refs:
            if ref in name_to_idx:
                target = name_to_idx[ref]
                if target != idx:
                    key = (idx, target, EdgeKind.DEFERRED)
                    if key not in seen:
                        seen.add(key)
                        edges.append(TypedEdge(idx, target, EdgeKind.DEFERRED, ref))

        for ref in stmt.immediate_refs:
            if ref in name_to_idx:
                target = name_to_idx[ref]
                if target != idx:
                    key = (target, idx, EdgeKind.IMMEDIATE)
                    if key not in seen:
                        seen.add(key)
                        edges.append(TypedEdge(target, idx, EdgeKind.IMMEDIATE, ref))

    return edges


def generate_dot(source: str, *, annotate_order: bool = True) -> str:
    """Generate DOT output for the dependency graph of a Python source."""
    statements = _extract_merged_statements(source)
    if not statements:
        return "digraph depgraph {\n  rankdir=TB;\n}\n"

    edges = _build_typed_edges(statements)
    num_nodes = len(statements)

    # SCC detection and topological sort (reuse existing pipeline)
    norm_graph = build_normalized_graph(statements)
    sccs = find_sccs(norm_graph, num_nodes)

    sort_graph = {i: set(s) for i, s in norm_graph.items()}
    for scc in sccs:
        scc_set = set(scc)
        for node in scc:
            sort_graph[node] = {s for s in sort_graph[node] if s not in scc_set}

    topo_order = topological_sort(sort_graph, num_nodes)
    if topo_order is None:
        topo_order = list(range(num_nodes))

    topo_position = {idx: pos for pos, idx in enumerate(topo_order)}

    node_to_scc: dict[int, int] = {}
    for scc_idx, scc in enumerate(sccs):
        for node in scc:
            node_to_scc[node] = scc_idx

    def node_id(idx: int) -> str:
        return f"n{idx}"

    def node_label(idx: int) -> str:
        stmt = statements[idx]
        names = sorted(stmt.bindings) if stmt.bindings else [f"<stmt:{stmt.start_line}>"]
        label = ", ".join(names)
        if annotate_order:
            label = f"#{topo_position[idx]} {label}"
        return label

    lines: list[str] = []
    lines.append("digraph depgraph {")
    lines.append("  rankdir=TB;")
    lines.append(
        '  node [shape=box, style="rounded,filled", fillcolor="#f0f0f0", fontname="Helvetica"];'
    )
    lines.append('  edge [fontname="Helvetica", fontsize=10];')
    lines.append("")

    # SCC clusters
    scc_emitted: set[int] = set()
    for scc_idx, scc in enumerate(sccs):
        lines.append(f"  subgraph cluster_scc{scc_idx} {{")
        lines.append('    label="mutual recursion";')
        lines.append("    style=filled;")
        lines.append('    color="#ffcccc";')
        lines.append('    fillcolor="#fff0f0";')
        for node in sorted(scc):
            lines.append(f'    {node_id(node)} [label="{node_label(node)}"];')
            scc_emitted.add(node)
        lines.append("  }")
        lines.append("")

    # Regular nodes
    for idx in range(num_nodes):
        if idx not in scc_emitted:
            lines.append(f'  {node_id(idx)} [label="{node_label(idx)}"];')
    lines.append("")

    # Edges
    for edge in edges:
        if edge.kind == EdgeKind.DEFERRED:
            attrs = 'color="#4169E1", style=solid, label="deferred"'
        else:
            attrs = 'color="#DC143C", style=dashed, label="immediate"'
        lines.append(f"  {node_id(edge.source)} -> {node_id(edge.target)} [{attrs}];")

    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Graphviz DOT dependency graph from a Python source file.",
    )
    parser.add_argument("file", help="Python source file to analyze")
    parser.add_argument(
        "--no-topo-order",
        action="store_true",
        help="Omit topological sort order annotation on nodes",
    )
    args = parser.parse_args()

    source = Path(args.file).read_text()
    dot = generate_dot(source, annotate_order=not args.no_topo_order)
    sys.stdout.write(dot)


if __name__ == "__main__":
    main()
