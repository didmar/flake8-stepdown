"""CLI entry point for flake8-stepdown."""

from __future__ import annotations

import argparse
import sys
from fnmatch import fnmatch
from pathlib import Path

from flake8_stepdown.core.ordering import order_module
from flake8_stepdown.reporter import format_diff, format_violations

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_ERROR = 2


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        Exit code: 0 (clean), 1 (violations/changes), 2 (error).

    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Handle stdin
    if args.stdin_filename:
        source = sys.stdin.read()
        code, output = _process_source(source, args.stdin_filename, args)
        if output:
            _write_output(output)
        return code

    if not args.files:
        sys.stderr.write("Error: no files specified\n")
        return EXIT_ERROR

    filepaths = _resolve_paths(args.files, args.exclude)
    if not filepaths:
        return EXIT_OK

    exit_code = EXIT_OK
    for filepath in filepaths:
        code = _process_file(filepath, args)
        if code == EXIT_ERROR:
            return EXIT_ERROR
        exit_code = max(exit_code, code)

    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="stepdown",
        description="Enforce top-down function ordering in Python",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("files", nargs="*", help="Files or directories to check")
    common.add_argument("--exclude", action="append", default=[], help="Glob patterns to exclude")
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug info (mutual recursion info on stderr)",
    )
    common.add_argument(
        "--stdin-filename",
        help="Read from stdin, use this filename for output",
    )

    check_parser = subparsers.add_parser("check", parents=[common], help="Report violations")
    check_parser.add_argument(
        "--format",
        dest="fmt",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )

    subparsers.add_parser("diff", parents=[common], help="Show unified diff")
    subparsers.add_parser("fix", parents=[common], help="Rewrite files in place")

    return parser


def _resolve_paths(paths: list[str], exclude: list[str]) -> list[str]:
    """Expand directories to .py files and apply exclude patterns."""
    resolved: list[str] = []
    for entry in paths:
        p = Path(entry)
        if p.is_dir():
            for py_file in sorted(p.rglob("*.py")):
                filepath = str(py_file)
                if not any(fnmatch(filepath, pat) for pat in exclude):
                    resolved.append(filepath)
        elif not any(fnmatch(entry, pat) for pat in exclude):
            resolved.append(entry)
    return resolved


def _process_file(filepath: str, args: argparse.Namespace) -> int:
    """Process a single file and handle output."""
    path = Path(filepath)
    if not path.exists():
        sys.stderr.write(f"Error: {filepath} not found\n")
        return EXIT_ERROR

    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError) as e:
        sys.stderr.write(f"Error reading {filepath}: {e}\n")
        return EXIT_ERROR

    code, output = _process_source(source, filepath, args)

    if args.command == "fix" and code == EXIT_VIOLATIONS and output:
        path.write_text(output)
    elif output:
        _write_output(output)

    return code


def _process_source(
    source: str,
    filename: str,
    args: argparse.Namespace,
) -> tuple[int, str]:
    """Process a single source file and return (exit_code, output)."""
    compute_rewrite = args.command != "check"
    result = order_module(source, compute_rewrite=compute_rewrite)

    if args.verbose and result.mutual_recursion_groups:
        for group in result.mutual_recursion_groups:
            sys.stderr.write(
                f"{filename}: mutual recursion between {', '.join(group)}; original order preserved\n"
            )

    if args.command == "check":
        output = format_violations(result.violations, filename=filename, fmt=args.fmt)
        return (EXIT_VIOLATIONS if result.violations else EXIT_OK), output

    if args.command == "diff":
        if result.reordered_source is not None:
            output = format_diff(source, result.reordered_source, filename=filename)
            return EXIT_VIOLATIONS, output
        return EXIT_OK, ""

    # fix command
    if result.reordered_source is not None:
        return EXIT_VIOLATIONS, result.reordered_source
    return EXIT_OK, ""


def _write_output(output: str) -> None:
    """Write output to stdout with trailing newline if needed."""
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")


if __name__ == "__main__":
    sys.exit(main())
