"""Tests for the Gemini optimizer (``pdo.core.gemini_optimizer``).

These tests mock the Gemini API so they run without an API key.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pdo.core.gemini_optimizer import GeminiOptimizer


@pytest.fixture()
def mock_client():
    """Patch ``genai.Client`` so no real API call is made."""
    with patch("pdo.core.gemini_optimizer.genai.Client") as mock_cls:
        client_instance = MagicMock()
        mock_cls.return_value = client_instance
        yield client_instance


def _make_response(text: str) -> MagicMock:
    """Create a mock Gemini response with the given text."""
    resp = MagicMock()
    resp.text = text
    return resp


class TestGeminiOptimizerInit:
    def test_raises_without_api_key(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="API key"),
        ):
            GeminiOptimizer(api_key="")

    def test_creates_with_api_key(self, mock_client) -> None:
        opt = GeminiOptimizer(api_key="test-key")
        assert opt._model == "gemini-2.0-flash"


class TestTwoStepFlow:
    def test_approved_returns_optimized(self, mock_client) -> None:
        """Step 1 optimizes, step 2 approves → return optimized text."""
        mock_client.models.generate_content.side_effect = [
            _make_response("Optimized description here."),
            _make_response('{"approved": true, "issues": [], "suggestion": ""}'),
        ]

        opt = GeminiOptimizer(api_key="test-key")
        result = opt.optimize("P001", "Original desc", {"brand": "TestBrand"})
        assert result == "Optimized description here."
        assert mock_client.models.generate_content.call_count == 2

    def test_rejected_returns_suggestion(self, mock_client) -> None:
        """Step 1 optimizes, step 2 rejects → return corrected suggestion."""
        mock_client.models.generate_content.side_effect = [
            _make_response("Optimized but with lies."),
            _make_response(
                '{"approved": false, '
                '"issues": ["Claims product is waterproof but original says water-resistant"], '
                '"suggestion": "Corrected version without lies."}'
            ),
        ]

        opt = GeminiOptimizer(api_key="test-key")
        result = opt.optimize("P002", "Water-resistant pen", {"brand": "PenCo"})
        assert result == "Corrected version without lies."

    def test_rejected_no_suggestion_keeps_optimized(self, mock_client) -> None:
        """If validation fails but has no suggestion, keep original optimized."""
        mock_client.models.generate_content.side_effect = [
            _make_response("Optimized text."),
            _make_response('{"approved": false, "issues": ["minor issue"], "suggestion": ""}'),
        ]

        opt = GeminiOptimizer(api_key="test-key")
        result = opt.optimize("P003", "Desc", {})
        assert result == "Optimized text."


class TestValidationParsing:
    def test_handles_markdown_fences(self, mock_client) -> None:
        """JSON wrapped in ```json fences should still parse."""
        mock_client.models.generate_content.side_effect = [
            _make_response("Optimized."),
            _make_response('```json\n{"approved": true, "issues": [], "suggestion": ""}\n```'),
        ]

        opt = GeminiOptimizer(api_key="test-key")
        result = opt.optimize("P004", "Desc", {})
        assert result == "Optimized."

    def test_handles_malformed_json(self, mock_client) -> None:
        """If validation response isn't valid JSON, fall back to optimized."""
        mock_client.models.generate_content.side_effect = [
            _make_response("Good optimized text."),
            _make_response("Not valid JSON at all"),
        ]

        opt = GeminiOptimizer(api_key="test-key")
        result = opt.optimize("P005", "Desc", {})
        assert result == "Good optimized text."


class TestContextFormatting:
    def test_format_context_none(self) -> None:
        assert GeminiOptimizer._format_context(None) == "(none)"

    def test_format_context_dict(self) -> None:
        result = GeminiOptimizer._format_context({"Brand": "X", "Color": "Blue"})
        assert "- Brand: X" in result
        assert "- Color: Blue" in result

    def test_format_context_skips_empty(self) -> None:
        result = GeminiOptimizer._format_context({"Brand": "X", "Empty": ""})
        assert "- Brand: X" in result
        assert "Empty" not in result


class TestRetryLogic:
    def test_retries_on_failure(self, mock_client) -> None:
        """Should retry and succeed on second attempt."""
        mock_client.models.generate_content.side_effect = [
            Exception("API transient error"),
            _make_response("Optimized on retry."),
            _make_response('{"approved": true, "issues": [], "suggestion": ""}'),
        ]

        opt = GeminiOptimizer(api_key="test-key", max_retries=2)

        with patch("pdo.core.gemini_optimizer.time.sleep"):
            result = opt.optimize("P006", "Desc", {})

        assert result == "Optimized on retry."

    def test_raises_after_all_retries_exhausted(self, mock_client) -> None:
        """Should raise after all retries are used."""
        mock_client.models.generate_content.side_effect = Exception("Persistent error")

        opt = GeminiOptimizer(api_key="test-key", max_retries=2)

        with (
            patch("pdo.core.gemini_optimizer.time.sleep"),
            pytest.raises(Exception, match="Persistent error"),
        ):
            opt.optimize("P007", "Desc", {})
