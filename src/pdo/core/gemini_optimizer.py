"""Gemini-powered product description optimizer.

Uses Google's Gemini API in a two-step flow:
1. **Optimize** — rewrite the product description for clarity, SEO, and appeal.
2. **Validate** — ask Gemini to verify the result contains no false promises,
   hallucinated features, or inaccurate claims.

Set the API key via the ``GEMINI_API_KEY`` environment variable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from google import genai
from google.genai import types

from pdo.core.optimizer import Optimizer

log = logging.getLogger(__name__)

# ── Prompt templates ─────────────────────────────────────────────────

_SYSTEM_OPTIMIZE_BASE = """\
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
- Do NOT use emoji or special symbols.
- Reproduce brand names, product names, and attribute values EXACTLY as given —
  do not paraphrase, abbreviate, or expand them.
- If the context lists a value such as "6 Neonfarben", state it as-is. Do NOT
  enumerate or invent specific sub-values (e.g. do not list colour names).
- If the original description is empty, create one based purely on the context
  fields provided (title, brand, attributes, etc.).
- Respond with ONLY the optimized description text. No headers, no markdown,
  no explanations.
- Write in the SAME LANGUAGE as the original description.
- Write exactly {target_sentences} sentence(s). No more, no less.
{style_block}"""

_USER_OPTIMIZE = """\
Original Description:
{description}

Context:
{context}

{empty_warning}Write exactly {target_sentences} sentence(s). No more, no less.
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
5. **Brand / product name errors** — brand names must be reproduced exactly;
   any misspelling or paraphrase is an error
6. **Invented specifics** — if an attribute says e.g. "6 Neonfarben", the text
   must NOT list individual colour names or other sub-values not in the input
7. **Emoji** — no emoji or special symbols are allowed

Respond in JSON (no markdown fences) with exactly this structure:
{{"approved": true/false, "issues": ["issue1", "issue2", ...], "suggestion": "..."}}

- If approved is true, issues should be empty and suggestion should be empty.
- If approved is false, list every issue found and provide a corrected version
  in the "suggestion" field that fixes ALL issues while keeping the improved
  style.
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

# ── Configuration defaults ───────────────────────────────────────────

_DEFAULT_MODEL = "gemini-2.0-flash"
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds
_DEFAULT_TARGET_SENTENCES = 3


class GeminiOptimizer(Optimizer):
    """Two-step optimizer using the Google Gemini API.

    Step 1: Generate an optimized description.
    Step 2: Validate the result for accuracy (no hallucinations/false promises).
           If validation fails, use the corrected suggestion instead.

    Args:
        model: Gemini model name (default: ``gemini-2.0-flash``).
        api_key: API key. Falls back to ``GEMINI_API_KEY`` env var.
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
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        optimize_temperature: float = 0.4,
        validate_temperature: float = 0.1,
        max_retries: int = _MAX_RETRIES,
        target_sentences: int = _DEFAULT_TARGET_SENTENCES,
        style_instructions: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            msg = (
                "Gemini API key required. Set GEMINI_API_KEY environment "
                "variable or pass api_key= to GeminiOptimizer."
            )
            raise ValueError(msg)

        self._client = genai.Client(api_key=key)
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
        """Optimize a product description using a two-step Gemini flow.

        1. Generate an optimized version.
        2. Validate for accuracy — if issues found, use the corrected
           suggestion.
        """
        ctx_str = self._format_context(context)

        # Step 1: Optimize
        empty_warning = (
            "[WARNING] The original description is empty. "
            "Use ONLY the Context fields above — do NOT invent any numbers, "
            "specifications, or product categories not listed there.\n\n"
            if not description
            else ""
        )
        optimized = self._call_gemini(
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
        validation_raw = self._call_gemini(
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

    def _call_gemini(self, *, system: str, user: str, temperature: float) -> str:
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
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
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

    @staticmethod
    def _format_context(context: dict[str, str] | None) -> str:
        """Format the context dict as a readable string for the prompt."""
        if not context:
            return "(none)"
        return "\n".join(f"- {k}: {v}" for k, v in context.items() if v)

    @staticmethod
    def _parse_validation(raw: str, original_optimized: str) -> str:
        """Parse the JSON validation response.

        Returns the original optimized text if approved, or the corrected
        suggestion if validation found issues.
        """
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
