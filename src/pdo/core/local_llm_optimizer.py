"""Local LLM product description optimizer using the OpenAI protocol.

Uses any OpenAI-compatible API (e.g., Ollama, LM Studio, vLLM) in a two-step flow:
1. **Optimize** — rewrite the product description for clarity, SEO, and appeal.
2. **Validate** — ask the LLM to verify the result contains no false promises,
   hallucinated features, or inaccurate claims.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pdo.core.optimizer import Optimizer

log = logging.getLogger(__name__)

# Prompt templates
_SYSTEM_OPTIMIZE = """\
You are an expert product copywriter for a B2B office supplies catalogue.
Your task is to rewrite product descriptions so they are:
- Clear, concise, and professional
- SEO-friendly (use relevant keywords naturally)
- Factually accurate — use ONLY information present in the input
- Well-structured with key features highlighted

Rules:
- Do NOT invent features, specifications, or claims that are not in the input.
- Do NOT add superlatives ("best", "leading", "unmatched") unless they are in
  the original description.
- Keep the tone professional and informative.
- If the original description is empty, create one based purely on the context
  fields provided (title, brand, attributes, etc.).
- Respond with ONLY the optimized description text. No headers, no markdown,
  no explanations.
- Write in the SAME LANGUAGE as the original description.
"""

_USER_OPTIMIZE = """\
Product ID: {product_id}

Original Description:
{description}

Context:
{context}

Write an optimized product description based ONLY on the information above.
"""

_SYSTEM_VALIDATE = """\
You are a quality-assurance reviewer for product descriptions.
Your job is to compare an optimized description against the original product
data and determine whether the optimized version is accurate.

Check for:
1. **False promises** — claims not supported by the original data
2. **Hallucinated features** — specifications or properties that do not appear
   in the original data
3. **Misleading statements** — exaggerations or implications not backed by facts
4. **Language consistency** — the optimized text should be in the same language
   as the original

Respond in JSON (no markdown fences) with exactly this structure:
{{"approved": true/false, "issues": ["issue1", "issue2", ...], "suggestion": "..."}}

- If approved is true, issues should be empty and suggestion should be empty.
- If approved is false, list every issue found and provide a corrected version
  in the "suggestion" field that fixes the issues while keeping the improved
  style.
"""

_USER_VALIDATE = """\
Original Product Data:
- Product ID: {product_id}
- Original Description: {description}
- Context: {context}

Optimized Description:
{optimized}

Is this optimized description accurate and free of false promises?
"""

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds


class LocalLLMOptimizer(Optimizer):
    """Two-step optimizer using any OpenAI-compatible local server.

    Step 1: Generate an optimized description.
    Step 2: Validate the result for accuracy (no hallucinations/false promises).
           If validation fails, use the corrected suggestion instead.

    Args:
        address: The absolute URL of the local LLM server (e.g., ``http://127.0.0.1:11434/v1``).
            Configure with: ``pdo config set local_llm_address <url>``
        model: Model identifier to request. Convention varies by server — Ollama uses
            ``deepseek-r1:8b``, LM Studio uses whatever is loaded (field often ignored).
            Configure with: ``pdo config set local_llm_model <model>``
        temperature: Sampling temperature for generation (default: 0.7).
        max_retries: Number of retries on transient API errors.
    """

    def __init__(
        self,
        *,
        address: str,
        model: str = "local-model",
        temperature: float = 0.7,
        max_retries: int = _MAX_RETRIES,
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

        self._client = OpenAI(base_url=address, api_key="local")
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries

    # ── Public interface (Optimizer ABC) ──────────────────────────────

    def optimize(
        self,
        product_id: str,
        description: str,
        context: dict[str, str] | None = None,
    ) -> str:
        """Optimize a product description using a two-step flow."""
        ctx_str = self._format_context(context)

        # Step 1: Optimize
        optimized = self._call_openai(
            system=_SYSTEM_OPTIMIZE,
            user=_USER_OPTIMIZE.format(
                product_id=product_id,
                description=description or "(empty)",
                context=ctx_str,
            ),
        )
        log.info("Step 1 complete for %s: generated %d chars", product_id, len(optimized))

        # Step 2: Validate
        validation_raw = self._call_openai(
            system=_SYSTEM_VALIDATE,
            user=_USER_VALIDATE.format(
                product_id=product_id,
                description=description or "(empty)",
                context=ctx_str,
                optimized=optimized,
            ),
        )

        validated = self._parse_validation(validation_raw, optimized)
        log.info("Step 2 complete for %s: approved=%s", product_id, validated == optimized)

        return validated

    # ── Internals ────────────────────────────────────────────────────

    def _call_openai(self, *, system: str, user: str) -> str:
        """Call the OpenAI-compatible API with retry logic."""
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=self._temperature,
                )
                text = response.choices[0].message.content
                if text:
                    return text.strip()
                msg = "Local LLM returned empty response"
                raise ValueError(msg)
            except Exception as exc:
                if attempt == self._max_retries:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
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

    @staticmethod
    def _format_context(context: dict[str, str] | None) -> str:
        """Format the context dict as a readable string for the prompt."""
        if not context:
            return "(none)"
        return "\n".join(f"- {k}: {v}" for k, v in context.items() if v)

    @staticmethod
    def _parse_validation(raw: str, original_optimized: str) -> str:
        """Parse the JSON validation response."""
        try:
            # Strip markdown fences if present
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

            data: dict[str, Any] = json.loads(cleaned)

            if data.get("approved", False):
                return original_optimized

            issues = data.get("issues", [])
            if issues:
                log.warning("Validation issues: %s", issues)

            suggestion = data.get("suggestion", "").strip()
            if suggestion:
                log.info("Using corrected suggestion from validation step")
                return suggestion

            # If no suggestion provided, fall back to original optimized
            return original_optimized
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("Could not parse validation response, using optimized as-is")
            return original_optimized
