"""Per-stage performance benchmarks for the flake8-stepdown pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from flake8_stepdown.core.bindings import extract_bindings
from flake8_stepdown.core.graph import (
    attach_no_binding_stmts,
    build_normalized_graph,
    find_sccs,
    topological_sort,
)
from flake8_stepdown.core.ordering import order_module
from flake8_stepdown.core.parser import compute_line_numbers, parse_source, segment
from flake8_stepdown.core.references import detect_future_annotations, extract_refs
from flake8_stepdown.rewriter import rewrite
from flake8_stepdown.types import Statement

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

    from benchmarks.conftest import PreparedInput


@pytest.mark.benchmark(group="parse")
def test_parse(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: parse_source."""
    benchmark(parse_source, prepared_input.source)


@pytest.mark.benchmark(group="line_numbers")
def test_line_numbers(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: compute_line_numbers (replaces MetadataWrapper)."""
    benchmark(compute_line_numbers, prepared_input.source, prepared_input.module)


@pytest.mark.benchmark(group="segment")
def test_segment(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: segment."""
    benchmark(segment, prepared_input.module)


@pytest.mark.benchmark(group="bindings")
def test_bindings(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: extract_bindings."""
    seg = prepared_input.seg
    if not seg.interstitials:
        pytest.skip("no interstitials")
    benchmark(extract_bindings, seg.interstitials, prepared_input.positions)


@pytest.mark.benchmark(group="references")
def test_references(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: detect_future_annotations + extract_refs."""
    seg = prepared_input.seg
    stmts = prepared_input.statements_with_bindings
    if not stmts:
        pytest.skip("no statements")

    def run() -> None:
        has_future = detect_future_annotations(seg.preamble)
        extract_refs(stmts, has_future_annotations=has_future)

    benchmark(run)


@pytest.mark.benchmark(group="grouping")
def test_grouping(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: attach_no_binding_stmts + merge loop."""
    stmts = prepared_input.statements_with_refs
    if not stmts:
        pytest.skip("no statements")

    def run() -> None:
        groups = attach_no_binding_stmts(stmts)
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

    benchmark(run)


@pytest.mark.benchmark(group="graph")
def test_graph(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: build_normalized_graph."""
    merged = prepared_input.merged
    if not merged:
        pytest.skip("no merged statements")
    benchmark(build_normalized_graph, merged)


@pytest.mark.benchmark(group="scc")
def test_scc(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: find_sccs."""
    if not prepared_input.merged:
        pytest.skip("no merged statements")
    # Use a fresh graph each time since find_sccs doesn't mutate it
    graph = build_normalized_graph(prepared_input.merged)
    benchmark(find_sccs, graph, prepared_input.num_nodes)


@pytest.mark.benchmark(group="sort")
def test_sort(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: topological_sort."""
    if not prepared_input.merged:
        pytest.skip("no merged statements")
    benchmark(topological_sort, prepared_input.graph, prepared_input.num_nodes)


@pytest.mark.benchmark(group="rewrite")
def test_rewrite(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: rewrite."""
    seg = prepared_input.seg
    if not prepared_input.all_nodes or not prepared_input.expanded_order:
        pytest.skip("no nodes to rewrite")
    benchmark(
        rewrite,
        seg.module,
        seg.preamble,
        prepared_input.all_nodes,
        seg.postamble,
        prepared_input.expanded_order,
    )


@pytest.mark.benchmark(group="end_to_end")
def test_order_module(benchmark: BenchmarkFixture, prepared_input: PreparedInput) -> None:
    """Benchmark: full order_module pipeline."""
    benchmark(order_module, prepared_input.source)
