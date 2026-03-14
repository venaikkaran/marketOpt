# CLAUDE.md

## Python Environment

**ALWAYS use `uv` for ALL Python-related operations. No exceptions.**

- `uv run` to execute scripts
- `uv add` to install dependencies
- `uv remove` to remove dependencies
- `uv sync` to sync the environment
- `uv lock` to update the lockfile
- NEVER use `pip`, `pip install`, `python -m pip`, `conda`, or any other package manager
- NEVER use bare `python` — use `uv run python` instead
- NEVER create venvs manually — `uv sync` handles this
