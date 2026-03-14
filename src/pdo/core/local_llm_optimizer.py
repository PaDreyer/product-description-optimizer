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
_SYSTEM_OPTIMIZE_BASE = """\
You are a product copywriter. Rewrite the product description to be clear,
concise, professional, and SEO-friendly.

IMPORTANT rules:
1. Use ONLY facts from the input. Do NOT invent anything.
2. Keep all numbers, percentages, warranties, and certifications from the
   original (e.g. "50% weiteres Öffnen", "5 Jahre Garantie", "Blauer Engel").
3. Copy brand names and attribute values exactly as given.
4. Write in the SAME language as the input.
5. Output ONLY the description as a single paragraph — no line breaks, no
   bullet points, no headings, no markdown, no emoji.
6. Use correct grammar.
7. Vary sentence starts — do not begin every sentence the same way.
8. Aim for around {target_sentences} sentences.
{style_block}"""

_USER_OPTIMIZE = """\
Original Description:
{description}

Context:
{context}

{empty_warning}Rewrite as a single paragraph. Keep all numbers, percentages, warranties,
and certifications. Around {target_sentences} sentences.
"""

_SYSTEM_VALIDATE = """\
You are a quality reviewer. Compare the optimized description against the
original data. Check for:
1. Invented claims not in the original
2. Important numbers, warranties, or certifications that were dropped
3. Misspelled brand or product names
4. Grammar errors
5. Wrong language, emoji, or line breaks

Respond in JSON:
{{"approved": true/false, "issues": ["..."], "suggestion": "..."}}

If approved: issues=[], suggestion="".
If not approved: list issues and put a corrected single-paragraph description
in "suggestion".
"""

_USER_VALIDATE = """\
Original Product Data:
- Product ID: {product_id}
- Brand: {brand}
- Original Description: {description}
- Context attributes (must be reproduced exactly, not expanded):
{context}

Optimized Description:
{optimized}

Is this optimized description accurate and free of errors? Check brand name
spelling, attribute values, and absence of emoji carefully.
"""

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds
_DEFAULT_TARGET_SENTENCES = 3


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
        model: str = "local-model",
        optimize_temperature: float = 0.4,
        validate_temperature: float = 0.1,
        max_retries: int = _MAX_RETRIES,
        target_sentences: int = _DEFAULT_TARGET_SENTENCES,
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

        self._client = OpenAI(base_url=address, api_key="local")
        self._model = model
        self._optimize_temperature = optimize_temperature
        self._validate_temperature = validate_temperature
        self._max_retries = max_retries
        self._target_sentences = target_sentences
        style_block = f"\n# Additional Instructions\n{style_instructions}\n" if style_instructions else ""
        self._system_optimize = _SYSTEM_OPTIMIZE_BASE.format(
            target_sentences=target_sentences,
            style_block=style_block,
        )

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
        empty_warning = (
            "[WARNING] The original description is empty. "
            "Use ONLY the Context fields above — do NOT invent any numbers, "
            "specifications, or product categories not listed there.\n\n"
            if not description
            else ""
        )
        optimized = self._call_openai(
            system=self._system_optimize,
            user=_USER_OPTIMIZE.format(
                description=description or "(empty)",
                context=ctx_str,
                empty_warning=empty_warning,
                target_sentences=self._target_sentences,
            ),
            temperature=self._optimize_temperature,
        )
        log.info("Step 1 complete for %s: generated %d chars", product_id, len(optimized))

        # Step 2: Validate
        # Extract brand from context for explicit validation
        brand = (context or {}).get("brand") or (context or {}).get("Marke") or ""
        validation_raw = self._call_openai(
            system=_SYSTEM_VALIDATE,
            user=_USER_VALIDATE.format(
                product_id=product_id,
                brand=brand,
                description=description or "(empty)",
                context=ctx_str,
                optimized=optimized,
            ),
            temperature=self._validate_temperature,
        )

        validated = self._parse_validation(validation_raw, optimized)
        log.info("Step 2 complete for %s: approved=%s", product_id, validated == optimized)

        return validated

    # ── Internals ────────────────────────────────────────────────────

    def _call_openai(self, *, system: str, user: str, temperature: float) -> str:
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
