from __future__ import annotations

__doc__ = """Exercise Codex's stdio lifecycle without real credentials or model requests."""

import json
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdo.config import PdoConfig
from pdo.core.codex_client import CodexClient
from pdo.core.registry import create_optimizer, list_optimizers
from pdo.exceptions import ConfigError, OptimizationError


@pytest.fixture
def fake_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[str]]:
    script = Path(__file__).parent / "fixtures" / "codex_app_server.py"
    popen = subprocess.Popen
    processes = []

    def launch(args: list[str], **kwargs: object) -> subprocess.Popen[str]:
        env = kwargs["env"]
        assert "OPENAI_API_KEY" not in env
        assert "CODEX_API_KEY" not in env
        assert "OPENAI_BASE_URL" not in env
        for name in (
            "CODEX_ACCESS_TOKEN",
            "CODEX_SQLITE_HOME",
            "OPENAI_FEDERATION_RULE_ID",
            "OPENAI_IDENTITY_TOKEN_FILE",
            "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
        ):
            assert name not in env
        assert env["CODEX_HOME"] == str(tmp_path / "profile")
        assert "features.shell_tool=false" in args
        process = popen([sys.executable, str(script)], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-use")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-use")
    for name in (
        "CODEX_ACCESS_TOKEN",
        "CODEX_SQLITE_HOME",
        "OPENAI_FEDERATION_RULE_ID",
        "OPENAI_IDENTITY_TOKEN_FILE",
        "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
    ):
        monkeypatch.setenv(name, "must-not-inherit")
    monkeypatch.setattr("pdo.core.codex_client.shutil.which", lambda _: sys.executable)
    monkeypatch.setattr("pdo.core.codex_client.subprocess.Popen", launch)
    return processes


def test_login_models_generation_and_cleanup(fake_server: list, tmp_path: Path) -> None:
    with CodexClient(tmp_path / "profile") as client:
        with patch("pdo.core.codex_client.webbrowser.open", return_value=True) as browser:
            client.login()
            browser.assert_called_once()
        assert client.models() == ["first", "second"]
        assert client.generate("first", "System instructions", "Original copy") == "Final copy."
    assert fake_server[0].poll() is not None
    assert fake_server[0].stdin.closed
    assert fake_server[0].stdout.closed


def test_cleanup_on_operation_failure(fake_server: list, tmp_path: Path) -> None:
    with (
        pytest.raises(ConfigError, match="browser"),
        CodexClient(tmp_path / "profile") as client,
        patch("pdo.core.codex_client.webbrowser.open", return_value=False),
    ):
        client.login()
    assert fake_server[0].poll() is not None


def test_missing_cli_actionable(tmp_path: Path) -> None:
    with (
        patch("pdo.core.codex_client.shutil.which", return_value=None),
        pytest.raises(ConfigError, match="Codex CLI is missing"),
        CodexClient(tmp_path),
    ):
        pass


@pytest.mark.parametrize("account", [None, {"type": "apiKey"}])
def test_subscription_never_falls_back_to_api_billing(tmp_path: Path, account: dict | None) -> None:
    client = CodexClient(tmp_path)
    with (
        patch.object(client, "call", return_value={"account": account}),
        pytest.raises(ConfigError, match="ChatGPT authentication"),
    ):
        client.require_subscription()


def test_wait_is_bounded(tmp_path: Path) -> None:
    client = CodexClient(tmp_path)
    with pytest.raises(ConfigError, match="timeout"):
        client.event(time.monotonic())


def test_rpc_error_is_reported(tmp_path: Path) -> None:
    client = CodexClient(tmp_path)
    client._messages.put({"id": 1, "error": {"message": "Model unavailable"}})
    with patch.object(client, "_send"), pytest.raises(ConfigError, match="Model unavailable"):
        client.call("model/list", {})


def test_failed_turn_is_not_accepted(tmp_path: Path) -> None:
    client = CodexClient(tmp_path)
    events = [
        {
            "method": "turn/completed",
            "params": {
                "threadId": "t",
                "turn": {"id": "u", "status": "failed", "error": {"message": "rate limit"}},
            },
        }
    ]
    with (
        patch.object(client, "require_subscription"),
        patch.object(client, "call", side_effect=[{"thread": {"id": "t"}}, {"turn": {"id": "u"}}]),
        patch.object(client, "event", side_effect=events),
        pytest.raises(OptimizationError, match="rate limit"),
    ):
        client.generate("model", "system", "user")


def test_subscription_optimizer_and_registry(tmp_path: Path) -> None:
    config = PdoConfig(
        config_file_path=tmp_path / "config.toml",
        options={
            "openai.auth_mode": "chatgpt",
            "openai.chatgpt_model": "subscription-model",
            "openai.codex_path": "custom-codex",
        },
    )
    with patch("pdo.core.codex_optimizer.CodexClient") as factory:
        factory.return_value.__enter__.return_value.generate.side_effect = [
            "Good copy.",
            json.dumps({"approved": True}),
        ]
        optimizer = create_optimizer("openai", config)
        assert optimizer.optimize("id", "Original") == "Good copy."
        factory.assert_called_with(tmp_path / "codex", "custom-codex")
    with patch("pdo.core.registry.shutil.which", return_value=None):
        assert not next(o for o in list_optimizers(config) if o.name == "openai").available
    with patch("pdo.core.registry.shutil.which", return_value="/bin/codex"):
        assert next(o for o in list_optimizers(config) if o.name == "openai").available


