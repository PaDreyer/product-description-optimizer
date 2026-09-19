"""Shared base class for two-step LLM optimizers.

Provides the common optimize → validate flow, shared prompt templates,
and utility methods used by :class:`GeminiOptimizer`, :class:`ZhipuAIOptimizer`,
and :class:`LocalLLMOptimizer`. Subclasses only need to implement
:meth:`_call_llm`.
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from typing import Any

from pdo.core.optimizer import Optimizer

log = logging.getLogger(__name__)

# ── Shared prompt templates ──────────────────────────────────────────

SYSTEM_OPTIMIZE_BASE = """\
You are an expert product copywriter for a B2B office supplies catalogue.
Your task is to rewrite product descriptions so they are:
- Clear, concise, and professional
- SEO-friendly (use relevant keywords naturally)
- Factually accurate — use ONLY information present in the input
- Well-structured with key selling points highlighted

Rules:
- PRESERVE all quantified claims from the original (percentages, capacities,
  measurements, warranty durations, certifications). These are key selling
  points. Example: if the original says "50% weiteres Öffnen" or "5 Jahre
  Garantie", these MUST appear in the output.
- Prioritize unique selling points and differentiating features — what makes
  this product stand out? Certifications, guarantees, capacity, and
  performance data are more valuable than generic feature lists.
- Avoid generic filler phrases like "bietet", "verfügt über", "ermöglicht".
  Instead, describe features with concrete benefits and action.
- Do NOT invent features, specifications, or claims that are not in the input.
- Do NOT add superlatives ("best", "leading", "unmatched") unless they are in
  the original description.
- Keep the tone professional, engaging, and informative.
- Vary your sentence structure. Do not start consecutive sentences the same way
  (e.g. avoid starting every sentence with the brand name or an article).
- Do NOT use emoji or special symbols.
- Reproduce brand names, product names, and attribute values EXACTLY as given —
  do not paraphrase, abbreviate, or expand them.
- If the context lists a value such as "6 Neonfarben", state it as-is. Do NOT
  enumerate or invent specific sub-values (e.g. do not list colour names).
- If the original description is empty, create one based purely on the context
  fields provided.
- Respond with ONLY the optimized description text. No headers, no markdown,
  no explanations.
- Do NOT use line breaks or newlines. The entire output MUST be a single
  continuous paragraph on one line.
- Do NOT use bullet points or lists.
- Write in the SAME LANGUAGE as the original description (or context variables,
  if description is empty).
- Pay attention to correct grammar, especially gendered articles and cases.
- Aim for around {target_sentences} sentences, prioritizing natural flow and
  readability over hitting an exact count.
{style_block}"""

USER_OPTIMIZE = """\
Original Description:
{description}

Context:
{context}

{empty_warning}Rewrite the description above into a compelling, single-paragraph product
description. Keep all quantified claims (percentages, capacities, warranty
durations, certifications). Aim for around {target_sentences} sentences.
"""

SYSTEM_VALIDATE = """\
You are a quality-assurance reviewer for product descriptions.
Your job is to compare an optimized description against the original product
data and determine whether the optimized version is accurate and complete.

Check for:
1. **False promises** — claims not supported by the original data
2. **Hallucinated features** — specifications or properties that do not appear
   in the original data
3. **Misleading statements** — exaggerations or implications not backed by facts
4. **Dropped key data** — important quantified claims from the original that
   were omitted (e.g. percentages, capacities, warranty periods,
   certifications like "Blauer Engel"). Flag as issue if significant data
   was lost.
5. **Language consistency** — the optimized text should be in the same language
   as the original (or context)
6. **Grammar errors** — check for correct grammar, especially gendered articles
   and noun cases (e.g. in German: "ein Griffloch" not "einen Griffloch")
7. **Brand / product name errors** — brand names must be reproduced exactly;
   any misspelling or paraphrase is an error
8. **Invented specifics** — if an attribute says e.g. "6 Neonfarben", the text
   must NOT list individual colour names or other sub-values not in the input
9. **Emoji or formatting** — no emoji, special symbols, line breaks, or bullet
   points are allowed

Respond in JSON format with exactly this structure:
{{"approved": true/false, "issues": ["issue1", "issue2", ...], "suggestion": "..."}}

- If approved is true, issues should be an empty list [] and suggestion should
  be "".
- If approved is false, list EVERY issue found. You MUST provide a corrected
  version in the "suggestion" field that fixes ALL issues while keeping the
  improved style. The suggestion MUST be a single continuous paragraph with
  no line breaks.
"""

USER_VALIDATE = """\
Original Product Data:
- Product ID: {product_id}
- Original Description: {description}
- Context attributes (must be reproduced exactly, not expanded):
{context}

Optimized Description:
{optimized}

Is this optimized description accurate and free of errors? Check brand name
spelling, attribute values, and absence of emoji carefully.
"""

# ── Configuration defaults ───────────────────────────────────────────

DEFAULT_TARGET_SENTENCES = 3
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds


class BaseLLMOptimizer(Optimizer):
    """Abstract base for two-step LLM optimizers (optimize → validate).

    Subclasses must implement :meth:`_call_llm`.
    """

    def __init__(
        self,
        *,
        optimize_temperature: float = 0.4,
        validate_temperature: float = 0.1,
        max_retries: int = MAX_RETRIES,
        target_sentences: int = DEFAULT_TARGET_SENTENCES,
        style_instructions: str | None = None,
    ) -> None:
        self._optimize_temperature = optimize_temperature
        self._validate_temperature = validate_temperature
        self._max_retries = max_retries
        self._target_sentences = target_sentences
        style_block = (
            f"\n# Additional Instructions\n{style_instructions}\n" if style_instructions else ""
        )
        self._system_optimize = SYSTEM_OPTIMIZE_BASE.format(
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
        """Optimize a product description using a two-step LLM flow.

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
        optimized = self._call_llm(
            system=self._system_optimize,
            user=USER_OPTIMIZE.format(
                description=description or "(empty)",
                context=ctx_str,
                empty_warning=empty_warning,
                target_sentences=self._target_sentences,
            ),
            temperature=self._optimize_temperature,
        )
        log.info("Step 1 complete for %s: generated %d chars", product_id, len(optimized))

        # Step 2: Validate
        validation_raw = self._call_llm(
            system=SYSTEM_VALIDATE,
            user=USER_VALIDATE.format(
                product_id=product_id,
                description=description or "(empty)",
                context=ctx_str,
                optimized=optimized,
            ),
            temperature=self._validate_temperature,
        )

        validated = self._parse_validation(validation_raw, optimized)
        log.info("Step 2 complete for %s: approved=%s", product_id, validated == optimized)

        return validated

    # ── Abstract method ──────────────────────────────────────────────

    @abstractmethod
    def _call_llm(self, *, system: str, user: str, temperature: float) -> str:
        """Call the LLM backend with retry logic. Subclasses implement this."""

    def _retry_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for a given attempt number."""
        return RETRY_BASE_DELAY * (2 ** (attempt - 1))

    # ── Shared utilities ─────────────────────────────────────────────

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
