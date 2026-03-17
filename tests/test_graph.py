"""Tests for dependency graph, topological sort, and SCC detection."""

import libcst as cst

from flake8_stepdown.core.graph import (
    attach_no_binding_stmts,
    build_normalized_graph,
    find_sccs,
    topological_sort,
)
from flake8_stepdown.types import Statement


def _make_stmt(
    bindings: frozenset[str],
    immediate: frozenset[str] | None = None,
    deferred: frozenset[str] | None = None,
    start_line: int = 0,
) -> Statement:
    """Create a minimal Statement for graph testing."""
    return Statement(
        node=cst.parse_statement("pass"),
        start_line=start_line,
        end_line=start_line,
        bindings=bindings,
        immediate_refs=immediate or frozenset(),
        deferred_refs=deferred or frozenset(),
        is_overload_group=False,
    )


def _make_stmt_from_source(
    source: str,
    bindings: frozenset[str] | None = None,
    start_line: int = 0,
) -> Statement:
    """Create a Statement with a real CST node parsed from source."""
    node = cst.parse_statement(source)
    return Statement(
        node=node,
        start_line=start_line,
        end_line=start_line,
        bindings=bindings or frozenset(),
        immediate_refs=frozenset(),
        deferred_refs=frozenset(),
        is_overload_group=False,
    )


class TestBuildNormalizedGraph:
    """Tests for build_normalized_graph."""

    def test_linear_chain(self) -> None:
        """A -> B -> C produces edges A->B, B->C."""
        stmts = [
            _make_stmt(frozenset({"A"}), deferred=frozenset({"B"})),
            _make_stmt(frozenset({"B"}), deferred=frozenset({"C"})),
            _make_stmt(frozenset({"C"})),
        ]
        graph = build_normalized_graph(stmts)
        assert 1 in graph[0]  # A -> B
        assert 2 in graph[1]  # B -> C

    def test_no_edges(self) -> None:
        """Independent statements produce no edges."""
        stmts = [
            _make_stmt(frozenset({"A"})),
            _make_stmt(frozenset({"B"})),
            _make_stmt(frozenset({"C"})),
        ]
        graph = build_normalized_graph(stmts)
        for successors in graph.values():
            assert successors == set()

    def test_diamond(self) -> None:
        """Diamond: A->B, A->C, B->D, C->D."""
        stmts = [
            _make_stmt(frozenset({"A"}), deferred=frozenset({"B", "C"})),
            _make_stmt(frozenset({"B"}), deferred=frozenset({"D"})),
            _make_stmt(frozenset({"C"}), deferred=frozenset({"D"})),
            _make_stmt(frozenset({"D"})),
        ]
        graph = build_normalized_graph(stmts)
        assert graph[0] == {1, 2}
        assert graph[1] == {3}
        assert graph[2] == {3}

    def test_immediate_ref_reverse_edge(self) -> None:
        """Immediate ref: A uses decorator B -> edge B->A (B before A)."""
        stmts = [
            _make_stmt(frozenset({"A"}), immediate=frozenset({"B"})),
            _make_stmt(frozenset({"B"})),
        ]
        graph = build_normalized_graph(stmts)
        assert 0 in graph[1]  # B -> A (B must come before A)
        assert 1 not in graph[0]  # NOT A -> B


