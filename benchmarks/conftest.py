"""Benchmark fixtures: synthetic chain generator and pre-computed stage inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import libcst as cst
import pytest

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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from flake8_stepdown.types import SegmentedModule


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def generate_chain(n: int) -> str:
    """Generate a bottom-up call chain of n functions.

    Produces source like:
        def func_0():
            pass

        def func_1():
            func_0()
        ...
        def func_{n-1}():
            func_{n-2}()
    """
    lines: list[str] = []
    for i in range(n):
        lines.append(f"def func_{i}():")
        if i == 0:
            lines.append("    pass")
        else:
            lines.append(f"    func_{i - 1}()")
        lines.append("")
        lines.append("")
    return "\n".join(lines)


@dataclass
class PreparedInput:
    """Pre-computed intermediate results so each stage benchmark measures only its own work."""

    name: str
    source: str
    module: cst.Module
    wrapper: cst.metadata.MetadataWrapper
    positions: Mapping[cst.CSTNode, cst.metadata.CodeRange]
    seg: SegmentedModule
    statements_with_bindings: list[Statement]
    statements_with_refs: list[Statement]
    groups: list[list[Statement]]
    merged: list[Statement]
    graph: dict[int, set[int]]
    num_nodes: int
    sccs: list[list[int]]
    new_order: list[int]
    all_nodes: list[cst.CSTNode]
    expanded_order: list[int]


def _prepare(name: str, source: str) -> PreparedInput:
    """Run the full pipeline and capture each intermediate result."""
    module = parse_source(source)
    wrapper = cst.metadata.MetadataWrapper(module)
    positions = wrapper.resolve(cst.metadata.PositionProvider)
    seg = segment(wrapper.module)

    if not seg.interstitials:
        # Return a minimal PreparedInput for empty modules
        return PreparedInput(
            name=name,
            source=source,
            module=module,
            wrapper=wrapper,
            positions=positions,
            seg=seg,
            statements_with_bindings=[],
            statements_with_refs=[],
            groups=[],
            merged=[],
            graph={},
            num_nodes=0,
            sccs=[],
            new_order=[],
            all_nodes=[],
            expanded_order=[],
        )

    statements_with_bindings = extract_bindings(seg.interstitials, positions)

    has_future = detect_future_annotations(seg.preamble)
    statements_with_refs = extract_refs(statements_with_bindings, has_future_annotations=has_future)

    groups = attach_no_binding_stmts(statements_with_refs)

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

    graph = build_normalized_graph(merged)
    num_nodes = len(merged)
    sccs = find_sccs(graph, num_nodes)

    # Remove SCC internal edges (same as ordering.py)
    for scc in sccs:
        scc_set = set(scc)
        for node in scc:
            graph[node] = {s for s in graph[node] if s not in scc_set}

    new_order = topological_sort(graph, num_nodes)
    if new_order is None:
        new_order = list(range(num_nodes))

    # Compute expanded order for rewrite
    expanded_order: list[int] = []
    offsets: list[int] = []
    offset = 0
    for group in groups:
        offsets.append(offset)
        offset += len(group)

    for group_idx in new_order:
        group = groups[group_idx]
        base = offsets[group_idx]
        expanded_order.extend(base + j for j in range(len(group)))

    all_nodes = [s.node for group in groups for s in group]

    return PreparedInput(
        name=name,
        source=source,
        module=module,
        wrapper=wrapper,
        positions=positions,
        seg=seg,
        statements_with_bindings=statements_with_bindings,
        statements_with_refs=statements_with_refs,
        groups=groups,
        merged=merged,
        graph=graph,
        num_nodes=num_nodes,
        sccs=sccs,
        new_order=new_order,
        all_nodes=all_nodes,
        expanded_order=expanded_order,
    )


def _collect_inputs() -> list[PreparedInput]:
    """Build prepared inputs from fixture files and synthetic chains."""
    inputs: list[PreparedInput] = []

    # Fixture files
    for path in sorted(FIXTURES_DIR.glob("*.py")):
        source = path.read_text()
        inputs.append(_prepare(path.stem, source))

    # Synthetic chains
    for n in (10, 50, 100):
        source = generate_chain(n)
        inputs.append(_prepare(f"chain_{n}", source))

    return inputs


_ALL_INPUTS = _collect_inputs()


@pytest.fixture(params=_ALL_INPUTS, ids=[p.name for p in _ALL_INPUTS])
def prepared_input(request: pytest.FixtureRequest) -> PreparedInput:
    """Parametrized fixture providing pre-computed stage inputs."""
    return request.param
