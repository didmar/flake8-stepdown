"""Profile each pipeline stage and identify performance bottlenecks.

Usage:
    uv run python benchmarks/profile_stages.py --chain 500
    uv run python benchmarks/profile_stages.py --wide 200
    uv run python benchmarks/profile_stages.py path/to/file.py
    uv run python benchmarks/profile_stages.py --scaling    # compare across sizes
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import time
from pathlib import Path

from flake8_stepdown.core.bindings import extract_bindings
from flake8_stepdown.core.graph import (
    attach_no_binding_stmts,
    build_normalized_graph,
    find_sccs,
    topological_sort,
)
from flake8_stepdown.core.ordering import order_module
from flake8_stepdown.core.parser import compute_line_numbers, parse_source, segment
from flake8_stepdown.core.references import detect_future_annotations, extract_refs
from flake8_stepdown.rewriter import rewrite
from flake8_stepdown.types import Statement


def generate_chain(n: int) -> str:
    """Generate a bottom-up call chain of n functions."""
    lines: list[str] = []
    for i in range(n):
        lines.append(f"def func_{i}():")
        if i == 0:
            lines.append("    pass")
        else:
            lines.append(f"    func_{i - 1}()")
        lines.append("")
        lines.append("")
    return "\n".join(lines)


def generate_wide(n: int) -> str:
    """Generate n independent functions with no cross-references."""
    lines: list[str] = []
    for i in range(n):
        lines.append(f"def func_{i}(x):")
        lines.append(f"    return x + {i}")
        lines.append("")
        lines.append("")
    return "\n".join(lines)


def profile_stages(source: str, label: str) -> dict[str, float]:
    """Run each pipeline stage individually and measure time."""
    timings: dict[str, float] = {}

    # 1. parse_source
    t0 = time.perf_counter()
    module = parse_source(source)
    timings["parse"] = time.perf_counter() - t0

    # 2. compute_line_numbers (replaces MetadataWrapper)
    t0 = time.perf_counter()
    positions = compute_line_numbers(source, module)
    timings["line_numbers"] = time.perf_counter() - t0

    # 3. segment
    t0 = time.perf_counter()
    seg = segment(module)
    timings["segment"] = time.perf_counter() - t0

    if not seg.interstitials:
        print(f"  [{label}] No interstitials found, skipping remaining stages.")
        return timings

    # 4. extract_bindings
    t0 = time.perf_counter()
    statements = extract_bindings(seg.interstitials, positions)
    timings["bindings"] = time.perf_counter() - t0

    # 5. extract_refs
    t0 = time.perf_counter()
    has_future = detect_future_annotations(seg.preamble)
    statements = extract_refs(statements, has_future_annotations=has_future)
    timings["references"] = time.perf_counter() - t0

    # 6. grouping + merge
    t0 = time.perf_counter()
    groups = attach_no_binding_stmts(statements)
    merged: list[Statement] = []
    for group in groups:
        all_bindings: frozenset[str] = frozenset().union(*(s.bindings for s in group))
        all_immediate: frozenset[str] = frozenset().union(*(s.immediate_refs for s in group))
        all_deferred: frozenset[str] = frozenset().union(*(s.deferred_refs for s in group))
        merged.append(
            Statement(
                node=group[0].node,
                start_line=group[0].start_line,
                end_line=group[-1].end_line,
                bindings=all_bindings,
                immediate_refs=all_immediate,
                deferred_refs=all_deferred,
                is_overload_group=group[0].is_overload_group,
            ),
        )
    timings["grouping"] = time.perf_counter() - t0

    # 7. graph + scc + sort
    t0 = time.perf_counter()
    graph = build_normalized_graph(merged)
    timings["graph"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    num_nodes = len(merged)
    sccs = find_sccs(graph, num_nodes)
    timings["scc"] = time.perf_counter() - t0

    for scc in sccs:
        scc_set = set(scc)
        for node in scc:
            graph[node] = {s for s in graph[node] if s not in scc_set}

    t0 = time.perf_counter()
    new_order = topological_sort(graph, num_nodes)
    timings["sort"] = time.perf_counter() - t0

    if new_order is None:
        new_order = list(range(num_nodes))

    # 8. rewrite
    t0 = time.perf_counter()
    expanded_order: list[int] = []
    offsets: list[int] = []
    offset = 0
    for group in groups:
        offsets.append(offset)
        offset += len(group)
    for group_idx in new_order:
        group = groups[group_idx]
        base = offsets[group_idx]
        expanded_order.extend(base + j for j in range(len(group)))
    all_nodes = [s.node for group in groups for s in group]
    rewrite(seg.module, seg.preamble, all_nodes, seg.postamble, expanded_order)
    timings["rewrite"] = time.perf_counter() - t0

    return timings


def print_stage_table(timings: dict[str, float], label: str) -> None:
    """Print a formatted table of stage timings."""
    total = sum(timings.values())
    print(f"\n{'=' * 65}")
    print(f"  Stage Breakdown: {label}")
    print(f"{'=' * 65}")
    print(f"  {'Stage':<20} {'Time (ms)':>12} {'% of total':>12}")
    print(f"  {'-' * 20} {'-' * 12} {'-' * 12}")
    for stage, t in timings.items():
        pct = (t / total * 100) if total > 0 else 0
        bar = "#" * int(pct / 2)
        print(f"  {stage:<20} {t * 1000:>10.2f}ms {pct:>10.1f}%  {bar}")
    print(f"  {'-' * 20} {'-' * 12} {'-' * 12}")
    print(f"  {'TOTAL':<20} {total * 1000:>10.2f}ms {'100.0%':>12}")


def run_cprofile(source: str, label: str, top_n: int = 20) -> None:
    """Run cProfile on the full order_module pipeline."""
    print(f"\n{'=' * 65}")
    print(f"  cProfile: order_module() — {label}")
    print(f"{'=' * 65}")

    pr = cProfile.Profile()
    pr.enable()
    order_module(source)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(top_n)
    print(s.getvalue())

    # Also show by tottime
    print(f"\n  Top {top_n} by total time (self):")
    s2 = io.StringIO()
    pstats.Stats(pr, stream=s2).sort_stats("tottime").print_stats(top_n)
    print(s2.getvalue())


def run_scaling() -> None:
    """Compare timings across different input sizes."""
    sizes = [50, 100, 200, 500, 1000]

    print(f"\n{'=' * 80}")
    print("  SCALING ANALYSIS: chain pattern")
    print(f"{'=' * 80}")

    all_timings: dict[int, dict[str, float]] = {}
    for n in sizes:
        source = generate_chain(n)
        timings = profile_stages(source, f"chain_{n}")
        all_timings[n] = timings
        print_stage_table(timings, f"chain_{n} ({len(source)} chars)")

    # Summary comparison table
    stages = list(all_timings[sizes[0]].keys())
    print(f"\n{'=' * 80}")
    print("  SCALING SUMMARY (ms)")
    print(f"{'=' * 80}")
    header = f"  {'Stage':<15}" + "".join(f" {'n=' + str(n):>10}" for n in sizes)
    print(header)
    print(f"  {'-' * 15}" + "".join(f" {'-' * 10}" for _ in sizes))
    for stage in stages:
        row = f"  {stage:<15}"
        for n in sizes:
            t = all_timings[n].get(stage, 0)
            row += f" {t * 1000:>9.2f}ms" if t > 0 else f" {'—':>10}"
        print(row)
    totals = f"  {'TOTAL':<15}"
    for n in sizes:
        totals += f" {sum(all_timings[n].values()) * 1000:>9.2f}ms"
    print(f"  {'-' * 15}" + "".join(f" {'-' * 10}" for _ in sizes))
    print(totals)

    # Show cProfile for the largest size
    run_cprofile(generate_chain(sizes[-1]), f"chain_{sizes[-1]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile flake8-stepdown pipeline stages")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--chain", type=int, metavar="N", help="Profile a synthetic call chain of N functions"
    )
    group.add_argument("--wide", type=int, metavar="N", help="Profile N independent functions")
    group.add_argument(
        "--scaling", action="store_true", help="Run scaling analysis across multiple sizes"
    )
    group.add_argument("file", nargs="?", help="Path to a Python file to profile")
    args = parser.parse_args()

    if args.scaling:
        run_scaling()
        return

    if args.chain:
        source = generate_chain(args.chain)
        label = f"chain_{args.chain}"
    elif args.wide:
        source = generate_wide(args.wide)
        label = f"wide_{args.wide}"
    else:
        path = Path(args.file)
        source = path.read_text()
        label = path.name

    timings = profile_stages(source, label)
    print_stage_table(timings, label)
    run_cprofile(source, label)


if __name__ == "__main__":
    main()
