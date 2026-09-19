# Getting started

## Install the desktop application

Use a package from [GitHub Releases](https://github.com/PaDreyer/product-description-optimizer/releases) when a release is available, or run the source checkout. Release packages bundle Python, the GUI, and provider libraries. They do not install the `pdo` CLI.

Linux packages target x86-64 and require glibc 2.36 or newer, as provided by Debian 12 and Ubuntu 24.04. For an AppImage, make the downloaded file executable and run it; for a Debian package, install it with `apt` and open PDO from the application menu. For example, with the corresponding `0.2.0` asset downloaded:

```bash
chmod +x PDO-0.2.0-x86_64.AppImage
./PDO-0.2.0-x86_64.AppImage
```

Alternatively:

```bash
sudo apt install ./PDO-0.2.0-amd64.deb
pdo-desktop
```

On Windows x64, run the downloaded `PDO-Setup-<version>-x64.exe` installer and open **Product Description Optimizer** from the Start menu.

For a source installation, clone the repository and enter its directory first. Linux requires `python3` to be Python 3.12 or newer:

```bash
git clone https://github.com/PaDreyer/product-description-optimizer.git
cd product-description-optimizer
./scripts/setup-dev.sh
source venv/bin/activate
pdo-desktop
```

On Windows, from the checkout in PowerShell:

```powershell
.\scripts\setup-dev.ps1
.\venv\Scripts\Activate.ps1
pdo-desktop
```

The Windows script uses `py -3.12` by default; pass `-Python <path-to-python.exe>` to select another Python 3.12+ interpreter. Setup scripts install Python dependencies. Linux Qt system dependencies and test setup are described in the [Development guide](development.md).

## Load, optimize, and review

1. **Daten laden:** Select a CSV file with unique, nonempty column headers. PDO detects common delimiters, UTF-8, UTF-16 LE/BE, and CP1252. Review the column roles beside the source examples. Map at least one description column, an optional product ID, and relevant context columns. Unmapped columns are preserved in exports but are not sent to the AI. A desktop import replaces the previous batch after confirmation and a successful import; a failed or zero-product replacement keeps the previous batch. Review any skipped-row report.
2. **Optimieren:** Configure the AI connection under **Einstellungen**. Cloud providers require an API key and use PDO's configured default model unless overridden under **Erweitert**. For a local server, start the model server, enter its OpenAI-compatible API address, and choose **Verbindung prüfen**. A sole discovered model is selected automatically; choose a model if several are available. You can set writing style and an approximate sentence count. **Demo** checks the workflow without an AI call and produces uppercase text with a marker.
3. **Prüfen & exportieren:** Compare original and optimized text side by side. Search and status filters cover the complete batch; the table displays pages of 100 products. Open **Fehler** to handle errors by cause before exporting.

An empty description can be generated from mapped context. **Quelldaten fehlen** means that both description and usable context are absent. Pause takes effect between products; an in-flight AI request can still finish. Completed products are saved immediately.

## Recover failed products

In **Fehler**, selecting a group includes every matching failed product, regardless of the table page. Retrying those groups preserves successful results and leaves unrelated pending products alone. If the selection includes **API-Limit erreicht**, PDO waits one second before each selected product, in addition to provider retry delays. Correct rejected credentials or an unavailable server before retrying those groups.

For **Quelldaten fehlen**:

1. Export **Quelldaten zur Korrektur**. This contains only products in that error group and only the original columns.
2. Fill in source descriptions or context. Keep the original column names **and order**, product IDs, and header row.
3. Import the corrected CSV through the correction action in **Fehler**.
4. Select **Quelldaten korrigiert** and retry. Correction import updates the source data but does not start optimization automatically.

Correction import requires exactly one mapped ID column. Every ID in the correction file must match exactly one failed product in the batch. Missing, duplicate, unknown, ambiguous, or non-error IDs reject the whole file; no partial corrections are applied. IDs need to be unique even if the initial import accepted duplicates. With no suitable ID mapping, prepare a corrected source file for a new batch instead.

**Alle Fehler exportieren** creates a separate error report with original columns, `error_message`, and `status`. It is not directly re-importable as a correction CSV because it has extra columns.

## Export CSV files

| Desktop export choice | Included rows | Added columns |
| --- | --- | --- |
| **Nur erfolgreiche Produkte** | Successful products | `optimized_description`, `status` |
| **Alle Produkte** | All products, including pending and failed rows | `optimized_description`, `status` |
| **Fehlerliste mit Quelldaten** | All failed products | `error_message`, `status` |
| **Quelldaten zur Korrektur** | Products in **Quelldaten fehlen** | None |

All exports preserve the original columns. Only successful rows receive optimized text. If an added column name already exists, PDO uses `pdo_` and, if needed, a numeric suffix, such as `pdo_status_2`.

The desktop export starts with the detected source format or a previously remembered export format. Under **Format anpassen**, choose UTF-8, UTF-16 LE/BE, Windows-1252, or ISO-8859-1 and a semicolon, comma, tab, space, pipe, or custom one-character separator. Further options control BOM, line endings, quotation marks, escaping, and headers. Keep headers enabled for correction files.

The preview uses up to two actual products and the same serializer as the saved file. Later rows can still contain characters outside the chosen encoding. Invalid combinations and unrepresentable characters fail explicitly; a failed export preserves an existing destination file. PDO prevents writing to the active source CSV path. A successful export can replace another existing destination file.

## Settings, data, and background work

Provider settings and API keys entered in the desktop app are saved as plain text in `~/.pdo/config.toml`; on Linux the file is written with owner-only permissions. `GEMINI_API_KEY` and `ZHIPUAI_API_KEY` are fallbacks when the corresponding saved key is empty. Set them in the environment before starting PDO. The default SQLite database is `~/.pdo/data/pdo.db`. On Windows, `~` refers to your user home, normally `%USERPROFILE%`.

The AI adapters send the mapped description and context to the configured provider. Their validation step also includes the mapped product ID and generated description. To keep these requests on your computer, run a model server on that computer and configure its local address; a remote address still sends the data to that remote server.

The GUI starts the daemon automatically. CLI and GUI clients sharing a data directory work on the same batch, with one import, optimization, or export running at a time.

On Linux, the tray uses StatusNotifierItem over D-Bus and needs a host such as KDE Plasma or GNOME with the AppIndicator extension. Windows uses the native Qt tray. Closing the window hides the GUI while the daemon continues. Click the tray icon or **Open** to restore it. **Quit** stops the shared daemon and closes the GUI. Without a tray host, closing the window exits the GUI client while the daemon continues; the Python CLI can stop it with `pdo daemon stop`. If the host disappears after the GUI was hidden, PDO restores the window.

After a daemon stop, crash, or update, reopening PDO reconnects to saved products and returns interrupted `processing` rows to `pending`. **Start optimization again** to process remaining rows; restarting the daemon does not automatically restart the job. `pdo resume` only unpauses an existing optimization. Failed rows need an error-group retry. Interrupted imports and exports must be started again.

If startup fails, check `~/.pdo/logs/daemon-startup.log` and `~/.pdo/logs/daemon.log`. With the Python CLI installed, `pdo daemon status` checks the process and its response. `pdo daemon repair` stops an unresponsive daemon before removing stale connection files; it does not reset the product database. Open PDO again afterward.

## CLI on Linux and Windows

The source setup above installs the CLI. For a CLI-only environment, install `python -m pip install -e '.[gemini,zhipuai,openai]'` from the checkout inside an activated Python 3.12+ virtual environment.

Configure credentials before starting the daemon, for example `pdo config set gemini.api_key YOUR_API_KEY`. Then run these steps interactively against an empty batch:

```bash
pdo daemon start
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo --json status
```

Repeat the status command until `busy` is `false`. Check `last_result.error`, `imported_count`, and `skipped_count` before continuing:

```bash
pdo optimize --optimizer gemini --watch
pdo export optimized-products.csv
pdo --json status
```

Wait for export to finish and check `last_result.total_exported`. Import/export success messages acknowledge the start of background work. They do not confirm completion.

CLI import **appends** rows and does not deduplicate product IDs. Before importing a different batch, export anything you need, then use `pdo reset` and confirm deletion. GUI replacement, correction imports, grouped retries, and custom export formatting currently have no CLI flags. The [CLI Reference](cli_reference.md) covers these differences, configuration refresh, JSON output, and known command limitations.
