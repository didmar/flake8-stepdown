#!/usr/bin/env bash
set -euo pipefail
uv run stepdown fix flake8_stepdown/
ruff check . --fix && ruff format .
