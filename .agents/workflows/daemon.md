---
description: Maintain the shared daemon, authenticated TCP protocol, and safe lifecycle
---

# /daemon — Daemon and IPC Maintenance

Read `docs/development.md` and the existing daemon modules before changing lifecycle behavior.

1. CLI and GUI share `daemon/launcher.py`, `entry.py`, and `startup.py`. Use detached subprocess startup and readiness notification on Linux and Windows.
2. Current IPC is newline-delimited JSON over authenticated loopback TCP. `daemon.endpoint` in `data_dir` publishes port and token. Unix sockets are retained only for legacy migration.
3. Keep `launch.lock` start/stop coordination separate from `pdo.lock` database ownership. Validate process identity before signaling; remove runtime files only after ownership is released.
4. Maintain app-version checks and bump `PROTOCOL_REVISION` when new handlers require it. Authenticated `ping` and `stop` remain usable across versions. Logs are read by clients from the log file, not through a `logs` IPC action.
5. Keep one active worker job. On restart, requeue interrupted rows without automatically starting optimization. Preserve existing batches on failed desktop replacements and destination files on failed exports.
6. Run daemon, protocol, version, instance-lock, integration, and desktop lifecycle tests. Include packaged startup checks when touching the frozen executable path.

Follow [AGENTS.md](../../AGENTS.md), the [Development guide](../../docs/development.md), and the [Git workflow](../rules/rules.md#git--workflow). Work on the current branch, request confirmation before committing, and merge only on explicit request.
