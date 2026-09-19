---
description: Maintain CLI commands and document differences from the desktop workflow
---

# /cli — CLI Maintenance

Read `docs/cli_reference.md` and `src/pdo/cli/` before changing a command.

1. Use the shared authenticated TCP client in `cli/client.py`; daemon lifecycle commands use the detached launcher and lifecycle helpers.
2. Check both text and JSON output. Import/export acknowledge background work; completion and failures come from `status` (`busy`, `last_result`). `optimize --watch` is text-only.
3. Preserve or explicitly change the CLI contract: imports append, exports default to UTF-8/semicolon/CRLF, and desktop grouped retries/correction imports have no CLI flags.
4. Cover config forwarding, error exit codes, and backend reporting when changing those paths. Known limitations are recorded in `docs/documentation_audit.md`; do not assume the help text guarantees implemented behavior.
5. Run `tests/test_cli.py`, `tests/test_cli_json.py`, `tests/test_config_cmd.py`, and `tests/test_version_check.py`, plus integration tests for daemon interactions. Update user examples when behavior changes.

Follow [AGENTS.md](../../AGENTS.md), the [Development guide](../../docs/development.md), and the [Git workflow](../rules/rules.md#git--workflow). Work on the current branch, request confirmation before committing, and merge only on explicit request.
