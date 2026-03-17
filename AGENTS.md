# AGENTS.md

Quick reference for AI agents working on the PDO (Product Description Optimizer) codebase.

## Quick Reference Commands

```bash
# Run a single test
python -m pytest tests/test_module.py::TestClass::method_name -v

# Run all tests in a file
python -m pytest tests/test_module.py -v

# Run all tests with coverage
python -m pytest tests/ -v --cov=src/pdo --cov-report=term-missing

# Lint and format check
make lint          # equivalent to: ruff check src/ tests/ && ruff format --check src/ tests/

# Auto-format code
make format        # equivalent to: ruff format src/ tests/
```

## Project Structure

```
src/pdo/
├── cli/          # CLI commands and utilities
├── core/         # Business logic (db, importer, optimizer, exporter)
├── daemon/        # Background process (server, worker, pid)
├── protocol/      # IPC message definitions
└── config.py      # Configuration management
```

## Code Style - Quick Reference

### File Header
- Always start with: `from __future__ import annotations`

### Import Order
1. Standard library
2. Third-party dependencies
3. Local imports (absolute: `from pdo.core.xxx import`)

### Type Hints
- Use modern syntax only: `dict[str, str]`, `X | None`, `list[Type]`
- Not: `Dict[str, str]`, `Optional[X]`, `List[Type]`

### Naming Conventions
- Functions/variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE` (module-level)
- Private methods: `_prefix`

### Docstrings
- Google-style on all public functions, classes, and modules
- Include Args/Returns/Raises sections

### Error Handling
- Use custom exceptions from `pdo.exceptions`
- Base class: `PdoError`
- Specific: `ImportDataError`, `DatabaseError`, `OptimizationError`, `ExportError`, `ProtocolError`, `ConfigError`, `DaemonNotRunningError`

### Logging
- Module-level: `log = logging.getLogger(__name__)`
- Use: `log.info()`, `log.warning()`, `log.exception()`

### Dataclasses
- Prefer `@dataclass(frozen=True)` for immutable data structures

## Testing Guidelines

- Use fixtures from `tests/conftest.py` (db, tmp_path, tmp_data_dir)
- Test naming: `test_<method_name>` or class-based `Test<ClassName>`
- For database tests: Use `Database(":memory:")` for in-memory SQLite
- Import test data from `tests/fixtures/`
- Aim for ≥80% code coverage on `src/pdo/`

## Adding New Optimizer Backends

1. Inherit from `BaseLLMOptimizer` in `src/pdo/core/`
2. Implement `_call_llm(*, system: str, user: str, temperature: float) -> str`
3. Use `self._retry_delay(attempt)` for exponential backoff
4. Register in `registry.py`:
   - Add availability check: `_check_<name>_available()`
   - Add to `list_optimizers()` with dot-namespace config keys (e.g., `optimizer_name.api_key`)
   - Add factory logic in `create_optimizer()` using dot-namespace pattern
5. Add optional dependency to `pyproject.toml` [project.optional-dependencies]

### Example: ZhipuAI Optimizer

See `src/pdo/core/zhipuai_optimizer.py` for a complete implementation using:
- Dot-namespace config: `zhipuai.api_key`, `zhipuai.model`
- Environment variable: `ZHIPUAI_API_KEY`
- SDK: `zhipuai` (OpenAI-compatible API)

## Configuration Naming Convention

Use dot-namespace for optimizer-specific settings:

| Pattern | Example | CLI Command |
|---------|---------|-------------|
| `optimizer_name.setting` | `zhipuai.api_key` | `pdo config set zhipuai.api_key <key>` |
| `optimizer_name.setting` | `local_llm.address` | `pdo config set local_llm.address <url>` |
| `optimizer_name.setting` | `gemini.api_key` | `pdo config set gemini.api_key <key>` |

**Environment variables** follow provider's convention:
- ZhipuAI: `ZHIPUAI_API_KEY`
- Gemini: `GEMINI_API_KEY`
- (Local LLMs typically use config only)

**Config file** (`~/.pdo/config.toml`):
```toml
[pdo]
optimizer = "zhipuai"
zhipuai.api_key = "..."
zhipuai.model = "glm-4"
local_llm.address = "http://127.0.0.1:11434/v1"
```

## Development Checklist

- ✅ Run `ruff check` before any commit
- ✅ Run `python -m pytest` (all tests must pass)
- ✅ Run tests for changed modules
- ✅ Follow existing patterns (don't reinvent)
- ✅ Ensure ≥80% coverage maintained
- 📝 **NOTE:** For local development, use the project venv at `venv/`:
  ```bash
  source venv/bin/activate
  ```

## References

- Design/architecture: `.agents/rules/rules.md`
- All commands: `Makefile` (test, lint, format)
- Ruff/pytest config: `pyproject.toml` [tool.ruff] and [tool.pytest]
