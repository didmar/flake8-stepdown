"""Tests for the ordering orchestrator."""

import ast
from unittest.mock import patch

from flake8_stepdown.core.ordering import order_module


class TestOrderModule:
    """Tests for order_module."""

    def test_empty_module(self) -> None:
        """Empty module produces no violations."""
        result = order_module("")
        assert result.violations == []
        assert result.changed is False

    def test_single_function(self) -> None:
        """Single function produces no violations."""
        source = """\
def foo():
    pass
"""
        result = order_module(source)
        assert result.violations == []
        assert result.changed is False

    def test_imports_only(self) -> None:
        """Imports-only module produces no violations."""
        source = """\
import os
import sys
"""
        result = order_module(source)
        assert result.violations == []
        assert result.changed is False

    def test_already_correct(self) -> None:
        """Caller before callee produces no violations."""
        source = """\
def main():
    helper()

def helper():
    pass
"""
        result = order_module(source)
        assert result.violations == []
        assert result.changed is False

    def test_simple_reorder(self) -> None:
        """Callee before caller produces TDP001 violation."""
        source = """\
def helper():
    pass

def main():
    helper()
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_constant_ordering(self) -> None:
        """Constants used by functions appear before those functions."""
        source = """\
def foo():
    print(CONSTANT)

CONSTANT = 1
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_decorator_ordering(self) -> None:
        """Decorator must appear before decorated function."""
        source = """\
@bar
def foo():
    pass

def bar(f):
    return f
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_mutual_recursion_no_violation(self) -> None:
        """Mutual recursion does not produce a violation, but populates mutual_recursion_groups."""
        source = """\
def a():
    b()

def b():
    a()
"""
        result = order_module(source)
        assert len(result.mutual_recursion_groups) == 1
        assert sorted(result.mutual_recursion_groups[0]) == ["a", "b"]

    def test_complex_chain(self) -> None:
        """A->B->C->D: all must be in correct order."""
        source = """\
def d():
    pass

def c():
    d()

def b():
    c()

def a():
    b()
"""
        result = order_module(source)
        assert result.changed is True

    def test_main_guard_ignored_by_default(self) -> None:
        """Functions called only from main guard are entry points (default)."""
        source = """\
def helper():
    pass

def main():
    helper()

if __name__ == "__main__":
    main()
"""
        result = order_module(source)
        # main calls helper -> main should come first
        assert result.changed is True

    def test_single_function_with_main_guard(self) -> None:
        """Single function called only from main guard needs no reordering."""
        source = """\
def only_called_from_main():
    pass

if __name__ == "__main__":
    only_called_from_main()
"""
        result = order_module(source)
        assert result.changed is False

    def test_reordered_source_is_valid_python(self) -> None:
        """When reordering happens, reordered_source is valid Python."""
        source = """\
def helper():
    pass


def main():
    helper()
"""
        result = order_module(source)
        assert result.changed is True
        assert result.reordered_source is not None
        ast.parse(result.reordered_source)

    def test_unchanged_has_no_reordered_source(self) -> None:
        """When no reordering needed, reordered_source is None."""
        source = """\
def main():
    helper()


def helper():
    pass
"""
        result = order_module(source)
        assert result.changed is False
        assert result.reordered_source is None

    def test_class_body_dependency_ordering(self) -> None:
        """Class body referencing a constant reorders correctly."""
        source = """\
class Config:
    x = DEFAULT

DEFAULT = 10
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_class_inheritance_ordering(self) -> None:
        """Child class before base class produces violation."""
        source = """\
class Child(Base):
    pass

class Base:
    pass
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_class_decorator_ordering_full(self) -> None:
        """Class decorator after decorated class produces violation."""
        source = """\
@bar
class Foo:
    pass

def bar(cls):
    return cls
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_mixed_function_and_class(self) -> None:
        """Function referencing a class produces correct ordering."""
        source = """\
def make_foo():
    return Foo()

class Foo:
    pass
"""
        result = order_module(source)
        assert result.changed is True

    def test_string_annotation_ordering(self) -> None:
        """String forward-reference annotation creates dependency."""
        source = """\
def foo(x: "Bar") -> "Bar":
    pass

class Bar:
    pass
"""
        result = order_module(source)
        assert result.changed is True
        assert any(v.code == "TDP001" for v in result.violations)

    def test_no_binding_bare_expression(self) -> None:
        """Bare expressions between functions move with their neighbor."""
        source = """\
print("setup")

def helper():
    pass

def main():
    helper()
"""
        result = order_module(source)
        # main calls helper, so main should come first; bare expression attaches to helper
        assert result.changed is True
        assert result.reordered_source is not None
        ast.parse(result.reordered_source)

    def test_independent_functions_preserve_order(self) -> None:
        """Functions with no dependencies preserve original order."""
        source = """\
def alpha():
    pass

def beta():
    pass

def gamma():
    pass
"""
        result = order_module(source)
        assert result.changed is False

    def test_diamond_dependency(self) -> None:
        """Diamond: A calls B and C, both B and C call D."""
        source = """\
def d():
    pass

def c():
    d()

def b():
    d()

def a():
    b()
    c()
"""
        result = order_module(source)
        assert result.changed is True
        assert result.reordered_source is not None
        # a should come first in the reordered source
        assert result.reordered_source.index("def a") < result.reordered_source.index("def d")

    def test_three_way_mutual_recursion(self) -> None:
        """Three-way mutual recursion: a->b->c->a."""
        source = """\
def a():
    b()

def b():
    c()

def c():
    a()
"""
        result = order_module(source)
        assert len(result.mutual_recursion_groups) == 1
        assert sorted(result.mutual_recursion_groups[0]) == ["a", "b", "c"]

    def test_whitespace_only_source(self) -> None:
        """Whitespace-only source produces no violations."""
        result = order_module("   \n\n  \n")
        assert result.violations == []
        assert result.changed is False

    def test_class_method_ref_is_deferred(self) -> None:
        """Class with method calling a function: the function ref is deferred, not immediate."""
        source = """\
class Foo:
    def method(self):
        fun_a()

def fun_a():
    fun_b()

def fun_b():
    pass
"""
        result = order_module(source)
        assert result.changed is False  # order should stay as-is

    def test_constants_only_module(self) -> None:
        """Module with only constants and no functions produces no violations."""
        source = """\
import os

A = 1
B = 2
C = 3
"""
        result = order_module(source)
        assert result.changed is False

    def test_topological_sort_none_fallback(self) -> None:
        """Graceful fallback when topological_sort unexpectedly returns None."""
        source = """\
def helper():
    pass

def main():
    helper()
"""
        with patch("flake8_stepdown.core.ordering.topological_sort", return_value=None):
            result = order_module(source)
        # Falls back to original order — no violations
        assert result.violations == []
        assert result.changed is False
