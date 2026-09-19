# Development guide

Run commands from the repository root. [AGENTS.md](../AGENTS.md) covers code conventions and [project rules](../.agents/rules/rules.md) cover architecture and the Git workflow. Keep the current branch unless the user explicitly requests a branch change; commits require confirmation and merges require an explicit request.

## Set up and test

Python 3.12+ is required. The setup scripts install the project in `venv/` with development tools, PySide6, Linux `dbus-next`, and all three provider SDKs.

Linux:

```bash
./scripts/setup-dev.sh
source venv/bin/activate
make lint
QT_QPA_PLATFORM=offscreen make test
```

The Linux script uses `python3`. It does not install system libraries. For headless tests, CI on Ubuntu 22.04 installs:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  libegl1 libgl1 libglib2.0-0 libfontconfig1 libxkbcommon0 dbus
```

A visible Linux desktop also needs the Qt platform libraries for its display server. The full release-build set is in [packaging/linux/Dockerfile](../packaging/linux/Dockerfile). `QT_QPA_PLATFORM=offscreen` avoids a display requirement but does not remove Qt's system-library requirements. The tray integration test needs `dbus-run-session`; daemon tests need permission to bind local sockets.

Windows PowerShell:

```powershell
.\scripts\setup-dev.ps1
.\venv\Scripts\Activate.ps1
python -m ruff check src/ tests/
python -m ruff format --check src/ tests/
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests/ -v --cov=src/pdo --cov-report=term-missing
Remove-Item Env:QT_QPA_PLATFORM
pdo-desktop
```

The Windows setup script defaults to `py -3.12`. Use `-Python <path-to-python.exe>` for a different interpreter. The Makefile defaults to `venv/bin/python` and `venv/bin/ruff`, so use the direct commands above on Windows.

For focused validation, select the tests relevant to a change:

| Change | Test files under `tests/` |
| --- | --- |
| CLI and configuration | `test_cli.py`, `test_cli_json.py`, `test_config_cmd.py`, `test_registry.py` |
| CSV, corrections, export | `test_importer.py`, `test_exporter.py`, `test_batch_workflow.py` |
| Database and recovery | `test_db.py`, `test_instance_lock.py`, `test_daemon.py` |
| Desktop workflow and model discovery | `test_desktop.py`, `test_desktop_interactions.py` |
| Tray | `test_linux_tray.py`, tray cases in `test_desktop.py` |
| Daemon, protocol, lifecycle | `test_daemon.py`, `test_protocol.py`, `test_version_check.py`, `test_integration.py`, lifecycle cases in `test_desktop.py` |
| AI adapters | `test_optimizer.py`, `test_gemini_optimizer.py`, `test_zhipuai_optimizer.py`, `test_local_llm_optimizer.py`, `test_openai_optimizer.py`, `test_codex_client.py` |

For example:

```bash
venv/bin/python -m pytest tests/test_batch_workflow.py tests/test_desktop_interactions.py -v
```

`make test` runs the full suite with coverage. `make test-unit` excludes only `test_integration.py`; it still includes desktop, socket, and D-Bus tests. Maintain the project's coverage target of at least 80%; neither pytest configuration nor CI currently enforces a numeric coverage threshold. CI runs the complete suite and Ruff on Linux with Python 3.12. The Windows release build runs the selected suite listed in `scripts/build-windows.ps1`.

## Architecture and state

The CLI and desktop session are clients of a single daemon per data directory. The desktop can inspect a source CSV for preview and query a model server for discovery, but database mutation and batch processing belong to the daemon. The worker accepts one pipeline job at a time; pause applies to optimization between products.

- `daemon/launcher.py`, `entry.py`, and `startup.py` implement detached startup and readiness notification on Linux and Windows, including packaged executables.
- `daemon/endpoint.py` publishes the ephemeral loopback TCP port and authentication token in `daemon.endpoint`. Unix sockets are used only to discover and stop older daemons during migration.
- `daemon/lifecycle.py`, `pid.py`, and `core/instance_lock.py` serialize start/stop, validate process identity, and protect database ownership.
- `protocol/messages.py` sends newline-delimited UTF-8 JSON with app version and authentication metadata. Update `PROTOCOL_REVISION` when new handlers are required by clients. Authenticated `ping` and `stop` remain usable across app versions.
- `desktop/session.py` supplies the GUI's daemon operations; `desktop/app.py`, `controls.py`, and `linux_tray.py` implement the screens, shared controls, and Linux tray.
- `core/openai_optimizer.py` uses the Responses API; `codex_optimizer.py` and `codex_client.py` implement optional subscription access through the official Codex stdio app-server. Codex is installed separately. Tests use a local protocol fixture without real credentials, browser login, or billable model calls.
- `core/csv_format.py`, `error_groups.py`, and `model_discovery.py` support CSV dialects, bulk recovery, and model selection.

The default runtime layout is:

```text
~/.pdo/
├── config.toml
├── codex/                 # Optional PDO-specific Codex credentials and runtime state
├── data/
│   ├── pdo.db              # SQLite; WAL sidecar files can exist while open
│   ├── daemon.pid         # Daemon process identity
│   ├── daemon.endpoint    # Loopback TCP port and authentication token
│   ├── pdo.lock           # Database ownership lock
│   └── launch.lock        # Start/stop coordination lock
└── logs/
    ├── daemon.log         # Rotated at 5,000,000 bytes; three backups
    └── daemon-startup.log
```

SQLite stores original CSV columns as JSON in `products.raw_data`, with extracted ID, description, context, result, status, and error fields alongside it. `pipeline_state` stores the singleton stage/counters, `column_mappings` stores roles, and `metadata` stores source headers and format. A data directory holds one active batch, not a separate database for every run.

On daemon startup, interrupted `processing` rows return to `pending`; work resumes only after another optimization request. Desktop replacement import uses a staging database. CLI import appends and can leave partial progress if interrupted. Exports write a temporary file and replace the destination after success; interrupted imports and exports must be restarted. Review [GUI/CLI differences](cli_reference.md) before extending either interface.

## Adding a provider

Implement `BaseLLMOptimizer._call_llm` and register the backend in `core/registry.py`. Keep shared model/address defaults in `core/provider_defaults.py`. Use provider-prefixed config keys and add the optional SDK dependency to `pyproject.toml`.

For desktop and release support, also update the provider controls/settings in `desktop/app.py`, the setup/build dependency lists, and PyInstaller hidden imports in both platform build scripts. Add adapter, registry, and desktop coverage as appropriate. Document credentials, model selection, defaults, and the data sent to the provider.

## Docker development versus release builds

The root [Dockerfile](../Dockerfile) and `make docker-*` targets run a CLI daemon environment. It installs Gemini and OpenAI-compatible SDKs, but currently not ZhipuAI or the GUI. Enter with `make docker-shell` and run CLI commands inside the container: the daemon's endpoint is loopback-only in that container. The workspace mount makes CSV files available under `/app/workspace`; it does not persist `/var/lib/pdo/data`. `make docker-clean` removes the container and its unmounted state.

Linux release packages use the separate [packaging Dockerfile](../packaging/linux/Dockerfile) through `scripts/build-linux-container.sh`. Windows packaging uses Inno Setup. See the [Release guide](RELEASE.md) for build, publication, and target-system checks.
