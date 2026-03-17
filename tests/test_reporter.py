"""Tests for violation formatting."""

import json

from flake8_stepdown.reporter import format_diff, format_violations
from flake8_stepdown.types import Violation

_DEFAULT_VIOLATION = Violation(
    code="TDP001",
    lineno=10,
    col_offset=0,
    name="helper",
    message="helper should appear after main",
    dependency="main",
)


class TestFormatViolations:
    """Tests for format_violations."""

    def test_format_text(self) -> None:
        """Text format produces filename:lineno:col: CODE message."""
        violations = [_DEFAULT_VIOLATION]
        result = format_violations(violations, filename="test.py", fmt="text")
        assert "test.py:10:0: TDP001" in result
        assert "helper should appear after main" in result

    def test_format_json(self) -> None:
        """JSON format produces valid JSON array."""
        violations = [_DEFAULT_VIOLATION]
        result = format_violations(violations, filename="test.py", fmt="json")
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["code"] == "TDP001"

    def test_empty_violations(self) -> None:
        """Empty violations list produces no output."""
        result = format_violations([], filename="test.py", fmt="text")
        assert result == ""

    def test_multiple_violations(self) -> None:
        """Multiple violations each appear in output."""
        violations = [
            Violation(
                code="TDP001",
                lineno=5,
                col_offset=0,
                name="a",
                message="a should appear after main",
                dependency="main",
            ),
            Violation(
                code="TDP001",
                lineno=10,
                col_offset=0,
                name="b",
                message="b should appear after main",
                dependency="main",
            ),
        ]
        result = format_violations(violations, filename="test.py", fmt="text")
        assert result.count("TDP001") == 2


class TestFormatDiff:
    """Tests for format_diff."""

    def test_unified_diff(self) -> None:
        """Produce unified diff output."""
        original = """\
def b():
    pass

def a():
    b()
"""
        rewritten = """\
def a():
    b()

def b():
    pass
"""
        result = format_diff(original, rewritten, filename="test.py")
        assert "---" in result
        assert "+++" in result
        assert "+def a" in result
        assert "-def a" in result

    def test_no_diff(self) -> None:
        """Identical input produces empty diff."""
        source = """\
def a():
    pass
"""
        result = format_diff(source, source, filename="test.py")
        assert result == ""
