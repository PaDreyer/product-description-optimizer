# CLI Reference

Complete reference for all `pdo` commands. Every command supports `--help` for inline usage.

The CLI and desktop application use the same daemon on Linux and Windows. Clients reach it through an authenticated, loopback-only TCP endpoint published in the user's PDO data directory. The desktop application starts the daemon automatically. On Windows, install the Python package separately for the CLI; the installer contains the GUI only.

## Global Options

Place these flags before the command name. `--json` and `--verbose` can also be placed after a command that exposes them.

| Flag | Description |
|------|-------------|
| `--json` | Output machine-readable JSON instead of rich text |
| `--verbose` | Enable verbose/debug output |
| `--config <path>` | Use a custom config file (top-level only) |

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

If the endpoint is missing, `stop` uses the validated daemon PID to request shutdown. It reports success after the process exits. `--force` also uses SIGKILL when the daemon does not exit after SIGTERM.

### `pdo daemon status`

Check whether the daemon is running and responding.

### `pdo daemon repair`

Stop an unresponsive daemon with SIGTERM (and SIGKILL if it does not exit), wait for exit, then remove stale PID and endpoint files while holding the data-directory lock. If the process cannot be stopped, its runtime files are preserved.

---

### `pdo import <file>`

Import a CSV file into the database.

| Flag | Description |
|------|-------------|
| `-m`, `--mapping ROLE:COLUMN` | Map a CSV column to a role (repeatable) |
| `-d`, `--delimiter CHAR` | CSV delimiter (default: `;`) |
| `-l`, `--limit N` | Import only the first N products |

**Roles:**

| Role | Required | Description |
|------|----------|-------------|
| `product_id` | No | Product identifier when present |
| `description` | Yes | The description text to optimize |
| `context` | No | Extra info for the AI (brand, title, specs, etc.) — repeatable |

**Example:**

```bash
pdo import catalogue.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung \
  -m context:Titel \
  -m context:Marke \
  -m "context:Merkmal 1"
```

---

### `pdo optimize`

Start the AI optimization pipeline.

| Flag | Description |
|------|-------------|
| `-w`, `--watch` | Poll for progress until done |
| `-o`, `--optimizer NAME` | Choose backend: `gemini`, `zhipuai`, `local_llm`, `dummy` |

```bash
pdo optimize --watch
pdo optimize --optimizer zhipuai --watch
```

### `pdo optimizer list`

List available optimizer backends and show which one is active.

---

### `pdo export <file>`

Export optimized products to a CSV file.

| Flag | Description |
|------|-------------|
| `--include-errors` | Include products that failed optimization |

The output CSV contains all original columns plus `optimized_description` and `status`.

---

### `pdo status`

Show current pipeline stage and progress (total, done, pending, errors).

### `pdo pause`

Pause the current optimization. Safe to leave paused indefinitely.

### `pdo resume`

Resume a paused optimization from where it left off.

### `pdo reset`

Stop all operations and clear the database.

| Flag | Description |
|------|-------------|
| `-y`, `--yes` | Skip the confirmation prompt |
| `--keep` | Keep products but flag them all as pending again |

---

### `pdo logs`

Display the daemon log file (works even when the daemon is stopped).

| Flag | Description |
|------|-------------|
| `-f`, `--follow` | Tail the log and stream new lines |
| `-n`, `--lines N` | Number of lines to show (default: 50) |

### `pdo version`

Print client and daemon version.

### `pdo config set <key> <value>`

Set a configuration key.

### `pdo config get <key>`

Read a single configuration key.

### `pdo config list`

List all configuration keys and values.

---

## Configuration Reference

PDO uses layered configuration (highest priority first):

1. CLI flags / arguments (including `--config <path>`)
2. Environment variables (`PDO_` prefix)
3. Config file (`~/.pdo/config.toml`, managed via `pdo config`)
4. Built-in defaults

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `ZHIPUAI_API_KEY` | — | ZhipuAI API key (GLM models) |
| `PDO_DATA_DIR` | `~/.pdo/data` | Database & PID storage |
| `PDO_LOG_DIR` | `~/.pdo/logs` | Log file directory |

### Optimizer Tuning

All optimizer behaviour is controlled with `pdo config set`. Settings are shared across backends.

#### Output Quality

| Config key | Default | Description |
|------------|---------|-------------|
| `target_sentences` | `3` | Exact number of sentences the AI must produce |
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
| `local_llm.model` | `local-model` | Model identifier passed in the request |

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

The desktop app writes the same keys when settings are saved in its optimizer screen. Cloud providers receive the mapped product description and context fields. An OpenAI-compatible local server keeps those requests on the configured local endpoint.
