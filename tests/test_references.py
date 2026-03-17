"""Tests for reference extraction."""

import libcst as cst

from flake8_stepdown.core.bindings import extract_bindings
from flake8_stepdown.core.parser import segment
from flake8_stepdown.core.references import detect_future_annotations, extract_refs
from flake8_stepdown.types import Statement


def _analyze(source: str) -> list[Statement]:
    """Parse source and extract bindings + references."""
    module = cst.parse_module(source)
    wrapper = cst.metadata.MetadataWrapper(module)
    positions = wrapper.resolve(cst.metadata.PositionProvider)
    seg = segment(wrapper.module)
    statements = extract_bindings(seg.interstitials, positions)
    has_future = detect_future_annotations(seg.preamble)
    return extract_refs(statements, has_future_annotations=has_future)


def _refs_by_name(statements: list[Statement]) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """Build a dict of name -> (immediate_refs, deferred_refs) for easy assertions."""
    result = {}
    for s in statements:
        for name in s.bindings:
            result[name] = (s.immediate_refs, s.deferred_refs)
    return result


class TestDeferredRefs:
    """Tests for deferred reference extraction."""

    def test_function_call(self) -> None:
        """Function call in body creates deferred ref."""
        source = """\
def a():
    b()

def b():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "b" in refs["a"][1]  # deferred

    def test_callback_reference(self) -> None:
        """Name reference (not a call) in body creates deferred ref."""
        source = """\
def a():
    x = b

def b():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "b" in refs["a"][1]  # deferred


class TestImmediateRefs:
    """Tests for immediate reference extraction."""

    def test_decorator(self) -> None:
        """Decorator creates immediate ref."""
        source = """\
def bar(f):
    return f

@bar
def foo():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "bar" in refs["foo"][0]  # immediate

    def test_default_arg(self) -> None:
        """Default argument value creates immediate ref."""
        source = """\
def foo(x=BAR):
    pass

BAR = 10
"""
        refs = _refs_by_name(_analyze(source))
        assert "BAR" in refs["foo"][0]  # immediate

    def test_annotation(self) -> None:
        """Type annotation creates immediate ref (without future annotations)."""
        source = """\
class Bar:
    pass

def foo(x: Bar) -> Bar:
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "Bar" in refs["foo"][0]  # immediate

    def test_constant_in_body_is_immediate(self) -> None:
        """Function body reference to a constant is immediate."""
        source = """\
def foo():
    print(CONSTANT)

CONSTANT = 1
"""
        refs = _refs_by_name(_analyze(source))
        assert "CONSTANT" in refs["foo"][0]  # immediate

    def test_class_ref_in_body_is_immediate(self) -> None:
        """Function body reference to a class is immediate."""
        source = """\
class MyClass:
    pass

def foo():
    return MyClass()
"""
        refs = _refs_by_name(_analyze(source))
        assert "MyClass" in refs["foo"][0]  # immediate

    def test_string_annotation_ref(self) -> None:
        """String annotation creates immediate ref (forward reference)."""
        source = """\
class Bar:
    pass

def foo(x: "Bar") -> "Bar":
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "Bar" in refs["foo"][0]  # immediate

    def test_function_ref_in_body_is_deferred(self) -> None:
        """Function body reference to another function is deferred."""
        source = """\
def foo():
    return bar()

def bar():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "bar" in refs["foo"][1]  # deferred
        assert "bar" not in refs["foo"][0]  # not immediate


class TestFutureAnnotations:
    """Tests for from __future__ import annotations handling."""

    def test_makes_annotations_deferred(self) -> None:
        """With future annotations, annotation refs become deferred."""
        source = """\
from __future__ import annotations

class Bar:
    pass

def foo(x: Bar) -> Bar:
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "Bar" not in refs["foo"][0]  # not immediate


class TestFiltering:
    """Tests for reference filtering."""

    def test_only_known_bindings_tracked(self) -> None:
        """References to names not in statements are ignored."""
        source = """\
def foo():
    unknown_func()
"""
        refs = _refs_by_name(_analyze(source))
        assert refs["foo"] == (frozenset(), frozenset())

    def test_builtin_not_tracked(self) -> None:
        """Builtins like print, len are not tracked as refs."""
        source = """\
def foo():
    print(len([]))
"""
        refs = _refs_by_name(_analyze(source))
        assert refs["foo"] == (frozenset(), frozenset())


class TestLambda:
    """Tests for lambda reference handling."""

    def test_lambda_ref_attributed_to_enclosing(self) -> None:
        """References inside a lambda are attributed to the enclosing function."""
        source = """\
def foo():
    f = lambda: bar()

