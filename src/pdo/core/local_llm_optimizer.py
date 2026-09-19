"""Local LLM product description optimizer using the OpenAI protocol.

Uses any OpenAI-compatible API (e.g., Ollama, LM Studio, vLLM) in a two-step flow:
1. **Optimize** — rewrite the product description for clarity, SEO, and appeal.
2. **Validate** — ask the LLM to verify the result contains no false promises,
   hallucinated features, or inaccurate claims.
"""

from __future__ import annotations

import logging
import time

from pdo.core.base_llm_optimizer import BaseLLMOptimizer
from pdo.core.provider_defaults import LOCAL_LLM_MODEL

log = logging.getLogger(__name__)


class LocalLLMOptimizer(BaseLLMOptimizer):
    """Two-step optimizer using any OpenAI-compatible local server.

    Step 1: Generate an optimized description.
    Step 2: Validate the result for accuracy (no hallucinations/false promises).
           If validation fails, use the corrected suggestion instead.

    Args:
        address: The absolute URL of the local LLM server (e.g., ``http://127.0.0.1:11434/v1``).
            Configure with: ``pdo config set local_llm.address <url>``
        model: Model identifier to request. Convention varies by server — Ollama uses
            ``deepseek-r1:8b``, LM Studio uses whatever is loaded (field often ignored).
            Configure with: ``pdo config set local_llm.model <model>``
        optimize_temperature: Sampling temperature for generation (default: 0.4).
        validate_temperature: Sampling temperature for validation (default: 0.1).
        max_retries: Number of retries on transient API errors.
        target_sentences: Target number of sentences for the optimized description
            (default: 3). Configure with: ``pdo config set target_sentences <n>``
        style_instructions: Optional extra instructions appended to the system prompt,
            e.g. ``"Start with the main benefit. End with a call to action."``
            Configure with: ``pdo config set style_instructions "..."``
    """

    def __init__(
        self,
        *,
        address: str,
        model: str = LOCAL_LLM_MODEL,
        optimize_temperature: float = 0.4,
        validate_temperature: float = 0.1,
        max_retries: int = 3,
        target_sentences: int = 3,
        style_instructions: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            msg = (
                "Local LLM optimizer requires the openai package. "
                "Install with: pip install 'pdo[openai]'"
            )
            raise ValueError(msg) from exc

        if not address:
            raise ValueError("address must be provided for LocalLLMOptimizer")

        super().__init__(
            optimize_temperature=optimize_temperature,
            validate_temperature=validate_temperature,
            max_retries=max_retries,
            target_sentences=target_sentences,
            style_instructions=style_instructions,
        )
        self._client = OpenAI(base_url=address, api_key="local")
        self._model = model

    # ── LLM call implementation ──────────────────────────────────────

    def _call_llm(self, *, system: str, user: str, temperature: float) -> str:
        """Call the OpenAI-compatible API with retry logic."""
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                )
                text = response.choices[0].message.content
                if text:
                    return text.strip()
                msg = "Local LLM returned empty response"
                raise ValueError(msg)
            except Exception as exc:
                if attempt == self._max_retries:
                    raise
                delay = self._retry_delay(attempt)
                log.warning(
                    "Local LLM API error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    self._max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        # Unreachable, but satisfies the type checker
        msg = "All retries exhausted"
        raise RuntimeError(msg)