class TestTopologicalSort:
    """Tests for topological_sort."""

    def test_linear_chain(self) -> None:
        """A->B->C sorts to [A, B, C]."""
        graph = {0: {1}, 1: {2}, 2: set()}
        result = topological_sort(graph, 3)
        assert result == [0, 1, 2]

    def test_no_edges(self) -> None:
        """No edges: original order preserved."""
        graph = {0: set(), 1: set(), 2: set()}
        result = topological_sort(graph, 3)
        assert result == [0, 1, 2]

    def test_stability_tiebreak(self) -> None:
        """When multiple nodes have in_degree=0, earlier original index wins."""
        # All three independent — should preserve original order
        graph = {0: set(), 1: set(), 2: set()}
        result = topological_sort(graph, 3)
        assert result == [0, 1, 2]

    def test_stability_with_constraints(self) -> None:
        """Constrained nodes sort correctly, unconstrained preserve order."""
        # 0 depends on nothing, 1 depends on nothing, 2 depends on 0
        # 0 and 1 are both in_degree=0; 0 wins by index
        graph = {0: {2}, 1: set(), 2: set()}
        result = topological_sort(graph, 3)
        assert result is not None
        assert result.index(0) < result.index(2)
        # 1 can go anywhere it has no constraints, but by stability goes to position 1
        assert result == [0, 1, 2]

    def test_cycle_returns_none(self) -> None:
        """Cycle detection: returns None when a cycle exists."""
        graph = {0: {1}, 1: {0}}
        result = topological_sort(graph, 2)
        assert result is None


class TestFindSccs:
    """Tests for find_sccs (Tarjan's SCC)."""

    def test_no_cycles(self) -> None:
        """No cycles: no SCCs with size > 1."""
        graph = {0: {1}, 1: {2}, 2: set()}
        sccs = find_sccs(graph, 3)
        assert sccs == []

    def test_simple_cycle(self) -> None:
        """A->B->A forms an SCC of size 2."""
        graph = {0: {1}, 1: {0}}
        sccs = find_sccs(graph, 2)
        assert len(sccs) == 1
        assert set(sccs[0]) == {0, 1}

    def test_two_separate_cycles(self) -> None:
        """Two separate cycles detected as two SCCs."""
        graph = {0: {1}, 1: {0}, 2: {3}, 3: {2}}
        sccs = find_sccs(graph, 4)
        assert len(sccs) == 2

    def test_conflicting_immediate_deferred(self) -> None:
        """A uses @B (immediate -> B before A) + A calls B (deferred -> A before B): cycle."""
        stmts = [
            _make_stmt(frozenset({"A"}), immediate=frozenset({"B"}), deferred=frozenset({"B"})),
            _make_stmt(frozenset({"B"})),
        ]
        graph = build_normalized_graph(stmts)
        # immediate B -> edge 1->0, deferred B -> edge 0->1: cycle!
        sccs = find_sccs(graph, 2)
        assert len(sccs) == 1
        assert set(sccs[0]) == {0, 1}


