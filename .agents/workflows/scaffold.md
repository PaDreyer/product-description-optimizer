---
description: Scaffold the project structure, pyproject.toml, config module, and install dev dependencies
---

# /scaffold — Project Scaffolding

Sets up the full project skeleton as defined in `.gemini/rules.md` so every subsequent workflow has a clean foundation.

## Steps

1. **Create the `src/` package layout.** Create all directories and `__init__.py` files for:
   - `src/pdo/`
   - `src/pdo/cli/`
   - `src/pdo/daemon/`
   - `src/pdo/core/`
   - `src/pdo/protocol/`

   Each `__init__.py` should contain a module-level docstring describing the package's purpose.

2. **Create `pyproject.toml`** in the project root with:
   - `[project]` section: name = `pdo`, version = `0.1.0`, requires-python = `>=3.12`
   - Dependencies: `click`, `rich`
   - `[project.optional-dependencies]` dev group: `pytest`, `pytest-cov`, `ruff`
   - `[project.scripts]` entry point: `pdo = "pdo.cli.main:cli"`
   - `[build-system]` using `hatchling` or `setuptools`
   - `[tool.ruff]` section with target-version = `"py312"`, line-length = 100

3. **Create `src/pdo/config.py`** with:
   - A `PdoConfig` dataclass holding: `data_dir`, `log_dir`, `socket_path`, `config_file_path`
   - Default paths under `~/.pdo/` (data, logs, socket, config)
   - A `load_config()` function that reads `~/.pdo/config.toml` (if it exists), merges with env vars (`PDO_` prefix), and returns a `PdoConfig` instance
   - Priority: CLI flags > env vars > config file > defaults (as per rules)

4. **Create `src/pdo/exceptions.py`** with:
   - `PdoError(Exception)` — base exception for the project
   - `DaemonNotRunningError(PdoError)`
   - `DatabaseError(PdoError)`
   - `ImportError_(PdoError)` (underscore to avoid shadowing the built-in)
   - `OptimizationError(PdoError)`
   - `ExportError(PdoError)`
   - `ProtocolError(PdoError)`

5. **Create a minimal `src/pdo/cli/main.py`** with:
   - A `click.Group` named `cli` as the root entry point
   - A `--json` global option stored in `click.Context`
   - A `--verbose` / `-v` flag
   - A placeholder `version` command that prints the version

6. **Create `tests/conftest.py`** with:
   - A `tmp_data_dir` fixture using `tmp_path` to create an isolated data directory
   - A `test_config` fixture returning a `PdoConfig` pointing to temp directories

7. **Delete the old `main.py`, `db.py`, and `requirements.txt`** from the project root — they are superseded by the new structure.

// turbo
8. **Install the project in editable mode:**
   ```bash
   cd /Users/pdreyer/Desktop/Carta-Mondo/Scripts/product_description_optimizer
   source venv/bin/activate && pip install -e ".[dev]"
   ```

// turbo
9. **Verify the setup:**
   ```bash
   source venv/bin/activate && pdo --help
   ```
   The CLI must print the help text with the version command visible.

// turbo
10. **Run ruff:**
    ```bash
    source venv/bin/activate && ruff check src/ tests/
    ```
    Fix any issues found.

11. **Commit:**
    ```bash
    git add -A && git commit -m "chore: scaffold project structure, config, and packaging"
    ```
