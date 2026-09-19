# Releasing PDO

The release workflow publishes Linux `.AppImage` and `.deb` packages and a Windows `.exe` installer from a `v*` tag. The Linux runner builds in a Debian 12 container. The Windows runner builds with a separate virtual environment and Inno Setup. The workflow attaches all packages and `SHA256SUMS.txt` to a GitHub Release.

## Prepare a version

1. Update `project.version` in `pyproject.toml` and `pdo.__version__` in `src/pdo/__init__.py` to the same version.
2. Update the README and other documentation for user-visible changes.
3. Run the platform's setup, lint, and complete test commands from the [Development guide](development.md). Linux headless tests need Qt runtime libraries and `QT_QPA_PLATFORM=offscreen`; Windows uses direct Python commands instead of the Makefile's Unix venv paths.
4. Review and commit the changes. A tag must refer to that reviewed commit.

The workflow rejects tags that do not equal `v` followed by the project version. Pushing `main` runs tests but does not create a release. Pushing a version tag starts the release workflow:

```bash
git tag -a v0.2.0 -m "PDO 0.2.0"
git push origin v0.2.0
```

Only push a tag when you intend to publish a release. Treat published tags as immutable; fix a failed release with a new patch version.

## Build stages

- **Verify:** Match the tag, `pyproject.toml` version, and `pdo.__version__`, then run Ruff and all tests on Linux with Python 3.12 in a fresh virtual environment. CI installs the Qt runtime libraries and D-Bus before headless tests. This job does not enforce a coverage percentage.
- **Linux:** Run `scripts/build-linux-container.sh`. Its Debian 12 image provides Python 3.12, Qt system libraries, and appimagetool. The script installs `requirements-build.txt` in an isolated build environment, runs desktop, StatusNotifier D-Bus, and daemon-client pipeline tests, validates the desktop and AppStream metadata, smoke-tests the packaged GUI with its detached daemon, and creates AppImage and Debian packages. Both packages include the AppStream metadata.
- **Windows:** Run `scripts/build-windows.ps1`. It installs `requirements-build.txt` in an isolated build environment, runs desktop and daemon-client pipeline tests, smoke-tests the packaged GUI with its detached daemon, and creates the installer with Inno Setup.
- **Publish:** Collect the three assets, write SHA-256 checksums and commit-based release notes, then create or update the GitHub Release.

For version `0.2.0`, the expected files are `PDO-0.2.0-x86_64.AppImage`, `PDO-0.2.0-amd64.deb`, `PDO-Setup-0.2.0-x64.exe`, and `SHA256SUMS.txt`.

The packages are currently unsigned. Before announcing a release, check that every job passed, download the artifacts, and verify the checksums with `sha256sum --check SHA256SUMS.txt` on Linux. On Windows, compare `Get-FileHash .\PDO-Setup-0.2.0-x64.exe -Algorithm SHA256` with the corresponding line in `SHA256SUMS.txt`. The Windows and Linux builds must be exercised on their respective target systems before calling a release production ready.

Use a disposable batch for the manual package check: import, optimize with **Demo**, review results, export, and reopen the app. Exercise tray **Open** and **Quit**, restart with pending products, retry an error group, and round-trip a correction file with unique IDs. Check a nondefault CSV format and a failed export that preserves an existing destination. Automated packaged smoke tests verify startup and the detached daemon; they do not replace these visible desktop checks or a real-provider connection check.

The Linux binaries are built on Debian 12 and require glibc 2.36 or newer. To build locally, use `./scripts/build-linux-container.sh` on Linux with Docker, or `.\scripts\build-windows.ps1` on Windows with Python 3.12 and Inno Setup installed.

Both builds bundle the GUI and provider SDKs; neither installs a separate `pdo` CLI command. The Debian package adds `pdo-desktop`. Install the Python package separately when CLI access is needed.

On Windows, Inno Setup closes a running PDO process during an update and does not restart it automatically. An active job stops at that point; opening the updated GUI starts the daemon again and requeues interrupted products. The user must start optimization again to process pending rows. Saved successful results remain; failed rows need a retry action.

Local build scripts create artifacts but do not publish them. GitHub publication requires a pushed matching tag and successful verify, Linux, and Windows jobs. Re-running the same tag can update that release's notes and overwrite its assets; preserve published releases by using a new version for subsequent changes.