class TestAttachNoBindingStmts:
    """Tests for no-binding statement attachment."""

    def test_attach_to_next(self) -> None:
        """Statement with no bindings attaches to the next statement."""
        stmts = [
            _make_stmt(frozenset(), start_line=1),  # no bindings
            _make_stmt(frozenset({"foo"}), start_line=3),
        ]
        groups = attach_no_binding_stmts(stmts)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_attach_to_preceding_if_last(self) -> None:
        """Last no-binding statement attaches to the preceding statement."""
        stmts = [
            _make_stmt(frozenset({"foo"}), start_line=1),
            _make_stmt(frozenset(), start_line=3),  # no bindings, last
        ]
        groups = attach_no_binding_stmts(stmts)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_all_have_bindings(self) -> None:
        """When all have bindings, each is its own group."""
        stmts = [
            _make_stmt(frozenset({"a"}), start_line=1),
            _make_stmt(frozenset({"b"}), start_line=3),
        ]
        groups = attach_no_binding_stmts(stmts)
        assert len(groups) == 2
        assert all(len(g) == 1 for g in groups)

    def test_docstring_after_constant_attaches_to_constant(self) -> None:
        """Docstring immediately after a constant groups with the constant."""
        stmts = [
            _make_stmt_from_source("RETRIES = 3\n", bindings=frozenset({"RETRIES"}), start_line=1),
            _make_stmt_from_source('"Number of retries."\n', start_line=2),
            _make_stmt_from_source("def foo(): pass\n", bindings=frozenset({"foo"}), start_line=4),
        ]
        groups = attach_no_binding_stmts(stmts)
        # Docstring should be in the same group as RETRIES, not with foo
        assert len(groups) == 2
        assert len(groups[0]) == 2  # [RETRIES, docstring]
        assert len(groups[1]) == 1  # [foo]

    def test_docstring_after_function_still_attaches_forward(self) -> None:
        """Docstring after a function def still attaches forward (no regression)."""
        stmts = [
            _make_stmt_from_source("def bar(): pass\n", bindings=frozenset({"bar"}), start_line=1),
            _make_stmt_from_source('"Some doc."\n', start_line=3),
            _make_stmt_from_source("def baz(): pass\n", bindings=frozenset({"baz"}), start_line=5),
        ]
        groups = attach_no_binding_stmts(stmts)
        # Docstring should attach forward to baz, not backward to bar
        assert len(groups) == 2
        assert len(groups[0]) == 1  # [bar]
        assert len(groups[1]) == 2  # [docstring, baz]

    def test_multiple_constants_with_docstrings(self) -> None:
        """Each constant-docstring pair is its own group."""
        stmts = [
            _make_stmt_from_source("A = 1\n", bindings=frozenset({"A"}), start_line=1),
            _make_stmt_from_source('"Doc for A."\n', start_line=2),
            _make_stmt_from_source("B = 2\n", bindings=frozenset({"B"}), start_line=3),
            _make_stmt_from_source('"Doc for B."\n', start_line=4),
            _make_stmt_from_source("def foo(): pass\n", bindings=frozenset({"foo"}), start_line=6),
        ]
        groups = attach_no_binding_stmts(stmts)
        assert len(groups) == 3
        assert len(groups[0]) == 2  # [A, doc]
        assert len(groups[1]) == 2  # [B, doc]
        assert len(groups[2]) == 1  # [foo]


class TestGraphEdgeCases:
    """Edge case tests for graph algorithms."""

    def test_self_loop_in_graph(self) -> None:
        """Self-loop: topological sort handles a node pointing to itself."""
        graph = {0: {0}, 1: set()}
        # Self-loop creates a cycle of size 1, topo sort can't complete
        result = topological_sort(graph, 2)
        assert result is None

    def test_single_node_topological_sort(self) -> None:
        """Single node graph produces trivial ordering."""
        graph = {0: set()}
        result = topological_sort(graph, 1)
        assert result == [0]

    def test_empty_graph_topological_sort(self) -> None:
        """Empty graph produces empty ordering."""
        graph: dict[int, set[int]] = {}
        result = topological_sort(graph, 0)
        assert result == []

    def test_self_loop_scc(self) -> None:
        """Self-loop is not reported as SCC (size 1)."""
        graph = {0: {0}}
        sccs = find_sccs(graph, 1)
        # Tarjan's only reports SCCs with size > 1
        assert sccs == []

    def test_empty_statements_attach(self) -> None:
        """Empty statement list produces empty groups."""
        groups = attach_no_binding_stmts([])
        assert groups == []

    def test_all_no_binding_stmts(self) -> None:
        """All statements with no bindings form a single group."""
        stmts = [
            _make_stmt(frozenset(), start_line=1),
            _make_stmt(frozenset(), start_line=2),
            _make_stmt(frozenset(), start_line=3),
        ]
        groups = attach_no_binding_stmts(stmts)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_duplicate_function_names_second_wins(self) -> None:
        """When two statements bind the same name, the second overwrites in the graph."""
        stmts = [
            _make_stmt(frozenset({"foo"})),
            _make_stmt(frozenset({"foo"})),
            _make_stmt(frozenset({"bar"}), deferred=frozenset({"foo"})),
        ]
        graph = build_normalized_graph(stmts)
        # "bar" calls "foo" -> edge 2->? — second "foo" (index 1) wins
        assert 1 in graph[2]
        assert 0 not in graph[2]
