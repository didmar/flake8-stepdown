"""Tests for source parsing and segmentation."""

import libcst as cst
import pytest

from flake8_stepdown.core.parser import parse_source, segment


class TestParseSource:
    """Tests for parse_source."""

    def test_parse_valid_source(self) -> None:
        """Valid Python source returns a cst.Module."""
        result = parse_source("x = 1\n")
        assert isinstance(result, cst.Module)

    def test_parse_empty_source(self) -> None:
        """Empty source returns a cst.Module."""
        result = parse_source("")
        assert isinstance(result, cst.Module)

    def test_parse_invalid_source(self) -> None:
        """Invalid Python source raises ParserSyntaxError."""
        with pytest.raises(cst.ParserSyntaxError):
            parse_source("def (broken")


class TestSegment:
    """Tests for segment."""

    def test_segment_empty_module(self) -> None:
        """Empty module produces empty segments."""
        module = parse_source("")
        result = segment(module)
        assert result.preamble == []
        assert result.interstitials == []
        assert result.postamble == []

    def test_segment_only_preamble(self) -> None:
        """Imports-only file has only preamble, no interstitials."""
        source = """\
import os
import sys
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 2
        assert result.interstitials == []
        assert result.postamble == []

    def test_segment_basic(self) -> None:
        """Imports + functions + main guard are segmented correctly."""
        source = """\
import os

def foo():
    pass

def bar():
    pass

if __name__ == "__main__":
    foo()
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 1  # import os
        assert len(result.interstitials) == 2  # foo, bar
        assert len(result.postamble) == 1  # main guard

    def test_segment_docstring_in_preamble(self) -> None:
        """Module docstring stays in preamble."""
        source = """\
\"\"\"Module docstring.\"\"\"

import os

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 2  # docstring + import
        assert len(result.interstitials) == 1  # foo

    def test_segment_dunder_in_preamble(self) -> None:
        """Dunder assignment like __all__ stays in preamble."""
        source = """\
import os

__all__ = ["foo"]

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 2  # import + __all__
        assert len(result.interstitials) == 1  # foo

    def test_segment_type_checking_in_preamble(self) -> None:
        """TYPE_CHECKING block stays in preamble."""
        source = """\
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 3  # import, TYPE_CHECKING import, TYPE_CHECKING block
        assert len(result.interstitials) == 1  # foo

    def test_segment_no_main_guard(self) -> None:
        """Without main guard, postamble is empty."""
        source = """\
import os

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert result.postamble == []

    def test_segment_constant_is_preamble(self) -> None:
        """A bare constant assignment after imports is preamble."""
        source = """\
import os

RETRIES = 3

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 2  # import + RETRIES
        assert len(result.interstitials) == 1  # foo

    def test_segment_future_import_in_preamble(self) -> None:
        """From __future__ import stays in preamble."""
        source = """\
from __future__ import annotations

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 1  # future import
        assert len(result.interstitials) == 1  # foo

    def test_segment_module_reference_preserved(self) -> None:
        """The module reference in SegmentedModule is the parsed module."""
        module = parse_source("import os\n")
        result = segment(module)
        assert result.module is module

    def test_function_between_imports_breaks_preamble(self) -> None:
        """A function between imports stops preamble collection."""
        source = """\
import os

def foo():
    pass

import sys
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 1  # only import os
        assert len(result.interstitials) == 2  # foo + import sys

    def test_main_guard_single_quotes(self) -> None:
        """Main guard with single quotes is detected."""
        source = """\
def foo():
    pass

if __name__ == '__main__':
    foo()
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.postamble) == 1
        assert len(result.interstitials) == 1

    def test_fstring_not_docstring(self) -> None:
        """F-string expression is not treated as a docstring."""
        source = """\
x = 1
f"hello {x}"

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        # x=1 is a simple assignment so it's preamble, f-string breaks preamble
        assert len(result.preamble) == 1  # x = 1
        assert len(result.interstitials) == 2  # f-string, foo

    def test_multiple_dunder_and_imports_in_preamble(self) -> None:
        """Multiple __all__ and dunder assignments mixed with imports stay in preamble."""
        source = """\
import os

__all__ = ["foo"]

import sys

__version__ = "1.0"

def foo():
    pass
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.preamble) == 4  # import os, __all__, import sys, __version__
        assert len(result.interstitials) == 1  # foo

    def test_multiple_main_guards(self) -> None:
        """Only the last main guard is detected as postamble."""
        source = """\
def foo():
    pass

if __name__ == "__main__":
    foo()

def bar():
    pass

if __name__ == "__main__":
    bar()
"""
        module = parse_source(source)
        result = segment(module)
        assert len(result.postamble) == 1  # only the last guard
        # The first main guard ends up in interstitials
        assert len(result.interstitials) == 3  # foo, first guard, bar
