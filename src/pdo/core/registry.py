"""Optimizer registry — discover, list, and instantiate optimizer backends.

The registry is the single source of truth for available optimizers.
Each entry maps a short name to a factory function and metadata.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OptimizerInfo:
    """Describes an optimizer backend."""

    name: str
    description: str
    available: bool
    reason: str = ""


def _check_gemini_available() -> tuple[bool, str]:
    """Check whether the Gemini backend can be used."""
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False, "google-genai not installed (pip install 'pdo[gemini]')"
    if not os.environ.get("GEMINI_API_KEY", ""):
        return False, "GEMINI_API_KEY not set"
    return True, ""


def list_optimizers() -> list[OptimizerInfo]:
    """Return metadata for every registered optimizer."""
    gemini_ok, gemini_reason = _check_gemini_available()
    return [
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


def get_default_optimizer_name() -> str:
    """Return the name of the best available optimizer.

    Returns ``"gemini"`` when the Gemini SDK and API key are present,
    otherwise ``"dummy"``.
    """
    gemini_ok, _ = _check_gemini_available()
    return "gemini" if gemini_ok else "dummy"


def create_optimizer(name: str, **kwargs: Any):
    """Instantiate an optimizer by name.

    Args:
        name: Registry name (``"gemini"`` or ``"dummy"``).
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

        api_key = kwargs.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            msg = (
                "Gemini optimizer requires an API key. "
                "Set GEMINI_API_KEY or pass --api-key on the CLI."
            )
            raise ValueError(msg)
        return GeminiOptimizer(api_key=api_key)

    known = [o.name for o in list_optimizers()]
    msg = f"Unknown optimizer: {name!r}. Available: {', '.join(known)}"
    raise ValueError(msg)
