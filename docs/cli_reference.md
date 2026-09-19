# CLI Reference

Complete reference for all `pdo` commands. Every command supports `--help` for inline usage.

The CLI and desktop application use the same daemon on Linux and Windows. Clients reach it through an authenticated, loopback-only TCP endpoint published in the user's PDO data directory. The desktop application starts the daemon automatically. Release packages on both platforms contain the GUI; install the Python package separately for the CLI.

## Global Options

Place these flags before the command name. `--json` and `--verbose` can also be placed after a command that exposes them.

| Flag | Description |
|------|-------------|
| `--json` | Output machine-readable JSON; see the command-specific exceptions below |
| `--verbose`, `-v` | Accepted flag; currently stored in CLI context without changing logging |
| `--config <path>` | Select a config file for `config set/get/list` and `optimizer list` (top-level only) |

**Current limitation:** daemon commands, pipeline commands, `version`, and `logs` do not pass `--config` through to runtime configuration. Use `PDO_DATA_DIR` and `PDO_LOG_DIR` consistently in the daemon and all clients when selecting alternate runtime directories. `--config` does not select a different running daemon.

## Background jobs and JSON

Import, export, and optimization are asynchronous. A successful command response means the daemon accepted the job. Poll `pdo --json status` until `busy` is `false`, then inspect `last_result` before starting another operation. The daemon rejects new work while busy, including while optimization is paused.

- Import results include `imported_count`, `skipped_count`, `total_rows`, and `errors`.
- Optimization results include `succeeded`, `failed`, and `skipped`; individual product failures also appear in `progress.error` and `error_groups`.
- Export results include `total_exported` and `output_path`.
- An operation-level failure is reported in `last_result.error`.

`last_result` describes the most recent job in this daemon process. It is cleared when a new job starts and is not persisted across daemon restarts. `stage` alone is insufficient to detect success: optimization normally finishes at `idle`, while successful export sets `done`.

JSON schemas vary by command. Job acknowledgements have `success`; successful `status` outputs the status object directly, and `daemon status` outputs `running` and `responding`. `version` outputs `client_version` and `server_version`. A command error can still exit with code 0, so automation must inspect JSON errors and job results as well as the process exit code. `--json` disables the `optimize --watch` loop. `logs --json` reports that JSON log streaming is unsupported.

## Commands

### `pdo daemon start`

Start the background daemon process. The command waits for the daemon to publish its connection details and respond; startup failures are written to `~/.pdo/logs/daemon-startup.log`.

```bash
pdo daemon start              # start a detached daemon (Linux and Windows)
pdo daemon start --foreground  # run in foreground (see logs in real-time)
```

### `pdo daemon stop`

Stop the running daemon.

```bash
pdo daemon stop           # graceful stop via IPC; waits for the process to exit
pdo daemon stop --force   # stop the process, wait for exit, then clean stale files
```

If the endpoint is missing, `stop` uses the validated daemon PID to request shutdown. It reports success after the process exits. `--force` also uses SIGKILL, where available, when the daemon does not exit after SIGTERM.

### `pdo daemon status`

Check whether the daemon is running and responding.

### `pdo daemon repair`

Stop an unresponsive daemon with SIGTERM (and SIGKILL where available if it does not exit), wait for exit, then remove stale PID and endpoint files while holding the data-directory lock. If the process cannot be stopped, its runtime files are preserved. Repair does not reset the product database. Restart the daemon afterward and explicitly start optimization to process pending rows.

---

### `pdo import <file>`

Append CSV rows to the current database. Repeated imports can create duplicates; IDs are not deduplicated. Column mappings and source metadata are replaced by those of the latest import. For a new batch, export the previous results and confirm `pdo reset` before importing, or use desktop replacement import, which preserves the old batch if the new import fails.

| Flag | Description |
|------|-------------|
| `-m`, `--mapping ROLE:COLUMN` | Map a CSV column to a role (repeatable) |
| `-d`, `--delimiter CHAR` | CSV delimiter (default: `;`) |
| `-l`, `--limit N` | Read at most N source data rows; skipped rows count toward the limit (use a positive value) |

