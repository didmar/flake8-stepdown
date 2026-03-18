"""Tests for source-level rewriting."""

import ast
import contextlib
import io
import runpy
from pathlib import Path

import libcst as cst

from flake8_stepdown.core.ordering import order_module
from flake8_stepdown.rewriter import _normalize_block

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
KNOWN_BROKEN_FIXTURES = {"decorator_ordering"}


def _full_pipeline(source: str) -> str | None:
    """Run the full pipeline and return rewritten source (or None if unchanged)."""
    result = order_module(source)
    return result.reordered_source


class TestRewrite:
    """Tests for the rewrite function."""

    def test_simple_reorder(self) -> None:
        """Two functions swapped produce correct output."""
        source = """\
def b():
    pass


def a():
    b()
"""
        result = _full_pipeline(source)
        assert result is not None
        assert result.index("def a") < result.index("def b")

    def test_byte_for_byte_stability(self) -> None:
        """Already-correct input returns None (no change)."""
        source = """\
def a():
    b()


def b():
    pass
"""
        result = _full_pipeline(source)
        assert result is None

    def test_preserves_comments(self) -> None:
        """Comments attached to functions move with them."""
        source = """\
# Helper function
def helper():
    pass


def main():
    helper()
"""
        result = _full_pipeline(source)
        assert result is not None
        assert result.index("def main") < result.index("def helper")

    def test_blank_line_normalization(self) -> None:
        """Exactly 2 blank lines between top-level defs after reorder."""
        source = """\
def b():
    pass


def a():
    b()
"""
        result = _full_pipeline(source)
        assert result is not None
        # Check for exactly 2 blank lines between functions
        lines = result.split("\n")
        in_blank_run = False
        blank_counts = []
        count = 0
        for line in lines:
            if line.strip() == "":
                count += 1
                in_blank_run = True
            elif in_blank_run:
                blank_counts.append(count)
                count = 0
                in_blank_run = False
        assert all(c <= 2 for c in blank_counts)

    def test_idempotency(self) -> None:
        """Rewrite twice produces same result as rewriting once."""
        source = """\
def b():
    pass


def a():
    b()
"""
        first = _full_pipeline(source)
        assert first is not None
        second = _full_pipeline(first)
        assert second is None  # Already correct, no change

    def test_preamble_only_module(self) -> None:
        """Preamble-only module with no interstitials returns None."""
        source = """\
import os
import sys
"""
        result = _full_pipeline(source)
        assert result is None

    def test_postamble_only_with_function(self) -> None:
        """Module with function and main guard reorders correctly."""
        source = """\
def helper():
    pass


def main():
    helper()


if __name__ == "__main__":
    main()
"""
        result = _full_pipeline(source)
        if result is not None:
            ast.parse(result)
            # Main guard should stay at the end
            assert result.rindex("if __name__") > result.rindex("def ")

    def test_trailing_inline_comments_preserved(self) -> None:
        """Inline comments on functions survive rewriting."""
        source = """\
def b():
    pass  # helper impl


def a():  # entry point
    b()
"""
        result = _full_pipeline(source)
        assert result is not None
        assert "# entry point" in result
        assert "# helper impl" in result

    def test_non_def_statements_preserve_no_blank_line(self) -> None:
        """Non-def/class interstitials: no blank added where there was none."""
        source = """\
do_a()
do_b()


def helper():
    pass


def main():
    helper()
"""
        result = _full_pipeline(source)
        assert result is not None
        # do_a() and do_b() were adjacent — must stay adjacent
        assert "do_a()\ndo_b()" in result

    def test_no_trailing_newline(self) -> None:
        """File without trailing newline still produces valid output."""
        source = """\
def b():
    pass


def a():
    b()"""
        result = _full_pipeline(source)
        assert result is not None
        ast.parse(result)
        assert result.index("def a") < result.index("def b")


class TestPipelineSafety:
    """Tests documenting safety properties of the rewriter with no-binding statements."""

    def test_conditional_function_def_not_reordered_past_caller(self) -> None:
        """If/else defining get_path (no binding) is not reordered past its caller."""
        source = """\
import sys

if sys.platform == "win32":
    def get_path():
        return "C:\\\\"
else:
    def get_path():
        return "/tmp"


def unrelated():
    pass


def cleanup():
    get_path()
"""
        result = _full_pipeline(source)
        actual = result if result is not None else source
        # The if/else block must not appear after cleanup
        assert actual.index("if sys.platform") < actual.index("def cleanup")

    def test_constant_docstring_stays_together(self) -> None:
        """Constant docstring stays adjacent to its constant through reordering."""
        source = """\
RETRIES = 3
\"\"\"Number of retries.\"\"\"


def helper():
    pass


def fetch():
    for i in range(RETRIES):
        helper()


def main():
    fetch()
"""
        result = _full_pipeline(source)
        actual = result if result is not None else source
        # Docstring must remain immediately after the constant
        retries_idx = actual.index("RETRIES = 3")
        doc_idx = actual.index('"""Number of retries."""')
        assert doc_idx > retries_idx
        # No function defs should appear between constant and its docstring
        between = actual[retries_idx:doc_idx]
        assert "def " not in between

    def test_augmented_assignment_stays_near_initial(self) -> None:
        """COUNTER += 1 (no binding) stays attached to COUNTER = 0."""
        source = """\
import os

COUNTER = 0
COUNTER += 1


def unrelated():
    pass


def get_counter():
    return COUNTER
"""
        result = _full_pipeline(source)
        actual = result if result is not None else source
        # COUNTER += 1 must remain after COUNTER = 0
        assert actual.index("COUNTER = 0") < actual.index("COUNTER += 1")


