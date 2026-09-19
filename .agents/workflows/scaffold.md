---
description: Maintain the project environment, packaging, and entry points
---

# /scaffold — Project Setup and Packaging

Use the existing package layout; setup no longer requires creating a project skeleton.

1. Read `pyproject.toml`, `AGENTS.md`, and `docs/development.md` before changing packaging or dependencies.
2. Keep Python 3.12+, the `pdo` CLI entry point, and the `pdo-desktop` GUI entry point consistent with supported Linux/Windows installs.
3. Use `scripts/setup-dev.sh` or `scripts/setup-dev.ps1` to prepare `venv/`. Update setup/build dependency lists together when adding a provider or desktop dependency.
4. For a version change, keep `project.version` and `pdo.__version__` equal and follow `docs/RELEASE.md`. Never reset the version to an old scaffolding example.
5. Verify `pdo --help`, `pdo-desktop` startup in a suitable environment, Ruff, and the relevant packaging tests. Release builds also require packaged smoke tests.

Follow [AGENTS.md](../../AGENTS.md), the [Development guide](../../docs/development.md), and the [Git workflow](../rules/rules.md#git--workflow). Work on the current branch, request confirmation before committing, and merge only on explicit request.
