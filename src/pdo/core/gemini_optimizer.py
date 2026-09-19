"""Gemini-powered product description optimizer.

Uses Google's Gemini API in a two-step flow:
1. **Optimize** — rewrite the product description for clarity, SEO, and appeal.
2. **Validate** — ask Gemini to verify the result contains no false promises,
   hallucinated features, or inaccurate claims.

Set the API key via the ``GEMINI_API_KEY`` environment variable.
"""

from __future__ import annotations

import logging
import os
import time

from google import genai
from google.genai import types

from pdo.core.base_llm_optimizer import BaseLLMOptimizer
from pdo.core.provider_defaults import GEMINI_MODEL

log = logging.getLogger(__name__)


class GeminiOptimizer(BaseLLMOptimizer):
    """Two-step optimizer using the Google Gemini API.

    Step 1: Generate an optimized description.
    Step 2: Validate the result for accuracy (no hallucinations/false promises).
           If validation fails, use the corrected suggestion instead.

    Args:
        model: Gemini model name (default: ``gemini-3.6-flash``).
        api_key: API key. Falls back to ``GEMINI_API_KEY`` env var or ``gemini.api_key`` config.
        optimize_temperature: Sampling temperature for generation (default: 0.4).
        validate_temperature: Sampling temperature for validation (default: 0.1).
        max_retries: Number of retries on transient API errors.
        target_sentences: Target number of sentences for the optimized description
            (default: 3). Configure with: ``pdo config set target_sentences <n>``
        style_instructions: Optional extra instructions appended to the system prompt,
            e.g. ``"Start with the main benefit. End with a call to action."``
            Configure with: ``pdo config set style_instructions "..."``
    """

    _DEFAULT_MODEL = GEMINI_MODEL

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        optimize_temperature: float = 0.4,
        validate_temperature: float = 0.1,
        max_retries: int = 3,
        target_sentences: int = 3,
        style_instructions: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            msg = (
                "Gemini API key required. Set GEMINI_API_KEY environment "
                "variable or pass api_key= to GeminiOptimizer."
            )
            raise ValueError(msg)

        super().__init__(
            optimize_temperature=optimize_temperature,
            validate_temperature=validate_temperature,
            max_retries=max_retries,
            target_sentences=target_sentences,
            style_instructions=style_instructions,
        )
        self._client = genai.Client(api_key=key)
        self._model = model

    # ── LLM call implementation ──────────────────────────────────────

    def _call_llm(self, *, system: str, user: str, temperature: float) -> str:
        """Call the Gemini API with retry logic for transient errors."""
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=temperature,
                    ),
                )
                text = response.text
                if text:
                    return text.strip()
                msg = "Gemini returned empty response"
                raise ValueError(msg)
            except Exception as exc:
                if attempt == self._max_retries:
                    raise
                delay = self._retry_delay(attempt)
                log.warning(
                    "Gemini API error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    self._max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        # Unreachable, but satisfies the type checker
        msg = "All retries exhausted"
        raise RuntimeError(msg)