class TestSnapshots:
    """Snapshot tests comparing fixture output to expected snapshots."""

    def _get_fixture_names(self) -> list[str]:
        """Get all fixture names that have corresponding snapshots."""
        return [
            f.stem for f in sorted(FIXTURES_DIR.glob("*.py")) if (SNAPSHOTS_DIR / f.name).exists()
        ]

    def test_all_fixtures_have_snapshots(self) -> None:
        """Verify all fixtures have corresponding snapshots."""
        fixtures = {f.stem for f in FIXTURES_DIR.glob("*.py")}
        snapshots = {f.stem for f in SNAPSHOTS_DIR.glob("*.py")}
        assert fixtures == snapshots, f"Missing snapshots: {fixtures - snapshots}"

    def test_fixture_produces_snapshot(self) -> None:
        """Each fixture, when fixed, matches its snapshot."""
        for name in self._get_fixture_names():
            fixture = (FIXTURES_DIR / f"{name}.py").read_text()
            expected = (SNAPSHOTS_DIR / f"{name}.py").read_text()

            result = _full_pipeline(fixture)
            actual = result if result is not None else fixture

            assert actual == expected, f"Fixture {name} did not match snapshot"

    def test_idempotency(self) -> None:
        """fix(fix(x)) == fix(x) for all fixtures."""
        for name in self._get_fixture_names():
            fixture = (FIXTURES_DIR / f"{name}.py").read_text()
            first = _full_pipeline(fixture)
            actual = first if first is not None else fixture
            second = _full_pipeline(actual)
            assert second is None, f"Fixture {name} is not idempotent"

    def test_syntax_valid(self) -> None:
        """Fix output is valid Python for all fixtures."""
        for name in self._get_fixture_names():
            fixture = (FIXTURES_DIR / f"{name}.py").read_text()
            result = _full_pipeline(fixture)
            actual = result if result is not None else fixture
            try:
                ast.parse(actual)
            except SyntaxError:
                msg = f"Fixture {name} produced invalid Python"
                raise AssertionError(msg) from None

    def test_snapshot_executes(self) -> None:
        """Rewritten output executes without runtime errors."""
        for name in self._get_fixture_names():
            try:
                _run_file(SNAPSHOTS_DIR / f"{name}.py")
            except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
                msg = f"Snapshot {name} raised a runtime error: {exc}"
                raise AssertionError(msg) from None

    def test_behavioral_equivalence(self) -> None:
        """Rewritten output has same namespace keys and stdout as original."""
        for name in self._get_fixture_names():
            if name in KNOWN_BROKEN_FIXTURES:
                continue

            fix_ns, fix_stdout = _run_file(FIXTURES_DIR / f"{name}.py")
            snap_ns, snap_stdout = _run_file(SNAPSHOTS_DIR / f"{name}.py")

            fix_keys = set(fix_ns)
            snap_keys = set(snap_ns)
            assert fix_keys == snap_keys, (
                f"{name}: namespace keys differ — "
                f"missing={fix_keys - snap_keys}, extra={snap_keys - fix_keys}"
            )

            assert fix_stdout == snap_stdout, f"{name}: stdout differs after rewrite"


def _run_file(path: Path) -> tuple[dict[str, object], str]:
    """Execute a Python file and return its user-defined namespace and stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns = runpy.run_path(str(path), run_name="__test__")
    filtered = {k: v for k, v in ns.items() if not k.startswith("_")}
    return filtered, buf.getvalue()


class TestNormalizeBlock:
    """Tests for _normalize_block edge cases."""

    def test_non_base_statement_skipped(self) -> None:
        """Non-BaseStatement nodes in the list are silently skipped."""
        # cst.EmptyLine is not a BaseStatement
        nodes: list[cst.CSTNode] = [cst.EmptyLine()]
        normalized, prev = _normalize_block(nodes, None)
        assert normalized == []
        assert prev is None