def bar():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "bar" in refs["foo"][1]  # deferred ref of foo

    def test_nested_function_ref_attributed_to_outer(self) -> None:
        """References inside a nested function are attributed to the outer function."""
        source = """\
def outer():
    def inner():
        helper()
    inner()

def helper():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "helper" in refs["outer"][1]  # deferred ref of outer


class TestClassReferences:
    """Tests for class-level reference extraction."""

    def test_class_base_class_ref(self) -> None:
        """Class inheriting from another class creates immediate ref."""
        source = """\
class Base:
    pass

class Child(Base):
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "Base" in refs["Child"][0]  # immediate

    def test_class_metaclass_ref(self) -> None:
        """Class metaclass keyword creates immediate ref."""
        source = """\
class MyMeta(type):
    pass

class Foo(metaclass=MyMeta):
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "MyMeta" in refs["Foo"][0]  # immediate

    def test_class_body_ref_to_constant(self) -> None:
        """Class body referencing a constant creates immediate ref."""
        source = """\
class Foo:
    x = DEFAULT

DEFAULT = 10
"""
        refs = _refs_by_name(_analyze(source))
        assert "DEFAULT" in refs["Foo"][0]  # immediate

    def test_class_decorator_creates_ref(self) -> None:
        """Class decorator creates immediate ref."""
        source = """\
def my_decorator(cls):
    return cls

@my_decorator
class Foo:
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "my_decorator" in refs["Foo"][0]  # immediate

    def test_class_method_body_ref_to_function_is_deferred(self) -> None:
        """Method body reference to a function is deferred (not immediate) for the class."""
        source = """\
class Foo:
    def method(self):
        fun_a()

def fun_a():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "fun_a" in refs["Foo"][1]  # deferred
        assert "fun_a" not in refs["Foo"][0]  # not immediate

    def test_class_method_body_ref_to_constant_is_immediate(self) -> None:
        """Method body reference to a constant is immediate for the class."""
        source = """\
class Foo:
    def method(self):
        print(CONST)

CONST = 42
"""
        refs = _refs_by_name(_analyze(source))
        assert "CONST" in refs["Foo"][0]  # immediate


class TestParameterRefs:
    """Tests for parameter-level reference extraction."""

    def test_kwonly_param_default(self) -> None:
        """Keyword-only parameter default creates immediate ref."""
        source = """\
def foo(*, limit=LIMIT):
    pass

LIMIT = 100
"""
        refs = _refs_by_name(_analyze(source))
        assert "LIMIT" in refs["foo"][0]  # immediate

    def test_posonly_param_annotation(self) -> None:
        """Positional-only parameter annotation creates immediate ref."""
        source = """\
class MyType:
    pass

def foo(x: MyType, /):
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "MyType" in refs["foo"][0]  # immediate

    def test_return_type_annotation(self) -> None:
        """Return type annotation creates immediate ref."""
        source = """\
class Result:
    pass

def foo() -> Result:
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "Result" in refs["foo"][0]  # immediate

    def test_star_arg_annotation(self) -> None:
        """*args annotation creates immediate ref."""
        source = """\
class Item:
    pass

def foo(*args: Item):
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "Item" in refs["foo"][0]  # immediate

    def test_multiple_decorators(self) -> None:
        """Multiple decorators each create immediate refs."""
        source = """\
def dec1(f):
    return f

def dec2(f):
    return f

@dec1
@dec2
def foo():
    pass
"""
        refs = _refs_by_name(_analyze(source))
        assert "dec1" in refs["foo"][0]
        assert "dec2" in refs["foo"][0]


class TestFutureAnnotationsDeferred:
    """Tests for future annotations making annotation refs deferred."""

    def test_future_annotations_function_annotations_not_immediate(self) -> None:
        """With future annotations, function param/return annotations are not immediate."""
        source = """\
from __future__ import annotations

class Bar:
    pass

def foo(x: Bar) -> Bar:
    pass
"""
        refs = _refs_by_name(_analyze(source))
        # Bar is a class, so body refs to it would be immediate, but annotations are skipped
        assert "Bar" not in refs["foo"][0]  # not immediate
        # Bar is not in the function body, only in annotations, so no deferred either
        assert "Bar" not in refs["foo"][1]


class TestDetectFutureAnnotations:
    """Tests for detect_future_annotations."""

    def test_present(self) -> None:
        """Detects from __future__ import annotations in preamble."""
        source = """\
from __future__ import annotations

def foo():
    pass
"""
        module = cst.parse_module(source)
        seg = segment(module)
        assert detect_future_annotations(seg.preamble) is True

    def test_absent(self) -> None:
        """Returns False when not present."""
        source = """\
import os

def foo():
    pass
"""
        module = cst.parse_module(source)
        seg = segment(module)
        assert detect_future_annotations(seg.preamble) is False
