"""ZhipuAI-powered product description optimizer.

Uses ZhipuAI's GLM models (glm-4, glm-4-plus) in a two-step flow:
1. **Optimize** — rewrite the product description for clarity, SEO, and appeal.
2. **Validate** — ask the LLM to verify the result contains no false promises,
   hallucinated features, or inaccurate claims.

Set the API key via the ``ZHIPUAI_API_KEY`` environment variable or
``pdo config set zhipuai.api_key <key>``.
"""

from __future__ import annotations

import logging
import os
import time

from pdo.core.base_llm_optimizer import BaseLLMOptimizer

log = logging.getLogger(__name__)


class ZhipuAIOptimizer(BaseLLMOptimizer):
    """Two-step optimizer using the ZhipuAI API (GLM models).

    Step 1: Generate an optimized description.
    Step 2: Validate the result for accuracy (no hallucinations/false promises).
           If validation fails, use the corrected suggestion instead.

    Args:
        model: ZhipuAI model name (default: ``glm-4``).
        api_key: API key. Falls back to ``ZHIPUAI_API_KEY`` env var or
            ``zhipuai.api_key`` config.
        optimize_temperature: Sampling temperature for generation (default: 0.4).
        validate_temperature: Sampling temperature for validation (default: 0.1).
        max_retries: Number of retries on transient API errors.
        target_sentences: Target number of sentences for the optimized description
            (default: 3). Configure with: ``pdo config set target_sentences <n>``
        style_instructions: Optional extra instructions appended to the system prompt,
            e.g. ``"Start with the main benefit. End with a call to action."``
            Configure with: ``pdo config set style_instructions "..."``
    """

    _DEFAULT_MODEL = "glm-4"

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
        try:
            from zhipuai import ZhipuAI
        except ImportError as exc:
            msg = (
                "ZhipuAI optimizer requires the zhipuai package. "
                "Install with: pip install 'pdo[zhipuai]'"
            )
            raise ValueError(msg) from exc

        key = api_key or os.environ.get("ZHIPUAI_API_KEY", "")
        if not key:
            msg = (
                "ZhipuAI API key required. Set ZHIPUAI_API_KEY environment "
                "variable or pass api_key= to ZhipuAIOptimizer."
            )
            raise ValueError(msg)

        super().__init__(
            optimize_temperature=optimize_temperature,
            validate_temperature=validate_temperature,
            max_retries=max_retries,
            target_sentences=target_sentences,
            style_instructions=style_instructions,
        )
        self._client = ZhipuAI(api_key=key)
        self._model = model

    def _call_llm(self, *, system: str, user: str, temperature: float) -> str:
        """Call the ZhipuAI API with retry logic for transient errors."""
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
                msg = "ZhipuAI returned empty response"
                raise ValueError(msg)
            except Exception as exc:
                if attempt == self._max_retries:
                    raise
                delay = self._retry_delay(attempt)
                log.warning(
                    "ZhipuAI API error (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    self._max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        msg = "All retries exhausted"
        raise RuntimeError(msg)
