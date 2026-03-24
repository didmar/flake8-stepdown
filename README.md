# flake8-stepdown

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
[![codecov](https://codecov.io/gh/didmar/flake8-stepdown/graph/badge.svg)](https://codecov.io/gh/didmar/flake8-stepdown)

A [flake8](https://flake8.pycqa.org/) plugin that enforces **top-down (newspaper-style) function ordering** in Python modules.

This is inspired by Robert C. Martin's "Clean Code" stepdown rule: High-level logic first, details later. When reading a module, callers should appear before callees, so you can read the code from top to bottom like a newspaper article.

## Violation codes

| Code | Meaning |
|---------|---------|
| TDP001 | Function is defined in the wrong order (should appear after another function) |

## Installation

```bash
pip install flake8-stepdown
```

The plugin registers itself with flake8 automatically. Verify it's installed:

```bash
flake8 --version
```

You should see `flake8-stepdown` in the list of installed plugins.

## Usage

### As a flake8 plugin

Just run flake8 as usual, the plugin will report `TDP001` violations:

```bash
flake8 your_module.py
```

### Standalone CLI

The package also provides a `stepdown` command with three subcommands:

```bash
# Report violations
stepdown check your_module.py

# Show a unified diff of the proposed reordering
stepdown diff your_module.py

# Rewrite files in place
stepdown fix your_module.py
```

Use `-v` / `--verbose` to show mutual recursion info on stderr.

## Development

### Prerequisites

- [UV](https://docs.astral.sh/uv/) (Python package manager)

### Setup

```bash
uv sync
```

### Linting

```bash
./lint.sh
```

### Testing

```bash
uv run pytest
```

Tests are organized by pipeline stage (`test_parser.py`, `test_graph.py`, `test_rewriter.py`, etc.). The rewriter uses **snapshot testing**: `tests/fixtures/` contains input Python files exercising various scenarios (bottom-up ordering, mutual recursion, decorators, etc.), and `tests/snapshots/` contains the expected output after rewriting. The test suite asserts correctness against snapshots, idempotency, and syntax validity.

### Pre-commit hooks

Pre-commit hooks are installed automatically. To run manually:

```bash
uv run pre-commit run --all-files
```

## CI

GitHub Actions runs linting, type checking, and tests on every push to `main` and on pull requests.

## Publishing to PyPI

This project uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) via GitHub Actions.

To publish a new version:

1. Bump the version with `uv version --bump patch` (or `minor`/`major`)
2. Update `__version__` in `flake8_stepdown/__init__.py` to match
3. Create a GitHub release with a tag matching the version (e.g., `v0.1.0`)
4. The publish workflow will automatically build and upload to PyPI

> **First-time setup:** Configure a trusted publisher on PyPI under your project's settings (Publishing tab). Use `publish.yml` as the workflow name and `publish` as the environment name.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for code style, conventions, and development workflow.
