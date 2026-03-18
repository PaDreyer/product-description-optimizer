# Getting Started with PDO

This guide walks you through installing PDO, setting up your environment, and running your first optimization.

## Prerequisites

- **Python 3.12+**
- **An API key** (or a local LLM server):
  - Google Gemini — get a key at [aistudio.google.com](https://aistudio.google.com/apikey)
  - ZhipuAI (GLM-4) — get a key at [open.bigmodel.cn](https://open.bigmodel.cn)
  - Local LLM Server (Ollama, LM Studio, etc.) — no key needed

## 1. Installation

```bash
git clone <repo-url>
cd product_description_optimizer

python -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows

pip install -e '.[gemini,zhipuai,openai,dev]'
```

Verify:

```bash
pdo version
```

> **Tip:** You can also run PDO entirely through Docker — see the [README](../README.md#docker) for instructions.

## 2. Set Your API Key

Pick one backend and configure it:

**Google Gemini:**
```bash
export GEMINI_API_KEY="your-key-here"
# or persist it:
pdo config set gemini.api_key "your-key-here"
```

**ZhipuAI (GLM-4):**
```bash
export ZHIPUAI_API_KEY="your-key-here"
# or persist it:
pdo config set zhipuai.api_key "your-key-here"
```

**Local LLM (no key required):**
```bash
pdo config set local_llm.address http://127.0.0.1:11434/v1
pdo config set local_llm.model llama3.2
```

> **Tip:** Add environment variables to your shell profile (`~/.bashrc`, `~/.zshrc`) so they persist across sessions.

Without a key or local server configured, PDO falls back to a dummy optimizer that uppercases text — useful for testing the pipeline.

## 3. Prepare Your CSV

PDO works with any CSV file. You tell it which columns to use via **column mappings** (`-m ROLE:COLUMN`).

**Example CSV** (`products.csv`):
```csv
"ProduktID";"Titel";"Beschreibung";"Marke";"Kategorie";"Preis"
"P001";"Premium Kugelschreiber";"Hochwertiger Kugelschreiber mit ergonomischem Griff.";"SchreibGut";"Bürobedarf";"12.99"
"P002";"Notizblock A5";"Praktischer Notizblock im A5-Format.";"PapierPro";"Bürobedarf";"4.50"
```

Every CSV needs at least a `product_id` and a `description` mapping. Add as many `context` mappings as you like — more context means better AI output.

## 4. Start the Daemon

```bash
# Foreground (see logs in real-time — great for first run)
pdo daemon start --foreground

# Or background
pdo daemon start
```

Check it's running:
```bash
pdo daemon status
```

## 5. Import Products

Open a second terminal (if using foreground mode) and import:

```bash
pdo import products.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung \
  -m context:Titel \
  -m context:Marke \
  -m context:Kategorie
```

> **Tip:** Use `--limit 10` to import only a few products for a quick test run.

Check progress:
```bash
pdo status
```

## 6. Optimize

```bash
pdo optimize --watch
```

This shows a live progress display as the AI processes each product. For each product, the optimizer:

1. **Generates** an optimized description based on the original text + context
2. **Validates** the result — checking for false promises, hallucinated features, and inaccurate claims
3. If validation finds issues, uses the corrected version instead

To choose a specific backend:
```bash
pdo optimize --optimizer zhipuai --watch
pdo optimize --optimizer local_llm --watch
```

### Controlling the Optimization

```bash
pdo pause          # Pause mid-run (safe to leave indefinitely)
pdo resume         # Resume where you left off
pdo status         # Check progress at any time
```

## 7. Export Results

Once optimization is complete (or even partway through — it exports whatever is done):

```bash
pdo export optimized_output.csv
```

The output CSV contains all original columns plus `optimized_description` and `status`.

To include failed products:
```bash
pdo export output.csv --include-errors
```

## 8. Starting Over

```bash
pdo reset --yes    # Stops any running operation + clears the database
pdo import new_data.csv -m product_id:ProduktID -m description:Beschreibung
pdo optimize --watch
pdo export output.csv
```

> **Tip:** Use `pdo reset --keep --yes` to re-run optimization on the same products without reimporting.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Daemon is not running` | Run `pdo daemon start` first |
| `Worker is busy` | Wait for current operation, or `pdo reset --yes` |
| `GEMINI_API_KEY not set` | `export GEMINI_API_KEY="..."` or `pdo config set gemini.api_key <key>` |
| `ZHIPUAI_API_KEY not set` | `export ZHIPUAI_API_KEY="..."` or `pdo config set zhipuai.api_key <key>` |
| `google-genai not installed` | `pip install -e '.[gemini]'` |
| `zhipuai not installed` | `pip install -e '.[zhipuai]'` |
| Daemon unresponsive | `pdo daemon repair` to clean up, then `pdo daemon start` |
| Optimization is slow | Normal — ~2–5s per product (two API calls per product) |

## What's Next

- **Tune output quality** — see the [CLI Reference](cli_reference.md) for `target_sentences`, `style_instructions`, and temperature settings
- **Switch backends** — `pdo optimizer list` shows available backends and which is active
- **View logs** — `pdo logs -f` to tail the daemon log in real-time
