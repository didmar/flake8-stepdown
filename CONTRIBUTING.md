# Contributing

## Code style

Ruff enforces many rules automatically.
Run `./lint.sh` to auto-fix and format.

## Commands reference

| Task | Command |
|------|---------|
| Install deps | `uv sync` |
| Lint + format | `./lint.sh` |
| Type check | `uvx ty check .` |
| Run tests | `uv run pytest` |
| Pre-commit (manual) | `uv run pre-commit run --all-files` |

## Benchmarks

Per-stage performance benchmarks use [pytest-benchmark](https://pytest-benchmark.readthedocs.io/). Benchmarks are disabled during normal test runs.

| Task | Command |
|------|---------|
| Run benchmarks only | `uv run pytest benchmarks/ --benchmark-only --benchmark-enable --no-cov` |
| Benchmarks with JSON output | `uv run pytest benchmarks/ --benchmark-only --benchmark-enable --no-cov --benchmark-json=benchmark-results.json` |
| Save a baseline | `uv run pytest benchmarks/ --benchmark-only --benchmark-enable --no-cov --benchmark-save=baseline` |
| Compare against saved baseline | `uv run pytest benchmarks/ --benchmark-only --benchmark-enable --no-cov --benchmark-compare` |
