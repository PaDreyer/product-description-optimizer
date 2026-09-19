from __future__ import annotations

__doc__ = """OpenAI Responses API adapter for two-step product copy optimization."""

import logging
import time

from pdo.core.base_llm_optimizer import BaseLLMOptimizer
from pdo.core.provider_defaults import OPENAI_ADDRESS, OPENAI_MODEL
from pdo.exceptions import ConfigError, OptimizationError

log = logging.getLogger(__name__)


class OpenAIOptimizer(BaseLLMOptimizer):
    """Generate and validate descriptions with an OpenAI API key.

    Args:
        api_key: OpenAI API credential; API usage is billed separately from ChatGPT.
        model: Responses-compatible text model ID.
        optimize_temperature: Generation temperature for GPT-4.1/GPT-4o models.
        validate_temperature: Validation temperature for GPT-4.1/GPT-4o models.
        max_retries: Maximum attempts per request, including the initial attempt.
        target_sentences: Approximate number of output sentences.
        style_instructions: Additional copywriting instructions.

    Raises:
        ConfigError: If the SDK, credential, or model is missing.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = OPENAI_MODEL,
        optimize_temperature: float = 0.4,
        validate_temperature: float = 0.1,
        max_retries: int = 3,
        target_sentences: int = 3,
        style_instructions: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ConfigError("OpenAI requires the SDK: pip install 'pdo[openai]'") from exc
        if not api_key.strip() or not model.strip():
            raise ConfigError("OpenAI requires an API key and model ID.")
        super().__init__(
            optimize_temperature=optimize_temperature,
            validate_temperature=validate_temperature,
            max_retries=max_retries,
            target_sentences=target_sentences,
            style_instructions=style_instructions,
        )
        # Explicit URL prevents OPENAI_BASE_URL from rerouting this provider's key.
        self._client = OpenAI(
            api_key=api_key.strip(), base_url=OPENAI_ADDRESS, timeout=120, max_retries=0
        )
        self._model = model.strip()

    def _call_llm(self, *, system: str, user: str, temperature: float) -> str:
        """Request complete text, retrying only transient transport/API failures."""
        from openai import APIConnectionError, APIStatusError

        # Reasoning models differ in supported sampling parameters. Leave their
        # defaults intact rather than sending an unsupported temperature.
        sampling = (
            {"temperature": temperature} if self._model.startswith(("gpt-4.1", "gpt-4o")) else {}
        )
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.responses.create(
                    model=self._model,
                    instructions=system,
                    input=user,
                    store=False,
                    **sampling,
                )
                if response.status != "completed":
                    raise OptimizationError("OpenAI returned an incomplete response.")
                text = response.output_text.strip()
                if not text:
                    raise OptimizationError("OpenAI returned no text (empty response or refusal).")
                return text
            except (APIConnectionError, APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                if attempt == self._max_retries or (
                    status is not None and status not in (408, 409, 429) and status < 500
                ):
                    raise
                delay = self._retry_delay(attempt)
                log.warning(
                    "OpenAI %s (attempt %d/%d); retrying in %.1fs",
                    type(exc).__name__,
                    attempt,
                    self._max_retries,
                    delay,
                )
                time.sleep(delay)
        raise OptimizationError("OpenAI request attempts exhausted.")