**Roles:**

| Role | Required | Description |
|------|----------|-------------|
| `product_id` | No | Product identifier; use exactly one unique ID column for desktop correction imports |
| `description` | Yes | At least one mapped column; multiple descriptions are joined with blank lines |
| `context` | No | Extra info for the AI (brand, title, specs, etc.) — repeatable |

Headers must be unique and nonempty. Encoding is detected (UTF-8, UTF-16 LE/BE, or CP1252), but the CLI separator stays `;` unless `--delimiter` is supplied. The desktop import uses detected CSV dialect settings. An empty description value is allowed if mapped context can supply the product information.

**Example:**

```bash
pdo import catalogue.csv \
  -m product_id:ProductID \
  -m description:Description \
  -m context:Title \
  -m context:Brand \
  -m "context:Feature 1"
```

---

### `pdo optimize`

Process pending products. Completed and failed products are skipped; use desktop error-group retries for failures. After a daemon restart, this command starts the remaining work. `pdo resume` only unpauses a still-running job.

| Flag | Description |
|------|-------------|
| `-w`, `--watch` | Poll until work finishes in text mode; ignored with `--json` |
| `-o`, `--optimizer NAME` | Choose backend: `gemini`, `zhipuai`, `local_llm`, `dummy` |

```bash
pdo optimize --watch
pdo optimize --optimizer zhipuai --watch
```

An explicit `--optimizer` also saves that backend in the daemon's config file and reloads provider settings. Without it, the worker uses its loaded `optimizer` setting. The default `auto` selects Gemini if its SDK and key are available, otherwise `dummy`; it does not automatically select ZhipuAI or a local server.

### `pdo optimizer list`

List registered backends and dependency/key checks in the CLI environment. The current `active` label and JSON `default` field show the **automatic fallback choice**, not the saved backend or the daemon's current job. The local backend is always listed as available; this is not a connectivity, model, or SDK check. Use desktop **Check connection** for local model discovery.

---

### `pdo export <file>`

Export optimized products to a CSV file.

| Flag | Description |
|------|-------------|
| `--include-errors` | Include products that failed optimization |

By default, export only successful products. `--include-errors` adds failed products, with empty optimized text; it excludes pending/processing rows and does not add `error_message`.

The output preserves original columns and adds `optimized_description` and `status`. Name collisions use `pdo_` and, if needed, a numeric suffix such as `pdo_status_2`.

The CLI format is **UTF-8 without BOM, semicolon separator, CRLF line endings, a header row, and minimal double-quote quoting**. It does not inherit the source format or desktop `export.format` preference. For other formats, all-product exports, error reports, or correction files, use the desktop export screen.

Export writes to a temporary file and replaces the destination only after success. The active source CSV path cannot be the destination. If no products match, the result is `total_exported: 0` and no file is created or replaced. Poll status to confirm completion.

---

### `pdo status`

Show current pipeline stage and counts (total, done, pending, errors), percentage, and pause state. JSON also includes `busy`, `processing` in `progress`, `last_result`, source metadata, error groups, and correction availability. No ETA is currently calculated.

### `pdo pause`

Request a pause between products. The current provider request may still finish. A paused job remains busy; import, export, and settings changes must wait until it finishes or is stopped.

### `pdo resume`

Unpause the current optimization. This does not restart a job after daemon shutdown or retry failed products; use `pdo optimize` for pending rows and the desktop error workflow for selective retries.

### `pdo reset`

Stop all operations and clear the database.

| Flag | Description |
|------|-------------|
| `-y`, `--yes` | Skip the confirmation prompt |
| `--keep` | Keep source products, column mappings, and metadata, but clear optimized descriptions/errors and mark every row pending |

`--keep` discards successful results too; it is not a selective retry. JSON mode skips the confirmation prompt even without `--yes`.

---

### `pdo logs`

Display the daemon log file (works even when the daemon is stopped).

