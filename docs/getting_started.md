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

1. **Daten laden:** Select a CSV file. PDO detects common delimiters, UTF-8, UTF-16 LE/BE, and CP1252. Review the suggested column roles next to source examples. Assign a description column and, if present, a unique product ID and relevant context columns. A new import replaces the previous batch after confirmation and a successful import; failures leave the current batch intact. Skipped rows are reported.
2. **Optimieren:** Configure a cloud or local AI connection once under **Einstellungen**. Cloud providers use their default model, with an optional advanced override. For a local server, enter its API address and choose **Verbindung prüfen**. PDO automatically selects a sole discovered model or presents a choice of available models. You can optionally specify writing style and text length. Pause and resume from the progress view; completed results are saved immediately. Demo mode only uppercases text.
3. **Prüfen & exportieren:** Compare original and optimized text side by side. Search and status filters cover the complete batch; the table displays pages of 100 products. Open **Fehler** to handle errors by cause, then continue to export.

An error-group selection includes every matching product, regardless of pagination. Retrying processes only those failed products and retains successful results. Rate-limit retries wait one second before each product; provider-specific retry delays also apply. Correct rejected credentials or an unavailable server before retrying those groups.

For missing descriptions and context, export **Quelldaten zur Korrektur**, fill in the missing source values, and import the corrected CSV. Keep the original column names and product IDs. Correction import requires exactly one mapped ID column, rejects missing, unknown, duplicate, or already successful IDs, and applies the whole file atomically. Select the resulting **Quelldaten korrigiert** group to process the corrected products. **Alle Fehler exportieren** produces a separate report with original columns, `error_message`, and `status`.

The default result export includes successful rows, all original columns, `optimized_description`, and `status`. If those names already exist in the source, PDO prefixes the new columns with `pdo_` (and a numeric suffix if needed), preserving the original values. **Alle Produkte** also includes pending and failed rows with an empty optimized text. CSV formatting initially follows the source or a previously remembered export format. Under **Format anpassen**, choose UTF-8, UTF-16 LE/BE, Windows-1252, or ISO-8859-1 and a semicolon, comma, tab, space, pipe, or custom one-character separator. Further options control BOM, line endings, quotation marks, escaping, and headers. The preview uses two actual products and the same serializer as the saved file. Invalid combinations and unrepresentable characters fail explicitly; a failed export preserves an existing destination file. PDO also prevents overwriting the original source CSV.

Provider settings, including API keys entered in the desktop app, are saved in `~/.pdo/config.toml`. On Linux the file is written with owner-only permissions. You can also set `GEMINI_API_KEY` or `ZHIPUAI_API_KEY` in the environment. The SQLite database lives in `~/.pdo/data/pdo.db` by default.

Cloud AI providers receive the description and context fields selected during column mapping. Choose an OpenAI-compatible local server when that data must remain on your computer.

The desktop application starts the PDO daemon automatically and uses it as a client. On Linux, the tray icon uses the StatusNotifierItem D-Bus protocol and needs a StatusNotifier host such as KDE Plasma or GNOME with the AppIndicator extension. On Windows it uses the native Qt tray. Closing the window hides the GUI in the tray while the daemon continues the current job. Click the tray icon or choose **Open** from its menu to reopen the window. **Quit** stops the daemon and closes the GUI; other open GUI windows do not restart a deliberately stopped daemon. Without a tray host, closing the window exits the GUI client while the daemon continues; use `pdo daemon stop` to stop it. If the host disappears after the GUI was hidden, PDO restores the window. Opening the GUI again starts or reconnects to the daemon and its saved progress. The CLI can use that daemon at the same time.

If the GUI reports a startup error, check `~/.pdo/logs/daemon-startup.log` and `~/.pdo/logs/daemon.log`. With the Python CLI installed, `pdo daemon status` shows whether a daemon process exists and responds; `pdo daemon repair` stops an unresponsive process before cleaning its stale connection files. Starting the GUI again reconnects to the saved database.

## CLI on Linux and Windows

The CLI uses the same local daemon as the desktop application. Install the Python package to use the CLI; the Windows installer contains the GUI only. Start the daemon manually when the desktop application has not already started it, then work in a second terminal:

```bash
pdo daemon start
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo optimize --optimizer gemini --watch
pdo export optimized-products.csv
```

Run `pdo optimizer list` to see available backends. Use `pdo pause`, `pdo resume`, and `pdo status` while a job is running. The [CLI Reference](cli_reference.md) lists all commands and configuration keys.
