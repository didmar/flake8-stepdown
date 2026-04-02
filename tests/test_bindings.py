"""Tests for binding extraction."""

from flake8_stepdown.core.bindings import extract_bindings
from flake8_stepdown.core.parser import compute_line_numbers, parse_source
from flake8_stepdown.types import Statement


def _parse_and_extract(source: str) -> list[Statement]:
    """Parse and extract bindings from all module-level statements."""
    module = parse_source(source)
    positions = compute_line_numbers(source, module)
    return extract_bindings(list(module.body), positions)


def _get_bindings(source: str) -> list[frozenset[str]]:
    """Return just the binding sets."""
    return [s.bindings for s in _parse_and_extract(source)]


class TestExtractBindings:
    """Tests for extract_bindings."""

    def test_function_binding(self) -> None:
        """FunctionDef produces binding = {function_name}."""
        source = """\
def foo():
    pass
"""
        assert _get_bindings(source) == [frozenset({"foo"})]

    def test_async_function_binding(self) -> None:
        """Async FunctionDef produces binding = {function_name}."""
        source = """\
async def foo():
    pass
"""
        assert _get_bindings(source) == [frozenset({"foo"})]

    def test_class_binding(self) -> None:
        """ClassDef produces binding = {class_name}."""
        source = """\
class Foo:
    pass
"""
        assert _get_bindings(source) == [frozenset({"Foo"})]

    def test_assignment_binding(self) -> None:
        """Simple assignment produces binding = {target_name}."""
        source = "X = 1\n"
        assert _get_bindings(source) == [frozenset({"X"})]

    def test_multi_target_assignment_binding(self) -> None:
        """Assignment with multiple targets produces all target names."""
        source = "A = B = 1\n"
        assert _get_bindings(source) == [frozenset({"A", "B"})]

    def test_annotated_assignment_binding(self) -> None:
        """Annotated assignment produces binding = {target_name}."""
        source = "x: int = 1\n"
        assert _get_bindings(source) == [frozenset({"x"})]

    def test_no_binding_bare_expr(self) -> None:
        """Bare expression has no bindings."""
        source = 'print("hi")\n'
        assert _get_bindings(source) == [frozenset()]

    def test_multiple_statements(self) -> None:
        """Multiple statements each get their own bindings."""
        source = """\
X = 1

def foo():
    pass

class Bar:
    pass
"""
        assert _get_bindings(source) == [frozenset({"X"}), frozenset({"foo"}), frozenset({"Bar"})]

    def test_line_numbers(self) -> None:
        """Start and end line numbers are set correctly."""
        source = """\
def foo():
    x = 1
    return x
"""
        statements = _parse_and_extract(source)
        assert len(statements) == 1
        assert statements[0].start_line == 1
        assert statements[0].end_line == 3

    def test_overload_grouping(self) -> None:
        """Consecutive @overload stubs + implementation are merged into one statement."""
        source = """\
import typing

@typing.overload
def foo(x: int) -> int: ...

@typing.overload
def foo(x: str) -> str: ...

def foo(x: int | str) -> int | str:
    return x
"""
        statements = _parse_and_extract(source)
        # import typing + the overload group
        assert statements[-1].bindings == frozenset({"foo"})
        assert statements[-1].is_overload_group is True

    def test_bare_overload_grouping(self) -> None:
        """Bare @overload (from typing import overload) stubs are grouped."""
        source = """\
from typing import overload

@overload
def foo(x: int) -> int: ...

@overload
def foo(x: str) -> str: ...

def foo(x: int | str) -> int | str:
    return x
"""
        statements = _parse_and_extract(source)
        assert statements[-1].bindings == frozenset({"foo"})
        assert statements[-1].is_overload_group is True

    def test_overload_not_consecutive(self) -> None:
        """Non-consecutive same-name functions are separate statements."""
        source = """\
import typing

@typing.overload
def foo(x: int) -> int: ...

def bar():
    pass

def foo(x: int | str) -> int | str:
    return x
"""
        statements = _parse_and_extract(source)
        # import typing, overload foo, bar, impl foo
        func_statements = [s for s in statements if s.bindings]
        assert len(func_statements) >= 3
        assert func_statements[0].is_overload_group is False

    def test_refs_initially_empty(self) -> None:
        """Extracted statements have empty refs (filled later by references module)."""
        source = """\
def foo():
    pass
"""
        statements = _parse_and_extract(source)
        assert statements[0].immediate_refs == frozenset()
        assert statements[0].deferred_refs == frozenset()

    def test_tuple_unpacking_binding(self) -> None:
        """Tuple unpacking assignment produces bindings for all unpacked names."""
        source = "a, b = 1, 2\n"
        assert _get_bindings(source) == [frozenset({"a", "b"})]

    def test_nested_tuple_unpacking_binding(self) -> None:
        """Nested tuple unpacking extracts all names recursively."""
        source = "(a, (b, c)) = (1, (2, 3))\n"
        assert _get_bindings(source) == [frozenset({"a", "b", "c"})]

    def test_starred_unpacking_binding(self) -> None:
        """Starred unpacking extracts all names including the starred target."""
        source = "a, *b = [1, 2, 3]\n"
        assert _get_bindings(source) == [frozenset({"a", "b"})]

    def test_augmented_assignment_no_binding(self) -> None:
        """Augmented assignment (x += 1) does not produce a binding."""
        source = "x = 0\nx += 1\n"
        assert _get_bindings(source) == [frozenset({"x"}), frozenset()]

    def test_subscript_assignment_no_binding(self) -> None:
        """Subscript assignment does not produce a binding."""
        source = 'd = {}\nd["key"] = 1\n'
        assert _get_bindings(source) == [frozenset({"d"}), frozenset()]

    def test_attribute_assignment_no_binding(self) -> None:
        """Attribute assignment does not produce a binding."""
        source = """\
class Obj:
    pass

obj = Obj()
obj.x = 1
"""
        bindings = _get_bindings(source)
        # class Obj -> {Obj}, obj = Obj() -> {obj}, obj.x = 1 -> no binding
        assert bindings == [frozenset({"Obj"}), frozenset({"obj"}), frozenset()]

    def test_function_in_if_block_no_binding(self) -> None:
        """Function defined inside an if block produces no binding (compound stmt)."""
        source = """\
if True:
    def platform_func():
        pass
"""
        bindings = _get_bindings(source)
        assert bindings == [frozenset()]  # if block has no bindings

    def test_function_in_try_except_no_binding(self) -> None:
        """Function defined inside try/except produces no binding."""
        source = """\
try:
    from fast_lib import optimize
except ImportError:
    def optimize(x):
        return x
"""
        bindings = _get_bindings(source)
        assert bindings == [frozenset()]  # try block has no bindings

    def test_annotation_only_no_value_no_binding(self) -> None:
        """Annotation-only `x: int` has no value, so no name is bound."""
        source = "x: int\n"
        assert _get_bindings(source) == [frozenset()]

    def test_for_loop_no_binding(self) -> None:
        """For loop is a compound statement — no binding extracted."""
        source = """\
for i in range(3):
    pass
"""
        bindings = _get_bindings(source)
        assert bindings == [frozenset()]

    def test_with_statement_no_binding(self) -> None:
        """With statement is a compound statement — no binding extracted."""
        source = """\
with open('f') as fh:
    pass
"""
        bindings = _get_bindings(source)
        assert bindings == [frozenset()]

    def test_while_loop_no_binding(self) -> None:
        """While loop is a compound statement — no binding extracted."""
        source = """\
while False:
    break
"""
        bindings = _get_bindings(source)
        assert bindings == [frozenset()]

    def test_del_statement_no_binding(self) -> None:
        """Del statement does not produce a binding."""
        source = "x = 1\ndel x\n"
        assert _get_bindings(source) == [frozenset({"x"}), frozenset()]

    def test_if_else_conditional_function_no_binding(self) -> None:
        """If/else both defining a function — still no binding (compound stmt)."""
        source = """\
if True:
    def get_path():
        return "C:\\\\"
else:
    def get_path():
        return "/tmp"
"""
        bindings = _get_bindings(source)
        assert bindings == [frozenset()]