| Flag | Description |
|------|-------------|
| `-f`, `--follow` | Tail the log and stream new lines |
| `-n`, `--lines N` | Number of lines to show (default: 50) |

### `pdo version`

Print client and daemon version. Works when the daemon is stopped; it reports `not running`. If versions differ, restart through `pdo daemon start` or reopen the GUI so the shared launcher can replace the older daemon.

### `pdo config set <key> <value>`

Write a value to the selected config file. This does not itself update a running daemon. Values are stored as strings; arbitrary keys are accepted and provider-specific validation happens when the settings are used.

### `pdo config get <key>`

Read a saved value from the selected config file. Environment overrides and built-in defaults are not shown; an absent saved key produces an error.

### `pdo config list`

List values saved in the selected config file, including API keys in plain text. This is not a dump of effective runtime defaults or environment overrides.

---

## Configuration Reference

PDO uses layered configuration (highest priority first):

1. Explicit overrides passed by the caller to `load_config`
2. Environment variables with the `PDO_` prefix
3. Config file (`~/.pdo/config.toml` by default)
4. Built-in defaults

Only wired command options override an operation. See the `--config` limitation above. `PDO_` names are lowercased after removing the prefix: `PDO_TARGET_SENTENCES` becomes `target_sentences`. Underscores are not converted into dots, so `PDO_GEMINI_API_KEY` does not set `gemini.api_key`.

Provider credentials have separate lookup rules: nonempty `openai.api_key`, `gemini.api_key`, and `zhipuai.api_key` settings take precedence over their respective `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `ZHIPUAI_API_KEY` variables. Those provider environment variables are fallbacks, not overrides of saved keys.

A daemon keeps the configuration loaded at startup. After `pdo config set`, restart it once the current job has finished, or use `pdo optimize --optimizer NAME` to save that backend and reload file settings before a new run. Desktop settings are saved and applied through the daemon while idle. Environment changes require restarting the daemon from the environment containing the new values.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (separate API billing) |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `ZHIPUAI_API_KEY` | — | ZhipuAI API key (GLM models) |
| `PDO_DATA_DIR` | `~/.pdo/data` | Database, PID, endpoint, and lock files |
| `PDO_LOG_DIR` | `~/.pdo/logs` | Log file directory |
| `PDO_OPTIMIZER` | `auto` | Override the configured backend when config is loaded |
| `PDO_TARGET_SENTENCES` | `3` | Approximate sentence target |
| `PDO_STYLE_INSTRUCTIONS` | *(none)* | Free-text style instructions |
| `PDO_OPTIMIZE_TEMPERATURE` | `0.4` | Generation temperature |
| `PDO_VALIDATE_TEMPERATURE` | `0.1` | Validation temperature |

Use absolute paths for `data_dir` and `log_dir`; TOML path strings are not expanded for `~`. Both settings can also be saved with `pdo config set`. Changing them does not move existing files. `socket_path` / `PDO_SOCKET_PATH` is retained only for discovering older Unix-socket daemons during migration; current clients use `<data_dir>/daemon.endpoint`.

### Optimizer Tuning

The shared tuning keys below apply to AI backends; demo mode ignores them. The `optimizer` key selects `auto` (default), `openai`, `gemini`, `zhipuai`, `local_llm`, or `dummy`:

```bash
pdo config set optimizer local_llm
pdo config set local_llm.address http://127.0.0.1:11434/v1
pdo config set local_llm.model YOUR_LOADED_MODEL_ID
```

Configure settings before daemon startup, or follow the refresh instructions above.

#### Output Quality

| Config key | Default | Description |
|------------|---------|-------------|
| `target_sentences` | `3` | Approximate sentence count requested in the prompt; not an enforced exact count |
| `style_instructions` | *(none)* | Free-text style guide appended to the system prompt |

```bash
pdo config set target_sentences 2
pdo config set style_instructions "Start with the product, then benefits, end with a call to action."
```

#### Temperature

| Config key | Default | Description |
|------------|---------|-------------|
| `optimize_temperature` | `0.4` | Sampling temperature for the generate step |
| `validate_temperature` | `0.1` | Sampling temperature for the QA/validate step |

#### Backend-Specific Settings

**OpenAI:**

| Config key | Default | Description |
|------------|---------|-------------|
| `openai.auth_mode` | `api_key` | `api_key` for the Responses API; `chatgpt` for a subscription through Codex |
| `openai.api_key` | — | API key (alternative to `OPENAI_API_KEY`) |
| `openai.model` | `gpt-5.6-luna` | Responses-compatible text model for API access |
| `openai.chatgpt_model` | — | Model selected from the authenticated Codex model list |
| `openai.codex_path` | `codex` | Installed Codex executable on PATH, or its absolute path |

API setup:

```bash
pdo config set optimizer openai
pdo config set openai.auth_mode api_key
pdo config set openai.api_key YOUR_API_KEY
pdo config set openai.model gpt-5.6-luna
```

Subscription setup (requires a separate [Codex CLI installation](https://learn.chatgpt.com/docs/codex/cli)):

```bash
pdo optimizer login openai
# Complete the browser login; the command prints the available model IDs.
pdo config set optimizer openai
pdo config set openai.auth_mode chatgpt
pdo config set openai.chatgpt_model MODEL_ID_FROM_LOGIN
```

`pdo optimizer login openai` honors the root `--config` option and supports `--json`. It logs in and lists models without switching the selected backend. Credentials stay in the adjacent `codex/` directory, normally `~/.pdo/codex/`, managed by Codex. PDO does not import another Codex profile. Login is bounded to three minutes; model requests to three minutes per step. No automatic API fallback occurs.

The GUI can discover models for either mode. The API model list excludes known image, audio, search, and coding-only families, but the listing endpoint does not certify Responses compatibility; manual IDs remain available. API requests use `store=false`. The shared temperature settings are sent only for GPT-4.1/GPT-4o API models; other API models and subscription access retain provider sampling defaults. Both modes send separate generation and validation requests.

**Gemini:**

| Config key | Default | Description |
|------------|---------|-------------|
| `gemini.api_key` | — | API key (alternative to `GEMINI_API_KEY` env var) |
| `gemini.model` | `gemini-3.6-flash` | Model identifier |

**ZhipuAI:**

| Config key | Default | Description |
|------------|---------|-------------|
| `zhipuai.api_key` | — | API key (alternative to `ZHIPUAI_API_KEY` env var) |
| `zhipuai.model` | `glm-4` | Model identifier |

**Local LLM:**

| Config key | Default | Description |
|------------|---------|-------------|
| `local_llm.address` | `http://127.0.0.1:11434/v1` | Base URL of the OpenAI-compatible server |
| `local_llm.model` | `local-model` | Model identifier passed in the request; replace the placeholder with a loaded model ID |

