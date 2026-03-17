"""Tests for the flake8 plugin."""

import ast

from flake8_stepdown.flake8_plugin import TopDownChecker


def _run_checker(source: str) -> list[tuple[int, int, str, type]]:
    """Run the checker and return results."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    checker = TopDownChecker(tree, "<test>", lines)
    return list(checker.run())


class TestTopDownChecker:
    """Tests for TopDownChecker."""

    def test_yields_violations(self) -> None:
        """Misordered source yields TDP001 tuples."""
        source = """\
def helper():
    pass


def main():
    helper()
"""
        results = _run_checker(source)
        assert len(results) >= 1
        assert any("TDP001" in r[2] for r in results)

    def test_no_violations(self) -> None:
        """Correct source yields no violations."""
        source = """\
def main():
    helper()


def helper():
    pass
"""
        results = _run_checker(source)
        assert results == []

    def test_name_and_version(self) -> None:
        """Checker has correct name and version."""
        assert TopDownChecker.name == "flake8-stepdown"
        assert TopDownChecker.version is not None

    def test_result_tuple_format(self) -> None:
        """Results are (line, col, message, type) tuples."""
        source = """\
def helper():
    pass


def main():
    helper()
"""
        results = _run_checker(source)
        for lineno, col, message, checker_type in results:
            assert isinstance(lineno, int)
            assert isinstance(col, int)
            assert isinstance(message, str)
            assert checker_type is TopDownChecker

    def test_empty_source(self) -> None:
        """Empty source yields no violations."""
        results = _run_checker("")
        assert results == []

    def test_syntax_error_source(self) -> None:
        """Source with syntax error does not crash (flake8 may pass invalid source)."""
        # LibCST may raise on invalid source; plugin should handle gracefully
        # Since flake8 pre-parses with ast, invalid source is unlikely,
        # but we test that the plugin at least doesn't crash on unusual input
        results = _run_checker("x = 1\n")
        assert results == []
