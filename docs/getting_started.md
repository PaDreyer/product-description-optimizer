# Getting Started with PDO

This guide walks you through installing the Product Description Optimizer, setting up your environment, and running your first optimization.

## Prerequisites

- **Python 3.12+**
- **API Key for one of**:
  - Google Gemini API — get one at [aistudio.google.com](https://aistudio.google.com/apikey)
  - ZhipuAI API (GLM-4) — get one at [open.bigmodel.cn](https://open.bigmodel.cn)
  - **OR** a local LLM Server (e.g., Ollama, LM Studio)

## 1. Installation

```bash
# Clone the repository
git clone <repo-url>
cd product_description_optimizer

# Create a virtual environment
python -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows

# Install with all optimizer support
pip install -e '.[gemini,zhipuai,openai,dev]'
```

Verify the installation:
```bash
pdo version
# → pdo 0.1.0
```

## 2. Docker Installation

If you prefer not to install Python dependencies locally, you can run the entire PDO stack through Docker:

```bash
# Build the image
docker build -t pdo-daemon .

# Run the container in the background
# The -v flag mounts your current directory to /app/workspace in the container
docker run -d --name pdo-daemon -v $(pwd):/app/workspace pdo-daemon

# Jump into the container using a bash shell
docker exec -it pdo-daemon bash
```

Once inside the container shell, you can simply run `pdo` commands as usual. Any files in your local directory will be available at `/app/workspace/`.

When you are finished, you can stop and remove the container:
```bash
docker rm -f pdo-daemon
```

## 3. Set Your API Key

**Option A: ZhipuAI (GLM-4)**
```bash
export ZHIPUAI_API_KEY="your-key-here"
# OR
pdo config set zhipuai.api_key "your-key-here"
```

**Option B: Google Gemini**
```bash
export GEMINI_API_KEY="your-key-here"
# OR
pdo config set gemini.api_key "your-key-here"
```

**Option C: Local LLM**
```bash
pdo config set local_llm.address http://127.0.0.1:11434/v1
```

> **Tip:** Add this to your shell profile (`~/.bashrc`, `~/.zshrc`) so you don't have to set it every session.

Without the key, PDO falls back to a dummy optimizer that uppercases text — useful for testing the pipeline, but not for real optimizations.

## 4. Prepare Your CSV

PDO works with any CSV file. You tell it which columns to use via **column mappings**.

**Example CSV** (`products.csv`):
```csv
"ProduktID";"Titel";"Beschreibung";"Marke";"Kategorie";"Preis"
"P001";"Premium Kugelschreiber";"Hochwertiger Kugelschreiber mit ergonomischem Griff.";"SchreibGut";"Bürobedarf";"12.99"
"P002";"Notizblock A5";"Praktischer Notizblock im A5-Format.";"PapierPro";"Bürobedarf";"4.50"
```

**Mapping rules:**
- Every CSV needs at least a `product_id` and a `description` mapping
- Add as many `context` mappings as you like — more context = better AI output
- Default delimiter is `;` (change with `-d ","`)

## 5. Start the Daemon

The daemon runs in the background and does all the heavy work:

```bash
# Option A: Foreground (see logs in real-time, great for first run)
pdo daemon start --foreground

# Option B: Background (daemonize)
pdo daemon start
```

Check it's running:
```bash
pdo daemon status
```

## 6. Import Products

Open a second terminal (if using foreground mode) and import:

```bash
pdo import products.csv \
  -m product_id:ProduktID \
  -m description:Beschreibung \
  -m context:Titel \
  -m context:Marke \
  -m context:Kategorie
```

You should see:
```
✓ Import started
```

> **Tip:** You can limit the number of products imported using the `--limit` or `-l` flag (e.g., `--limit 10` is great for testing the pipeline).

Check progress:
```bash
pdo status
```

## 7. Optimize

Start the AI optimization:

```bash
# Use ZhipuAI (glm-4) by default if key is set
pdo optimize --watch

# Or explicitly choose a backend:
pdo optimize --optimizer zhipuai --watch
pdo optimize --optimizer gemini --watch
pdo optimize --optimizer local_llm --watch
```

This shows a progress bar as the AI processes each product. For each product, the optimizer:

1. **Generates** an optimized description based on the original text + context
2. **Validates** the result — checking for false promises, hallucinated features, and inaccurate claims
3. If validation fails, uses the corrected version instead

> **Note:** With `gemini-2.0-flash`, each product takes ~2–5 seconds (two API calls). A 1,000-product catalogue takes roughly 30–80 minutes.

### Controlling the Optimization

```bash
pdo pause          # Pause mid-run (safe to leave overnight)
pdo resume         # Resume where you left off
pdo status         # Check progress at any time
```

## 8. Export Results

Once optimization is complete (or even partway through — it exports whatever is done):

```bash
pdo export optimized_output.csv
```

The output CSV contains all original columns plus:
- `optimized_description` — the AI-generated text
- `status` — `done` or `error`

To include failed products:
```bash
pdo export output.csv --include-errors
```

## 9. Starting Over

When your product data changes:

```bash
pdo reset --yes    # Stops any running operation + clears the database
pdo import new_data.csv -m product_id:ProduktID -m description:Beschreibung
pdo optimize --watch
pdo export output.csv
```

## 10. Viewing Logs

```bash
pdo logs              # Last 50 lines
pdo logs -n 200       # Last 200 lines
pdo logs -f           # Follow (live tail)
```

## 11. Stopping the Daemon

```bash
pdo daemon stop
```

## 12. Troubleshooting

| Problem | Solution |
|---------|----------|
| `Daemon is not running` | Run `pdo daemon start` first |
| `Worker is busy` | Wait for current operation, or run `pdo reset --yes` |
| `ZHIPUAI_API_KEY not set` | Export the key: `export ZHIPUAI_API_KEY="..."` or use `pdo config set zhipuai.api_key <key>` |
| `GEMINI_API_KEY not set` | Export the key: `export GEMINI_API_KEY="..."` or use `pdo config set gemini.api_key <key>` |
| `zhipuai not installed` | Run `pip install -e '.[zhipuai,dev]'` |
| `google-genai not installed` | Run `pip install -e '.[gemini,openai]'` |
| Optimization is slow | Normal — ~2–5s per product with two validation API calls |

## 13. What's Next

Complete command reference: [CLI Reference](docs/cli_reference.md)

- **Tune output quality** — control length and style without touching code:
  ```bash
  pdo config set target_sentences 2
  pdo config set style_instructions "Describe the product, highlight key features, end with a gentle call to action."
  ```

- **Adjust temperature** — lower values produce more rule-consistent output:
  ```bash
  pdo config set optimize_temperature 0.3   # generate step (default 0.4)
  pdo config set validate_temperature 0.1   # QA step (default 0.1)
  ```

- **Switch optimizer** — use a different backend:
  ```bash
  # Use ZhipuAI with custom model
  pdo config set zhipuai.model glm-4-plus
  pdo optimize --optimizer zhipuai --watch

  # Use local model
  pdo config set local_llm.address http://127.0.0.1:11434/v1
  pdo config set local_llm.model llama3.2
  pdo optimize --optimizer local_llm --watch
  ```

- **Persistent config** — all settings survive restarts via `~/.pdo/config.toml`:
  ```toml
  [pdo]
  optimizer            = "local_llm"
  local_llm.address    = "http://127.0.0.1:11434/v1"
  local_llm.model      = "llama3.2"
  target_sentences     = "2"
  optimize_temperature = "0.4"
  validate_temperature = "0.1"
  style_instructions   = "Starte mit dem Produkt selbst, erwähne dann die Vorteile und ende mit einem sanften Kaufimpuls."
  ```
  Manage it through `pdo config set / get / list` — no manual editing required.
