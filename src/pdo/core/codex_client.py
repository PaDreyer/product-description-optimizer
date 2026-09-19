from __future__ import annotations

__doc__ = """Small stdio client for the official Codex app-server subscription interface."""

import json
import logging
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import webbrowser
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pdo.exceptions import ConfigError, OptimizationError

log = logging.getLogger(__name__)


class CodexClient:
    """Own an isolated Codex app-server process for one bounded operation.

    Args:
        home: PDO-specific credential/configuration directory, separate from Codex's user profile.
        executable: Installed Codex executable name or absolute path.
        cancel: Optional event for stopping an operation when its client closes.

    Raises:
        ConfigError: If Codex cannot start or the protocol fails.
    """

    def __init__(
        self, home: Path, executable: str = "codex", *, cancel: threading.Event | None = None
    ) -> None:
        self._home = home
        self._executable = executable
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._messages: queue.Queue[dict[str, Any] | Exception] = queue.Queue()
        self._events: deque[dict[str, Any]] = deque()
        self._next_id = 0
        self._cancel = cancel or threading.Event()

    def __enter__(self) -> CodexClient:
        executable = shutil.which(self._executable)
        if not executable:
            raise ConfigError(
                "Codex CLI is missing. Install Codex and restart PDO, or set openai.codex_path."
            )
        self._home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = dict(os.environ)
        # Isolate PDO login and settings; never copy or parse another app's tokens.
        env["CODEX_HOME"] = str(self._home.resolve())
        for name in (
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN",
            "CODEX_SQLITE_HOME",
            "OPENAI_FEDERATION_RULE_ID",
            "OPENAI_IDENTITY_TOKEN_FILE",
            "OPENAI_WORKLOAD_IDENTITY_CONTEXT",
        ):
            env.pop(name, None)
        args = [executable, "app-server"]
        settings = {
            "model_provider": "openai",
            "cli_auth_credentials_store": "file",
            "web_search": "disabled",
            "features.shell_tool": False,
            "features.unified_exec": False,
            "features.browser_use": False,
            "features.computer_use": False,
            "features.view_image": False,
            "features.image_generation": False,
            "features.multi_agent": False,
            "features.apps": False,
            "features.plugins": False,
            "features.hooks": False,
            "features.remote_plugin": False,
            "project_doc_max_bytes": 0,
        }
        for key, value in settings.items():
            args.extend(["-c", f"{key}={json.dumps(value)}"])
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=self._home,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._reader = threading.Thread(target=self._read_messages, daemon=True)
            self._reader.start()
            self.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "pdo",
                        "title": "Product Description Optimizer",
                        "version": "0.2.0",
                    }
                },
            )
            self._send({"method": "initialized"})
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Stop and reap the subprocess and close its streams."""
        process = self._process
        if process is None:
            return
        # Package-manager launchers can have a native app-server child. Stop
        # the whole owned tree so descendants cannot keep the output pipe open.
        if os.name != "nt":
            self._signal_process_group(signal.SIGTERM)
        elif process.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired):
                log.warning("Could not stop the Codex process tree; terminating the launcher")
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self._reader:
            self._reader.join(timeout=1)
            if self._reader.is_alive() and os.name != "nt":
                self._signal_process_group(signal.SIGKILL)
                self._reader.join(timeout=1)
        if process.stdin:
            process.stdin.close()
        # Closing a TextIOWrapper while another thread is in readline can
        # deadlock on its internal lock. The reader owns that stream's close.
        if process.stdout and (not self._reader or not self._reader.is_alive()):
            process.stdout.close()
        self._process = None

    def _signal_process_group(self, sig: signal.Signals) -> None:
        assert self._process is not None
        with suppress(ProcessLookupError):
            os.killpg(self._process.pid, sig)

    def _read_messages(self) -> None:
        assert self._process and self._process.stdout
        stream = self._process.stdout
        try:
            while line := stream.readline(1_000_001):
                if len(line) > 1_000_000:
                    raise ConfigError("Codex response is too large.")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ConfigError("Invalid Codex response.")
                self._messages.put(message)
        except (OSError, ValueError, ConfigError) as exc:
            self._messages.put(ConfigError(f"Codex protocol error: {type(exc).__name__}"))
        finally:
            stream.close()
            self._messages.put(ConfigError("Codex exited. Check the CLI installation."))

    def _send(self, message: dict[str, Any]) -> None:
        assert self._process and self._process.stdin
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except OSError as exc:
            raise ConfigError("Connection to Codex was interrupted.") from exc

    def _receive(self, deadline: float) -> dict[str, Any]:
        while True:
            self._check_wait(deadline)
            try:
                message = self._messages.get(timeout=max(0, min(0.2, deadline - time.monotonic())))
            except queue.Empty as exc:
                if time.monotonic() < deadline:
                    continue
                raise ConfigError("Codex timeout: request took too long.") from exc
            if isinstance(message, Exception):
                raise message
            if "method" in message and "id" in message:
                # This adapter only consumes text; it never authorizes tool actions.
                self._send(
                    {
                        "id": message["id"],
                        "error": {"code": -32601, "message": "PDO does not support tool requests"},
                    }
                )
                continue
            return message

    def _check_wait(self, deadline: float) -> None:
        if self._cancel.is_set():
            raise ConfigError("Codex request was interrupted.")
        if time.monotonic() >= deadline:
            raise ConfigError("Codex timeout: request took too long.")

    def call(self, method: str, params: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
        """Send a request while retaining intervening notifications.

        Args:
            method: App-server method name.
            params: Method parameters without credentials.
            timeout: Maximum response wait in seconds.

        Returns:
            The method's result object.

        Raises:
            ConfigError: On cancellation, timeout, or a protocol error.
        """
        self._next_id += 1
        request_id = self._next_id
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            message = self._receive(deadline)
            if message.get("id") == request_id:
                if "error" in message:
                    raise ConfigError(f"Codex: {message['error'].get('message', 'Request failed')}")
                return message.get("result", {})
            if "method" in message:
                self._events.append(message)

    def event(self, deadline: float) -> dict[str, Any]:
        """Read the next notification.

        Args:
            deadline: Absolute monotonic deadline for waiting.

        Returns:
            A server notification.

        Raises:
            ConfigError: On cancellation, timeout, or a protocol error.
        """
        self._check_wait(deadline)
        return self._events.popleft() if self._events else self._receive(deadline)

    def require_subscription(self) -> None:
        """Require a ChatGPT login without falling back to API billing.

        Raises:
            ConfigError: If the active account is not authenticated with ChatGPT.
        """
        account = self.call("account/read", {"refreshToken": False}).get("account")
        if not account or account.get("type") != "chatgpt":
            raise ConfigError("ChatGPT authentication is missing. Sign in with ChatGPT in PDO.")

    def login(self) -> None:
        """Open the official browser login and wait up to three minutes.

        Raises:
            ConfigError: If the browser, login, or subscription verification fails.
        """
        result = self.call("account/login/start", {"type": "chatgpt"})
        url = result.get("authUrl", "")
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme == "https"
                and parsed.hostname in {"auth.openai.com", "chatgpt.com"}
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ConfigError("Codex returned an invalid OpenAI sign-in address.")
        if not webbrowser.open(url):
            raise ConfigError("Could not open the browser. Check the default browser.")
        deadline = time.monotonic() + 180
        while True:
            event = self.event(deadline)
            if event.get("method") == "account/login/completed":
                params = event.get("params", {})
                if params.get("loginId") != result.get("loginId"):
                    continue
                if not params.get("success"):
                    raise ConfigError("ChatGPT sign-in failed. Please try again.")
                self.require_subscription()
                return

    def models(self) -> list[str]:
        """List picker-visible models for the authenticated Codex account.

        Returns:
            Unique model IDs in server order.

        Raises:
            ConfigError: If authentication fails or no models are available.
        """
        self.require_subscription()
        models: list[str] = []
        cursor = None
        for _ in range(10):
            result = self.call(
                "model/list", {"limit": 100, "cursor": cursor, "includeHidden": False}
            )
            models.extend(row["model"] for row in result.get("data", []) if row.get("model"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        if not models:
            raise ConfigError("Codex returned no available models for this account.")
        return list(dict.fromkeys(models))

    def generate(self, model: str, system: str, user: str) -> str:
        """Generate text in an ephemeral, read-only conversation.

        Args:
            model: Model ID selected from the subscription model list.
            system: Copywriting or validation instructions.
            user: Product data for this request.

        Returns:
            The completed final answer text.

        Raises:
            ConfigError: If authentication or communication fails.
            OptimizationError: If generation fails or supplies no final text.
        """
        self.require_subscription()
        with tempfile.TemporaryDirectory(prefix="pdo-codex-") as workspace:
            result = self.call(
                "thread/start",
                {
                    "model": model,
                    "cwd": workspace,
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                    "ephemeral": True,
                    "baseInstructions": system,
                },
            )
            thread_id = result["thread"]["id"]
            turn = self.call(
                "turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": user}]}
            )
            turn_id = turn["turn"]["id"]
            deadline = time.monotonic() + 180
            final_text = ""
            while True:
                event = self.event(deadline)
                params = event.get("params", {})
                if params.get("threadId") != thread_id:
                    continue
                if event.get("method") == "item/completed" and params.get("turnId") == turn_id:
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage" and item.get("phase") != "commentary":
                        final_text = item.get("text", "").strip()
                if (
                    event.get("method") == "turn/completed"
                    and params.get("turn", {}).get("id") == turn_id
                ):
                    completed = params["turn"]
                    if completed.get("status") != "completed":
                        error = completed.get("error") or {}
                        raise OptimizationError(
                            f"Codex: {error.get('message', 'Response interrupted')}"
                        )
                    if not final_text:
                        raise OptimizationError("Codex returned no response text.")
                    return final_text
