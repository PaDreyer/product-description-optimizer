from __future__ import annotations

__doc__ = """ChatGPT subscription adapter using an independently installed Codex CLI."""

from pathlib import Path
from typing import Any

from pdo.core.base_llm_optimizer import BaseLLMOptimizer
from pdo.core.codex_client import CodexClient
from pdo.exceptions import ConfigError


class CodexOptimizer(BaseLLMOptimizer):
    """Use a ChatGPT-authenticated Codex app-server for the shared two-step flow.

    Args:
        home: PDO-specific Codex profile directory.
        model: Model selected from the subscription's model list.
        executable: Installed Codex executable name or path.
        **kwargs: Shared copywriting settings. Temperature uses Codex defaults.

    Raises:
        ConfigError: If no model has been selected.
    """

    def __init__(self, *, home: Path, model: str, executable: str = "codex", **kwargs: Any) -> None:
        if not model.strip():
            raise ConfigError("Select a ChatGPT model in Settings first.")
        super().__init__(**kwargs)
        self._home = home
        self._model = model
        self._executable = executable

    def _call_llm(self, *, system: str, user: str, temperature: float) -> str:
        with CodexClient(self._home, self._executable) as client:
            return client.generate(self._model, system, user)
