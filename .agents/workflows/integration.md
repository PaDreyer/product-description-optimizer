---
description: Validate CLI and desktop workflows against the shared daemon
---

# /integration — Integration Validation

Use the existing integration suites; run all commands from the repository root with the project virtual environment. See `docs/development.md` for platform-specific setup and Qt dependencies.

1. Select relevant cases from `tests/test_integration.py`, `tests/test_desktop.py`, `tests/test_desktop_interactions.py`, and `tests/test_linux_tray.py`.
2. Run the complete suite with coverage (`make test` on Linux; direct Python commands from the development guide on Windows) and `make lint` or equivalent Ruff commands.
3. Local socket binding is required for daemon tests. The private D-Bus test requires `dbus-run-session`; headless Qt still requires system libraries.
4. For a manual smoke test, use temporary data/log directories and an explicitly chosen `dummy` backend. Map the actual CSV description column, wait for asynchronous import/export completion, and inspect job results.
5. Exercise pause/resume, restart with pending rows, preservation of successful results during group retries, corrections by ID, and custom CSV output as relevant.
6. For release validation, follow `docs/RELEASE.md` on both target systems. The root Docker development environment and Linux release builder are different workflows.

Follow [AGENTS.md](../../AGENTS.md), the [Development guide](../../docs/development.md), and the [Git workflow](../rules/rules.md#git--workflow). Work on the current branch, request confirmation before committing, and merge only on explicit request.
