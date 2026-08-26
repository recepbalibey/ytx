# Releasing YTX

1. Update `CHANGELOG.md` and the version in `pyproject.toml`.
2. Run `pytest tests/unit -q`, `ruff check src tests`, and `python3 -m build`.
3. Commit the version change and create an annotated Git tag such as `v0.2.0`.
4. Push the tag. GitHub creates a release with the built package files.

PyPI publishing is a separate step. Do not publish until the package name and release process are ready.
