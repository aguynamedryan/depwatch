# Run the full test suite (matches CI)
test:
    uv run ruff check .
    uv run ruff format --check .
    uv run pytest -v
