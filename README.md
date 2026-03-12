# PDO — Product Description Optimizer

A daemon/client CLI tool for batch-optimizing product descriptions using AI.

Import product data from CSV, optimize descriptions with Google Gemini, validate for accuracy, and export the results — all controlled through a familiar CLI interface (think `systemctl` or `docker`).

## Features

- **Two-step AI optimization** — Gemini or Local LLMs rewrite descriptions, then validate them for false promises and hallucinated features
- **Daemon architecture** — background process handles long-running operations while the CLI stays responsive
- **Pause / resume / reset** — full control over the pipeline at any time
- **Crash-resilient** — per-product commits mean you never lose progress
- **Configurable column mapping** — works with any CSV structure via `ROLE:COLUMN` mappings
- **Encoding detection** — handles UTF-8, CP1252, and other encodings automatically

## Quick Start

```bash
# Clone and install
git clone <repo-url> && cd product_description_optimizer
python -m venv venv && source venv/bin/activate
pip install -e '.[gemini,openai,dev]'

# Set your Gemini API key
export GEMINI_API_KEY="your-key-here"

# Start the daemon
pdo daemon start --foreground

# In another terminal:
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo optimize --optimizer gemini --watch
pdo export optimized_output.csv
```

→ See [Getting Started](docs/getting_started.md) for a detailed walkthrough.

## CLI Reference

| Command                  | Description                                  |
|--------------------------|----------------------------------------------|
| `pdo config set <k> <v>` | Set a configuration key to a given value     |
| `pdo config get <key>`   | Get the value of a configuration key         |
| `pdo config list`        | List all configuration keys and values       |
| `pdo daemon start`       | Start the background daemon                  |
| `pdo daemon stop`        | Stop the daemon                              |
| `pdo daemon status`      | Check if the daemon is running               |
| `pdo daemon repair`      | Repair unresponsive daemon (clean PID/socket)|
| `pdo import <file>`      | Import products from a CSV file              |
| `pdo optimize [--watch]` | Start optimization (optionally watch progress) |
| `pdo optimizer list`     | List available optimizer backends            |
| `pdo export <file>`      | Export results to CSV                        |
| `pdo status`             | Show pipeline progress                       |
| `pdo pause`              | Pause the current optimization               |
| `pdo resume`             | Resume a paused optimization                 |
| `pdo reset [--yes]`      | Stop all operations and clear the database   |
| `pdo logs [-f] [-n N]`   | View daemon log output                       |
| `pdo version`            | Print version                                |

All commands support `--help` for detailed usage.

## Column Mappings

Map your CSV columns to roles using `-m ROLE:COLUMN`:

| Role          | Required | Description                             |
|---------------|----------|-----------------------------------------|
| `product_id`  | Yes      | Unique product identifier               |
| `description` | Yes      | The description text to optimize        |
| `context`     | No       | Extra info for the AI (brand, title, specs, etc.) |

**Example** (semicolon-delimited German catalogue):
```bash
pdo import catalogue.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung \
  -m context:Titel \
  -m context:Marke \
  -m "context:Merkmal 1" \
  -m "context:Attribut 1"
```

## Architecture

```
┌──────────┐    Unix Socket    ┌──────────────┐
│  CLI     │◄─────────────────►│  Daemon      │
│  (click) │   JSON messages   │  Server      │
└──────────┘                   └──────┬───────┘
                                      │
                                ┌─────▼─────┐
                                │  Worker    │
                                │  (thread)  │
                                └──┬──┬──┬──┘
                                   │  │  │
                          ┌────────┘  │  └────────┐
                          ▼           ▼            ▼
                     Importer    Optimizer     Exporter
                       (CSV→DB) (Gemini/Local LLM) (DB→CSV)
                          │           │            │
                          └─────┬─────┘────────────┘
                                ▼
                            SQLite DB
```

## Configuration

PDO uses layered configuration (highest priority first):

1. CLI flags / arguments (including global `--config <path>`)
2. Environment variables (`PDO_` prefix)
3. Config file (`~/.pdo/config.toml`, manage via `pdo config`)
4. Built-in defaults

**Key environment variables:**

| Variable         | Default              | Description            |
|------------------|----------------------|------------------------|
| `GEMINI_API_KEY`        | —                           | Google Gemini API key            |
| `PDO_LOCAL_LLM_ADDRESS` | `http://127.0.0.1:11434/v1` | Local OpenAI-compatible endpoint |
| `PDO_LOCAL_LLM_MODEL`   | `local-model`               | Model name to pass to the server |
| `PDO_DATA_DIR`          | `~/.pdo/data`               | Database & PID storage           |
| `PDO_LOG_DIR`           | `~/.pdo/logs`               | Log file directory               |
| `PDO_SOCKET_PATH`       | `~/.pdo/pdo.sock`           | Daemon socket path               |

## Development

```bash
# Install dev dependencies
pip install -e '.[gemini,openai,dev]'

# Run tests
make test              # all tests with coverage
make test-unit         # unit tests only
make test-integration  # integration tests only

# Lint & format
make lint
make format
```

## License

MIT
