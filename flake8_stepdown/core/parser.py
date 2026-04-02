"""AST parsing and source segmentation."""

from __future__ import annotations

import ast

import libcst as cst
import libcst.matchers as m

from flake8_stepdown.types import SegmentedModule


def parse_source(source: str) -> cst.Module:
    """Parse Python source into a LibCST module tree."""
    return cst.parse_module(source)


def compute_line_numbers(source: str, module: cst.Module) -> dict[cst.CSTNode, tuple[int, int]]:
    """Compute start/end line numbers for top-level statements using the ast module.

    This is much faster than libcst's MetadataWrapper + PositionProvider, which
    deep-clones the entire tree and runs codegen to compute positions.
    """
    ast_tree = ast.parse(source)
    result: dict[cst.CSTNode, tuple[int, int]] = {}
    for cst_node, ast_node in zip(module.body, ast_tree.body, strict=False):
        result[cst_node] = (ast_node.lineno, ast_node.end_lineno or ast_node.lineno)
    return result


def segment(module: cst.Module) -> SegmentedModule:
    """Split a module into preamble, interstitial, and postamble zones."""
    body = list(module.body)

    # Extract preamble: contiguous block from top matching preamble rules
    preamble: list[cst.CSTNode] = []
    idx = 0
    while idx < len(body) and _is_preamble_statement(body[idx]):
        preamble.append(body[idx])
        idx += 1

    # Extract postamble: main guard at end
    postamble: list[cst.CSTNode] = []
    if body and _is_main_guard(body[-1]):
        postamble.append(body[-1])
        remaining = body[idx:-1]
    else:
        remaining = body[idx:]

    # Everything else is interstitial
    interstitials: list[cst.CSTNode] = list(remaining)

    return SegmentedModule(
        module=module,
        preamble=preamble,
        interstitials=interstitials,
        postamble=postamble,
    )


def _is_main_guard(node: cst.BaseStatement) -> bool:
    """Check if a statement is `if __name__ == "__main__":`."""
    return m.matches(
        node,
        m.If(
            test=m.Comparison(
                left=m.Name("__name__"),
                comparisons=[
                    m.ComparisonTarget(
                        operator=m.Equal(),
                        comparator=m.SimpleString('"__main__"') | m.SimpleString("'__main__'"),
                    ),
                ],
            ),
        ),
    )


def _is_preamble_statement(node: cst.BaseStatement) -> bool:
    """Check if a statement belongs in the preamble."""
    return (
        is_docstring(node)
        or _is_import(node)
        or is_simple_assignment(node)
        or _is_type_checking_block(node)
    )


def is_simple_assignment(node: cst.CSTNode) -> bool:
    """Check if a statement is a simple assignment (e.g. module-level constants)."""
    if not isinstance(node, cst.SimpleStatementLine):
        return False
    return all(isinstance(stmt, (cst.Assign, cst.AnnAssign)) for stmt in node.body)


def is_docstring(node: cst.CSTNode) -> bool:
    """Check if a statement is a module-level string expression (docstring)."""
    return m.matches(
        node,
        m.SimpleStatementLine(body=[m.Expr(value=m.ConcatenatedString() | m.SimpleString())]),
    )


def _is_import(node: cst.BaseStatement) -> bool:
    """Check if a statement is an import or from-import."""
    return m.matches(
        node,
        m.SimpleStatementLine(body=[m.Import() | m.ImportFrom()]),
    )


def _is_type_checking_block(node: cst.BaseStatement) -> bool:
    """Check if a statement is an `if TYPE_CHECKING:` block."""
    return m.matches(
        node,
        m.If(test=m.Name("TYPE_CHECKING")),
    )
