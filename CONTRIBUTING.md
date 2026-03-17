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