def test_invalid_auth_mode_and_missing_model_fail_closed() -> None:
    with pytest.raises(ConfigError, match="auth_mode"):
        create_optimizer("openai", PdoConfig(options={"openai.auth_mode": "typo"}))
    with pytest.raises(ConfigError, match="ChatGPT model"):
        create_optimizer("openai", PdoConfig(options={"openai.auth_mode": "chatgpt"}))


def test_closed_gui_cancels_pending_codex_request(tmp_path: Path) -> None:
    import threading

    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ConfigError, match="interrupted"):
        CodexClient(tmp_path, cancel=cancel).event(time.monotonic() + 180)


def test_cli_subscription_login_reports_available_models(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from pdo.cli.main import cli

    with patch("pdo.core.codex_client.CodexClient") as factory:
        factory.return_value.__enter__.return_value.models.return_value = ["first", "second"]
        result = CliRunner().invoke(
            cli,
            ["--config", str(tmp_path / "config.toml"), "optimizer", "login", "openai", "--json"],
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["models"] == ["first", "second"]
    factory.return_value.__enter__.return_value.login.assert_called_once()


@pytest.mark.parametrize("host", ["chatgpt.com", "auth.openai.com"])
def test_login_accepts_official_browser_origins(tmp_path: Path, host: str) -> None:
    client = CodexClient(tmp_path)
    url = f"https://{host}/authorize?state=test"
    with (
        patch.object(client, "call", return_value={"authUrl": url, "loginId": "login"}),
        patch.object(
            client,
            "event",
            return_value={
                "method": "account/login/completed",
                "params": {"loginId": "login", "success": True},
            },
        ),
        patch.object(client, "require_subscription"),
        patch("pdo.core.codex_client.webbrowser.open", return_value=True) as browser,
    ):
        client.login()
    browser.assert_called_once_with(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://chatgpt.com/authorize",
        "https://chatgpt.com.example.org/authorize",
        "https://user:password@chatgpt.com/authorize",
        "https://chatgpt.com:8443/authorize",
        "https://chatgpt.com:invalid/authorize",
        "https://[invalid/authorize",
    ],
)
def test_login_rejects_untrusted_browser_urls(tmp_path: Path, url: str) -> None:
    with (
        patch.object(CodexClient, "call", return_value={"authUrl": url}),
        patch("pdo.core.codex_client.webbrowser.open") as browser,
        pytest.raises(ConfigError, match="sign-in address"),
    ):
        CodexClient(tmp_path).login()
    browser.assert_not_called()


@pytest.mark.parametrize("buffered", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
def test_buffered_notifications_cannot_bypass_deadline_or_cancellation(
    tmp_path: Path, buffered: bool, cancelled: bool
) -> None:
    client = CodexClient(tmp_path)
    event = {"method": "item/agentMessage/delta", "params": {"delta": "still working"}}
    if buffered:
        client._events.extend([event] * 100)
    else:
        for _ in range(100):
            client._messages.put(event)
    if cancelled:
        client._cancel.set()
    with pytest.raises(ConfigError, match="interrupted" if cancelled else "timeout"):
        client.event(time.monotonic() + (30 if cancelled else -1))


def test_expired_rpc_does_not_drain_continuous_notifications(tmp_path: Path) -> None:
    client = CodexClient(tmp_path)
    for _ in range(100):
        client._messages.put({"method": "progress", "params": {}})
    with patch.object(client, "_send"), pytest.raises(ConfigError, match="timeout"):
        client.call("model/list", {}, timeout=-1)
    assert client._messages.qsize() == 100


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group regression")
def test_close_stops_wrapper_descendants_holding_stdout(tmp_path: Path) -> None:
    import os
    import signal

    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import json,subprocess,sys,time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])\n"
        "print(json.dumps({'method':'ready'}), flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    client = CodexClient(tmp_path)
    process = subprocess.Popen(
        [sys.executable, str(wrapper)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    import threading

    client._process = process
    client._reader = threading.Thread(target=client._read_messages, daemon=True)
    client._reader.start()
    try:
        assert client.event(time.monotonic() + 3)["method"] == "ready"
        closing = threading.Thread(target=client.close, daemon=True)
        closing.start()
        closing.join(timeout=3)
        assert not closing.is_alive(), "close blocked while a descendant held stdout open"
        assert not client._reader.is_alive()
        assert process.poll() is not None
        assert process.stdout.closed
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)


@pytest.mark.parametrize("taskkill_error", [None, OSError("taskkill unavailable")])
def test_windows_close_stops_tree_and_reaps_launcher(
    tmp_path: Path, taskkill_error: OSError | None
) -> None:
    client = CodexClient(tmp_path)
    process = MagicMock()
    process.pid = 12345
    process.poll.return_value = None
    client._process = process
    with (
        patch("pdo.core.codex_client.os.name", "nt"),
        patch("pdo.core.codex_client.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True),
        patch("pdo.core.codex_client.subprocess.run", side_effect=taskkill_error) as taskkill,
    ):
        client.close()
    taskkill.assert_called_once_with(
        ["taskkill", "/PID", "12345", "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
        creationflags=0x08000000,
    )
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)
    process.stdin.close.assert_called_once()
    process.stdout.close.assert_called_once()
