import os
import tomllib
from pathlib import Path

from click.testing import CliRunner

from pdo.cli.main import cli


def test_config_set_and_get(tmp_path: Path, monkeypatch) -> None:
    # Point the application config to our tmp_path
    monkeypatch.setenv("PDO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))

    # We will patch PdoConfig so that `config_file_path` defaults to our temp dir.
    # Alternatively, setting HOME might be enough if PdoConfig respects it, but to be sure:

    cfg_file = tmp_path / ".pdo" / "config.toml"

    class MockConfig:
        def __init__(self):
            self.config_file_path = cfg_file

    monkeypatch.setattr("pdo.cli.config_cmd.PdoConfig", MockConfig)

    runner = CliRunner()

    # 1. Test getting a non-existent key
    result = runner.invoke(cli, ["config", "get", "log_dir"])
    assert result.exit_code == 1
    assert "Key 'log_dir' not found" in result.output

    # 2. Test setting a key
    result = runner.invoke(cli, ["config", "set", "log_dir", "/tmp/custom_logs"])
    assert result.exit_code == 0
    assert "Set log_dir to /tmp/custom_logs" in result.output

    # 3. Verify it was actually written to the file
    assert cfg_file.exists()
    if os.name != "nt":
        assert cfg_file.stat().st_mode & 0o077 == 0
    with cfg_file.open("rb") as f:
        data = tomllib.load(f)
        assert data["pdo"]["log_dir"] == "/tmp/custom_logs"

    # 4. Test getting the key
    result = runner.invoke(cli, ["config", "get", "log_dir"])
    assert result.exit_code == 0
    assert "/tmp/custom_logs" in result.output

    # 5. Test setting another key (should append, not overwrite the first one)
    result = runner.invoke(cli, ["config", "set", "gemini.api_key", "secret123"])
    assert result.exit_code == 0

    # Verify both exist
    with cfg_file.open("rb") as f:
        data = tomllib.load(f)
        assert data["pdo"]["log_dir"] == "/tmp/custom_logs"
        assert data["pdo"]["gemini.api_key"] == "secret123"

    # 6. Test getting the second key
    result = runner.invoke(cli, ["config", "get", "gemini.api_key"])
    assert result.exit_code == 0
    assert "secret123" in result.output

    # 7. Test overriding a key
    result = runner.invoke(cli, ["config", "set", "log_dir", "/var/log/pdo"])
    assert result.exit_code == 0

    with cfg_file.open("rb") as f:
        data = tomllib.load(f)
        assert data["pdo"]["log_dir"] == "/var/log/pdo"
        assert data["pdo"]["gemini.api_key"] == "secret123"

    # 8. Test listing all keys
    result = runner.invoke(cli, ["config", "list"])
    assert result.exit_code == 0
    assert "log_dir = /var/log/pdo" in result.output
    assert "gemini.api_key = secret123" in result.output

    # 9. Test listing empty config
    cfg_file.unlink()
    result = runner.invoke(cli, ["config", "list"])
    assert result.exit_code == 0
    assert "No configuration found" in result.output


def test_config_malformed(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    with cfg_file.open("w") as f:
        f.write("[pdo]\nbad_syntax =")

    class MockConfig:
        def __init__(self):
            self.config_file_path = cfg_file

    monkeypatch.setattr("pdo.cli.config_cmd.PdoConfig", MockConfig)

    runner = CliRunner()
    result = runner.invoke(cli, ["config", "get", "key"])
    assert result.exit_code == 1
    assert "Failed to parse config file" in result.output

    original = cfg_file.read_text()
    result = runner.invoke(cli, ["config", "set", "key", "value"])
    assert result.exit_code == 1
    assert cfg_file.read_text() == original


def test_config_not_a_dict(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.toml"
    with cfg_file.open("w") as f:
        f.write("pdo = 'string'")

    class MockConfig:
        def __init__(self):
            self.config_file_path = cfg_file

    monkeypatch.setattr("pdo.cli.config_cmd.PdoConfig", MockConfig)

    runner = CliRunner()
    result = runner.invoke(cli, ["config", "get", "key"])
    assert result.exit_code == 1
    assert "section must be a dictionary" in result.output


def test_config_custom_path(tmp_path: Path) -> None:
    custom_cfg = tmp_path / "custom.toml"
    runner = CliRunner()

    # Set using custom config path
    result = runner.invoke(
        cli, ["--config", str(custom_cfg), "config", "set", "log_dir", "/custom/log"]
    )
    assert result.exit_code == 0
    assert custom_cfg.exists()

    # Get using custom config path
    result = runner.invoke(cli, ["--config", str(custom_cfg), "config", "get", "log_dir"])
    assert result.exit_code == 0
    assert "/custom/log" in result.output

    # List using custom config path
    result = runner.invoke(cli, ["--config", str(custom_cfg), "config", "list"])
    assert result.exit_code == 0
    assert "log_dir = /custom/log" in result.output
