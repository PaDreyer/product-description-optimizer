# PDO — Product Description Optimizer

<p align="center">
  <img src="docs/logo.png" alt="PDO Logo" width="150" />
</p>

A daemon/client CLI tool for batch-optimizing product descriptions using AI.

Import product data from CSV, optimize descriptions with Google Gemini, validate for accuracy, and export the results — all controlled through a familiar CLI interface (think `systemctl` or `docker`).

## Features

- **Two-step AI optimization** — Gemini, ZhipuAI, or Local LLMs rewrite descriptions, then validate them for false promises and hallucinated features
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
pip install -e '.[gemini,zhipuai,openai,dev]'

# Set your API key (choose one)
export ZHIPUAI_API_KEY="your-key-here"  # For ZhipuAI
# OR
export GEMINI_API_KEY="your-key-here"  # For Gemini

# Start daemon
pdo daemon start --foreground

# In another terminal:
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo optimize --watch
pdo export optimized_output.csv
```

→ See [Getting Started](docs/getting_started.md) for a detailed walkthrough.

### Using Docker

Alternatively, you can run the PDO daemon and CLI entirely within Docker, without installing Python dependencies locally.

```bash
# Build the image
docker build -t pdo-daemon .

# Start the daemon container (mounts current directory to /app/workspace)
docker run -d --name pdo-daemon -v $(pwd):/app/workspace pdo-daemon

# Jump into the container shell to run CLI commands
docker exec -it pdo-daemon bash

# Inside the container:
# root@container:/app# pdo import /app/workspace/products.csv ...

# Stop and remove the container when finished
docker rm -f pdo-daemon
```

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
| `pdo import <file> [-l N]` | Import products (optionally limit N)         |
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
                        (CSV→DB) (Gemini/ZhipuAI/Local LLM) (DB→CSV)
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

| Variable               | Default                       | Description                      |
|------------------------|-------------------------------|----------------------------------|
| `ZHIPUAI_API_KEY`     | —                             | ZhipuAI API key (GLM models)    |
| `GEMINI_API_KEY`       | —                             | Google Gemini API key            |
| `PDO_LOCAL_LLM_ADDRESS` | `http://127.0.0.1:11434/v1`  | Local OpenAI-compatible endpoint |
| `PDO_LOCAL_LLM_MODEL`  | `local-model`                 | Model name to pass to the server |
| `PDO_DATA_DIR`         | `~/.pdo/data`                 | Database & PID storage           |
| `PDO_LOG_DIR`          | `~/.pdo/logs`                 | Log file directory               |
| `PDO_SOCKET_PATH`      | `~/.pdo/pdo.sock`             | Daemon socket path               |

## Optimizer Tuning

All optimizer behaviour is controlled with `pdo config set`. Settings are shared across backends (only one optimizer runs at a time).

### Output quality

| Config key           | Default | Description |
|----------------------|---------|-------------|
| `target_sentences`   | `3`     | Exact number of sentences the AI must produce. Increase for richer copy, decrease for compact listings. |
| `style_instructions` | *(none)* | Free-text style guide appended to the system prompt — e.g. tone, structure, call-to-action rules. |

```bash
pdo config set target_sentences 2
pdo config set style_instructions "Starte mit dem Produkt selbst, erwähne dann die Vorteile und ende mit einem sanften Kaufimpuls."
```

### Temperature (creativity vs. discipline)

| Config key              | Default | Description |
|-------------------------|---------|-------------|
| `optimize_temperature`  | `0.4`   | Sampling temperature for the **generate** step. Lower = more rule-following; higher = more creative. |
| `validate_temperature`  | `0.1`   | Sampling temperature for the **QA/validate** step. Keep this low for deterministic fact-checking. |

```bash
pdo config set optimize_temperature 0.3   # stricter rule-following
pdo config set validate_temperature 0.1   # keep deterministic
```

### Local LLM connection

| Config key           | Default                      | Description |
|----------------------|------------------------------|-------------|
| `local_llm.address`  | `http://127.0.0.1:11434/v1` | Base URL of the OpenAI-compatible server |
| `local_llm.model`    | `local-model`                | Model identifier passed in the request |

```bash
pdo config set local_llm.address http://127.0.0.1:11434/v1
pdo config set local_llm.model llama3.2
```

### ZhipuAI connection

| Config key           | Default | Description |
|----------------------|---------|-------------|
| `zhipuai.api_key`    | (none)  | ZhipuAI API key |
| `zhipuai.model`      | `glm-4` | ZhipuAI model identifier |

```bash
export ZHIPUAI_API_KEY="your-key"
pdo config set zhipuai.model glm-4-plus
pdo optimize --optimizer zhipuai --watch
```

View or verify all active settings at any time:
```bash
pdo config list
```

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
