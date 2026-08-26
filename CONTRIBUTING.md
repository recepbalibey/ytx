# Contributing to YTX

## Getting Started

```bash
git clone https://github.com/ytx-project/ytx.git
cd ytx
pip install -e ".[dev]"
```

## Running Tests

```bash
# Unit tests (no network required)
pytest tests/unit/

# All tests including integration (requires network)
pytest
```

## Code Quality

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the project design and module structure.

## Pull Requests

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure `ruff check` and `pytest` pass
5. Submit a pull request

## Adding a New Transcription Provider

1. Create a new file in `src/ytx/transcription/`
2. Implement the `LocalTranscriptionProvider` interface from `base.py`
3. Add tests (mock the model)
4. Update the CLI to support selecting the provider

## Adding a New Output Format

1. Create a new file in `src/ytx/output/`
2. Implement the writer function signature: `(result, path, include_timestamps) -> str`
3. Register it in `pipeline.py`'s `_write_output` method
4. Add tests
