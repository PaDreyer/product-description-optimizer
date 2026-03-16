"""Optimizer registry — discover, list, and instantiate optimizer backends.

The registry is the single source of truth for available optimizers.
Each entry maps a short name to a factory function and metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdo.config import PdoConfig

# Defaults for the local_llm backend — override with:
#   pdo config set local_llm_address <url>
#   pdo config set local_llm_model   <model>
_DEFAULT_LOCAL_LLM_ADDRESS = "http://127.0.0.1:11434/v1"
_DEFAULT_LOCAL_LLM_MODEL = "local-model"


@dataclass(frozen=True)
class OptimizerInfo:
    """Describes an optimizer backend."""

    name: str
    description: str
    available: bool
    reason: str = ""


def _get_opt(config: "PdoConfig | None", key: str, default: Any = None) -> Any:
    """Safely read a config option, returning *default* when config is absent."""
    if config is None:
        return default
    return config.options.get(key) or default


def _check_gemini_available(config: "PdoConfig | None" = None) -> tuple[bool, str]:
    """Check whether the Gemini backend can be used."""
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False, "google-genai not installed (pip install 'pdo[gemini]')"

    api_key = _get_opt(config, "gemini_api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return False, "GEMINI_API_KEY not set in config or environment"
    return True, ""


def list_optimizers(config: "PdoConfig | None" = None) -> list[OptimizerInfo]:
    """Return metadata for every registered optimizer."""
    gemini_ok, gemini_reason = _check_gemini_available(config)
    return [
        OptimizerInfo(
            name="local_llm",
            description="OpenAI-compatible local server (e.g. Ollama, LM Studio)",
            available=True,
        ),
        OptimizerInfo(
            name="gemini",
            description="Google Gemini 2.0 Flash — two-step optimize + validate",
            available=gemini_ok,
            reason=gemini_reason,
        ),
        OptimizerInfo(
            name="dummy",
            description="Uppercase placeholder for development and testing",
            available=True,
        ),
    ]


def get_default_optimizer_name(config: "PdoConfig | None" = None) -> str:
    """Return the name of the best available optimizer.

    Returns ``"gemini"`` when the Gemini SDK and API key are present,
    otherwise ``"dummy"``.
    """
    gemini_ok, _ = _check_gemini_available(config)
    return "gemini" if gemini_ok else "dummy"


def _common_optimizer_kwargs(config: "PdoConfig | None") -> dict[str, Any]:
    """Extract the shared optimizer kwargs from config."""
    return {
        "target_sentences": int(_get_opt(config, "target_sentences", 3)),
        "style_instructions": _get_opt(config, "style_instructions"),
        "optimize_temperature": float(_get_opt(config, "optimize_temperature", 0.4)),
        "validate_temperature": float(_get_opt(config, "validate_temperature", 0.1)),
    }


def create_optimizer(name: str, config: "PdoConfig | None" = None, **kwargs: Any):
    """Instantiate an optimizer by name.

    Args:
        name: Registry name (``"gemini"``, ``"local_llm"``, or ``"dummy"``).
        config: Optional PdoConfig instance for fetching connection settings.
        **kwargs: Passed through to the optimizer constructor
            (e.g. ``api_key`` for Gemini).

    Returns:
        An :class:`~pdo.core.optimizer.Optimizer` instance.

    Raises:
        ValueError: If the name is unknown or the backend is unavailable.
    """
    from pdo.core.optimizer import DummyOptimizer

    if name == "dummy":
        return DummyOptimizer()

    if name == "gemini":
        try:
            from pdo.core.gemini_optimizer import GeminiOptimizer
        except ImportError as exc:
            msg = (
                "Gemini optimizer requires the google-genai package. "
                "Install with: pip install 'pdo[gemini]'"
            )
            raise ValueError(msg) from exc

        api_key = (
            kwargs.get("api_key")
            or _get_opt(config, "gemini_api_key", "")
            or os.environ.get("GEMINI_API_KEY", "")
        )
        if not api_key:
            msg = (
                "Gemini optimizer requires an API key. "
                "Set GEMINI_API_KEY or pass --api-key on the CLI."
            )
            raise ValueError(msg)
        return GeminiOptimizer(api_key=api_key, **_common_optimizer_kwargs(config))

    if name == "local_llm":
        try:
            from pdo.core.local_llm_optimizer import LocalLLMOptimizer
        except ImportError as exc:
            msg = (
                "Local LLM optimizer requires the openai package. "
                "Install with: pip install 'pdo[openai]'"
            )
            raise ValueError(msg) from exc

        address = _get_opt(config, "local_llm_address", _DEFAULT_LOCAL_LLM_ADDRESS)
        model = _get_opt(config, "local_llm_model", _DEFAULT_LOCAL_LLM_MODEL)
        return LocalLLMOptimizer(address=address, model=model, **_common_optimizer_kwargs(config))

    known = [o.name for o in list_optimizers(config)]
    msg = f"Unknown optimizer: {name!r}. Available: {', '.join(known)}"
    raise ValueError(msg)
