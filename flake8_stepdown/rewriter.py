"""Source-level rewriting using LibCST tree manipulation."""

from __future__ import annotations

import libcst as cst


def rewrite(
    module: cst.Module,
    preamble: list[cst.CSTNode],
    interstitial_nodes: list[cst.CSTNode],
    postamble: list[cst.CSTNode],
    ordered_indices: list[int],
) -> str:
    """Rewrite a module with reordered interstitial statements.

    Args:
        module: The original parsed CST module.
        preamble: Preamble nodes (anchored, not reordered).
        interstitial_nodes: All interstitial CST nodes in original order.
        postamble: Postamble nodes (anchored, not reordered).
        ordered_indices: New ordering of interstitial nodes by index.

    Returns:
        Rewritten source code as a string.

    """
    # Reorder interstitial nodes
    reordered = [interstitial_nodes[i] for i in ordered_indices]

    preamble_stmts = [n for n in preamble if isinstance(n, cst.BaseStatement)]
    prev_node: cst.BaseStatement | None = preamble_stmts[-1] if preamble_stmts else None

    # Normalize blank lines between top-level defs
    normalized, prev_node = _normalize_block(reordered, prev_node, is_first_block=not preamble)

    # Normalize postamble leading lines
    normalized_postamble, prev_node = _normalize_block(postamble, prev_node)

    # Build new body
    new_body = [*preamble_stmts, *normalized, *normalized_postamble]

    new_module = module.with_changes(body=new_body)
    return new_module.code


def _normalize_block(
    nodes: list[cst.CSTNode],
    prev_node: cst.BaseStatement | None,
    *,
    is_first_block: bool = False,
) -> tuple[list[cst.BaseStatement], cst.BaseStatement | None]:
    """Normalize blank lines for a block of nodes, returning normalized nodes and last node."""
    normalized: list[cst.BaseStatement] = []
    for i, raw_node in enumerate(nodes):
        if not isinstance(raw_node, cst.BaseStatement):
            continue
        blanks = _compute_desired_blanks(raw_node, prev_node, is_first=i == 0 and is_first_block)
        normalized.append(_normalize_leading_lines(raw_node, desired_blanks=blanks))
        prev_node = raw_node
    return normalized, prev_node


def _compute_desired_blanks(
    node: cst.BaseStatement,
    prev_node: cst.BaseStatement | None,
    *,
    is_first: bool,
) -> int:
    """Compute the desired number of blank lines before a statement."""
    if is_first:
        return 0
    if isinstance(node, (cst.FunctionDef, cst.ClassDef)) or (
        prev_node is not None and isinstance(prev_node, (cst.FunctionDef, cst.ClassDef))
    ):
        return 2
    orig_blanks = (
        len(node.leading_lines)
        if isinstance(node, (cst.SimpleStatementLine, cst.BaseCompoundStatement))
        else 0
    )
    return min(orig_blanks, 1)


def _normalize_leading_lines(
    node: cst.BaseStatement,
    desired_blanks: int,
) -> cst.BaseStatement:
    """Set the number of blank lines before a statement."""
    leading = [
        cst.EmptyLine(
            indent=True,
            whitespace=cst.SimpleWhitespace(""),
            comment=None,
            newline=cst.Newline(value=None),
        )
        for _ in range(desired_blanks)
    ]
    return node.with_changes(leading_lines=leading)
