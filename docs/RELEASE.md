# Releasing PDO

The release workflow publishes Linux `.AppImage` and `.deb` packages and a Windows `.exe` installer from a `v*` tag. The Linux runner builds in a Debian 12 container. The Windows runner builds with a separate virtual environment and Inno Setup. The workflow attaches all packages and `SHA256SUMS.txt` to a GitHub Release.

## Prepare a version

1. Update `project.version` in `pyproject.toml` and `pdo.__version__` in `src/pdo/__init__.py` to the same version.
2. Update the README and other documentation for user-visible changes.
3. Run `./scripts/setup-dev.sh`, then `make lint` and `make test`. On Windows, use `.\scripts\setup-dev.ps1`.
4. Review and commit the changes. A tag must refer to that reviewed commit.

The workflow rejects tags that do not equal `v` followed by the project version. Pushing `main` runs tests but does not create a release. Pushing a version tag starts the release workflow:

```bash
git tag -a v0.2.0 -m "PDO 0.2.0"
git push origin v0.2.0
```

Only push a tag when you intend to publish a release. Treat published tags as immutable; fix a failed release with a new patch version.

## Build stages

- **Verify:** Match tag and version, then run Ruff and all tests in a fresh virtual environment.
- **Linux:** Run `scripts/build-linux-container.sh`. Its Debian 12 image provides Python 3.12, Qt system libraries, and appimagetool. The script installs `requirements-build.txt` in an isolated build environment, runs desktop, StatusNotifier D-Bus, and daemon-client pipeline tests, validates the desktop and AppStream metadata, smoke-tests the packaged GUI with its detached daemon, and creates AppImage and Debian packages. Both packages include the AppStream metadata.
- **Windows:** Run `scripts/build-windows.ps1`. It installs `requirements-build.txt` in an isolated build environment, runs desktop and daemon-client pipeline tests, smoke-tests the packaged GUI with its detached daemon, and creates the installer with Inno Setup.
- **Publish:** Collect the three assets, write SHA-256 checksums and commit-based release notes, then create or update the GitHub Release.

For version `0.2.0`, the expected files are `PDO-0.2.0-x86_64.AppImage`, `PDO-0.2.0-amd64.deb`, `PDO-Setup-0.2.0-x64.exe`, and `SHA256SUMS.txt`.

The packages are currently unsigned. Before announcing a release, check that every job passed, download the artifacts, and verify the checksums with `sha256sum --check SHA256SUMS.txt` on Linux. The Windows and Linux builds must be exercised on their respective target systems before calling a release production ready.

The Linux binaries are built on Debian 12 and require glibc 2.36 or newer. To build locally, use `./scripts/build-linux-container.sh` on Linux with Docker, or `.\scripts\build-windows.ps1` on Windows with Python 3.12 and Inno Setup installed.

On Windows, Inno Setup closes a running PDO process during an update and does not restart it automatically. An active job stops at that point; opening the updated GUI starts the daemon again and requeues interrupted products.
