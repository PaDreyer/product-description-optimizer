# PDO — Product Description Optimizer

PDO is an AI-powered desktop app and CLI for importing, improving, reviewing, and exporting product descriptions from CSV files. It preserves the original columns and supports both cloud and locally hosted AI models.

## What it does

- **Guided CSV workflow:** Preview the file, detect common delimiters and encodings, and map columns before import.
- **Flexible AI integration:** Connect cloud or locally hosted models. Built-in adapters currently support Google Gemini, ZhipuAI, and OpenAI-compatible servers such as Ollama or LM Studio.
- **Reviewable results:** Compare original and revised descriptions side by side, search and page through large batches, and pause or resume between products.
- **Bulk recovery:** Retry entire error groups, export error reports, and import corrected source data by unique product ID while preserving successful results.
- **Configurable CSV export:** Use the source format or optionally choose UTF-8, UTF-16 LE/BE, Windows-1252, or ISO-8859-1; separators, BOM, line endings, quoting, and headers are configurable with a data preview.
- **Local project state:** SQLite stores progress after every product so a stopped run can continue with remaining rows.
- **Desktop and automation:** The PySide6 GUI and CLI are clients of the same background daemon, so progress continues when the window is closed.

## Install

Download a Linux `.AppImage` or `.deb`, or a Windows `.exe` installer from [GitHub Releases](https://github.com/PaDreyer/product-description-optimizer/releases) once a version is published. The packages contain the desktop application and provider libraries; they do not require a separate Python installation. Linux packages currently require glibc 2.36 or newer, as provided by Debian 12 and Ubuntu 24.04.

To run from source, use Python 3.12 or newer:

```bash
git clone https://github.com/PaDreyer/product-description-optimizer.git
cd product-description-optimizer
./scripts/setup-dev.sh
source venv/bin/activate
pdo-desktop
```

On Windows, run `.\scripts\setup-dev.ps1` in PowerShell and activate
`venv\Scripts\Activate.ps1`.

Follow the three desktop steps: **Daten laden**, **Optimieren**, and **Prüfen & exportieren**. Choose a CSV file, assign a description column, and configure the AI connection under **Einstellungen**. API keys entered in the desktop app are saved in `~/.pdo/config.toml`; on Linux the file is created with owner-only permissions. Environment variables `GEMINI_API_KEY` and `ZHIPUAI_API_KEY` also work.

The desktop application starts the PDO daemon automatically. On Linux it registers the tray icon through the StatusNotifierItem D-Bus protocol; a StatusNotifier host must be available (for example, KDE Plasma or GNOME with the AppIndicator extension). On Windows it uses the native Qt tray. Closing the window moves the GUI to the tray while imports, optimization, and exports continue. Click the tray icon or choose **Open** from its menu to reopen the window. **Quit** stops the daemon and closes the GUI. If no tray host is available, closing the window exits the GUI client while the daemon continues; use `pdo daemon stop` to stop it. If the host disappears later, PDO restores the window. Opening PDO again reconnects to the same daemon state.

If startup fails, check `~/.pdo/logs/daemon-startup.log` and `~/.pdo/logs/daemon.log`. The source-install CLI can show daemon status with `pdo daemon status` and stop an unresponsive daemon with `pdo daemon repair`.

The demo backend changes text to uppercase and is meant only to check the import and export flow. Choose an AI backend for useful descriptions. A local server must already be running with a model loaded. **Verbindung prüfen** discovers models: a single model is selected automatically, and a chooser appears when several are available. Manual model IDs are optional under **Erweitert**. Cloud providers receive the mapped description and context fields; use a local server when the product data must stay on your computer.

## CLI

The CLI is available from a Python installation on Linux and Windows. It connects to the same user-local daemon as the desktop application, so both interfaces can be open at the same time. The Windows installer contains the GUI; install the Python package separately to use the CLI there.

```bash
python -m pip install -e '.[gemini,zhipuai,openai]'
pdo daemon start
pdo import products.csv -m product_id:ProduktID -m description:Beschreibung -m context:Marke
pdo optimize --optimizer gemini --watch
pdo export optimized-products.csv
```

See [Getting Started](docs/getting_started.md) and the [CLI Reference](docs/cli_reference.md) for the full command set and configuration options.

## Development

```bash
./scripts/setup-dev.sh
make lint
make test
```

The tag-triggered [release workflow](.github/workflows/release.yml) builds Linux AppImage and Debian packages in a Docker container and a Windows installer with Inno Setup. It checks the tag against the project version, runs tests, and publishes packages with SHA-256 checksums. See [Release guide](docs/RELEASE.md).

## License

[MIT](LICENSE)
