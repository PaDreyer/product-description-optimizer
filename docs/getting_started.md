# Getting started

## Desktop application

Install a package from [GitHub Releases](https://github.com/PaDreyer/product-description-optimizer/releases) or run the source checkout with Python 3.12 or newer:

The Linux AppImage and Debian package currently require glibc 2.36 or newer, as provided by Debian 12 and Ubuntu 24.04.

```bash
./scripts/setup-dev.sh
source venv/bin/activate
pdo-desktop
```

On Windows, run `.\scripts\setup-dev.ps1`, then activate
`venv\Scripts\Activate.ps1` in PowerShell.

1. **Import:** Select a CSV file. PDO detects the delimiter and tries UTF-8 and CP1252. Map a description column and, if present, a product ID and relevant context columns. A new import replaces the previous batch after confirmation and only after the complete file has been validated; a failed import leaves the current batch intact.
2. **Optimize:** Select a cloud or local AI backend. Built-in adapters currently cover Google Gemini, ZhipuAI, and OpenAI-compatible local servers. Enter the API key for a cloud provider, or the local server address and model name. The demo backend only uppercases text and is intended for checking the workflow.
3. **Review:** Watch the counts, open a row to compare full descriptions, and pause or resume between products. Each completed result is saved to SQLite immediately.
4. **Export:** Choose an output CSV path. The file includes all original columns plus `optimized_description` and `status`. Optionally include rows that failed optimization.

Provider settings, including API keys entered in the desktop app, are saved in `~/.pdo/config.toml`. On Linux the file is written with owner-only permissions. You can also set `GEMINI_API_KEY` or `ZHIPUAI_API_KEY` in the environment. The SQLite database lives in `~/.pdo/data/pdo.db` by default.

Cloud AI providers receive the description and context fields selected during column mapping. Choose an OpenAI-compatible local server when that data must remain on your computer. The desktop app and CLI daemon share the same database and enforce exclusive access; stop the daemon with `pdo daemon stop` before starting `pdo-desktop`.

## CLI on Linux

The CLI uses a Unix-socket daemon. Start it, then work in a second terminal:

```bash
pdo daemon start
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo optimize --optimizer gemini --watch
pdo export optimized-products.csv
```

Run `pdo optimizer list` to see available backends. Use `pdo pause`, `pdo resume`, and `pdo status` while a job is running. The [CLI Reference](cli_reference.md) lists all commands and configuration keys.
