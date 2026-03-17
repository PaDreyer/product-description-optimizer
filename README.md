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

→ See [Getting Started](docs/getting_started.md) for a detailed walkthrough. Docker is also available - see [Getting Started](docs/getting_started.md).

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

For complete CLI reference, see [CLI Reference](docs/cli_reference.md).

## Configuration

PDO uses layered configuration (highest priority first):

1. CLI flags / arguments (including global `--config <path>`)
2. Environment variables (`PDO_` prefix)
3. Config file (`~/.pdo/config.toml`, manage via `pdo config`)
4. Built-in defaults

→ For deep setup and persistent configuration, see [Getting Started](docs/getting_started.md).

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

### Gemini connection

| Config key        | Default | Description |
|-------------------|---------|-------------|
| `gemini.api_key`  | (none)  | Google Gemini API key |
| `gemini.model`    | `gemini-2.0-flash` | Gemini model identifier |

View or verify all active settings at any time:
```bash
pdo config list
```

For detailed configuration examples, see [Getting Started](docs/getting_started.md).

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

## Contributing

Contributions are welcome! We're happy to review pull requests and help new contributors get started.

**Development setup:**
```bash
git clone <repo-url>
cd product_description_optimizer
python -m venv venv && source venv/bin/activate
pip install -e '.[gemini,zhipuai,openai,dev]'
make test
```

**Pull requests:**
- Fork the repository
- Create a feature branch
- Ensure tests pass: `make test`
- Ensure code quality: `make lint`
- Submit a PR with a clear description

See [AGENTS.md](AGENTS.md) for development conventions and guidelines.

## License

MIT