These are PDO's code defaults, not a guarantee that a provider currently serves a given model. The CLI does not discover local models. Desktop connection testing discovers them through the configured server.

### Desktop Preferences

| Config key | Meaning |
| --- | --- |
| `openai.manual_model`, `gemini.manual_model`, `zhipuai.manual_model`, `local_llm.manual_model` | Desktop advanced-model toggle, saved as `true` or `false`; the registry itself uses the corresponding `.model` value |
| `export.format` | JSON-encoded CSV format saved when remembering the desktop export format; ignored by CLI export |

Use the desktop controls to change these preferences. Export formats cover encoding, delimiter, BOM, line endings, quote character, minimal/all quoting, quote escaping, and headers.

### Example Config File

`~/.pdo/config.toml`:

```toml
[pdo]
optimizer            = "local_llm"
"local_llm.address"  = "http://127.0.0.1:11434/v1"
"local_llm.model"    = "llama3.2"
target_sentences     = "2"
optimize_temperature = "0.4"
validate_temperature = "0.1"
```

Manage via `pdo config set / get / list` — no manual editing required.

The desktop app writes the same provider keys under **Settings**. AI requests include mapped descriptions and context; validation also includes the mapped product ID and generated text. The server address determines where local-backend requests go: use a server on your own computer to keep those requests there.
