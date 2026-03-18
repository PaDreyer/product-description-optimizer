# PDO — Product Description Optimizer

<p align="center">
  <img src="docs/logo.png" alt="PDO Logo" width="150" />
</p>

A daemon/client CLI tool for batch-optimizing product descriptions using AI.

Import product data from CSV, optimize descriptions with Google Gemini, ZhipuAI, or a local LLM, validate them for accuracy, and export the results — all controlled through a familiar CLI interface.

## Features

- **Two-step AI optimization** — rewrite descriptions, then validate for false promises and hallucinated features
- **Multiple backends** — Google Gemini, ZhipuAI (GLM-4), any OpenAI-compatible local server (Ollama, LM Studio, …)
- **Daemon architecture** — background process handles long-running operations while the CLI stays responsive
- **Pause / resume / reset** — full control over the pipeline at any time
- **Crash-resilient** — per-product commits mean you never lose progress
- **Flexible CSV support** — configurable column mappings and automatic encoding detection (UTF-8, CP1252)

## Quick Start

```bash
# Clone and install
git clone <repo-url> && cd product_description_optimizer
python -m venv venv && source venv/bin/activate
pip install -e '.[gemini,zhipuai,openai,dev]'

# Set your API key (choose one)
export GEMINI_API_KEY="your-key-here"    # Google Gemini
# export ZHIPUAI_API_KEY="your-key-here" # ZhipuAI

# Start daemon and run the pipeline
pdo daemon start --foreground

# In another terminal:
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo optimize --watch
pdo export optimized_output.csv
```

→ See the [Getting Started guide](docs/getting_started.md) for a detailed walkthrough.

### Docker

```bash
docker build -t pdo-daemon .
docker run -d --name pdo-daemon -v $(pwd):/app/workspace pdo-daemon
docker exec -it pdo-daemon bash
# Inside: pdo import /app/workspace/products.csv ...
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

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting_started.md) | Step-by-step installation and first optimization |
| [CLI Reference](docs/cli_reference.md) | All commands, flags, and configuration options |

## Development

```bash
pip install -e '.[gemini,openai,dev]'

make test              # all tests with coverage
make test-unit         # unit tests only
make test-integration  # integration tests only
make lint              # ruff check + format check
make format            # auto-format
```

## License

MIT
