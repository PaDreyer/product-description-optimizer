"""Tests for the ZhipuAI optimizer (``pdo.core.zhipuai_optimizer``).

These tests mock the ZhipuAI API so they run without an API key.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pdo.core.zhipuai_optimizer import ZhipuAIOptimizer


@pytest.fixture()
def mock_zhipuai_sdk():
    """Patch ``zhipuai`` so no real API call is made."""
    with patch("zhipuai.ZhipuAI") as mock_zhipuai_module:
        client_instance = MagicMock()
        mock_zhipuai_module.return_value = client_instance
        yield client_instance


def _make_response(text: str) -> MagicMock:
    """Create a mock ZhipuAI response with the given text."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    return resp


class TestZhipuAIOptimizerInit:
    def test_raises_without_api_key(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="API key"),
        ):
            ZhipuAIOptimizer(api_key="")

    def test_creates_with_api_key(self, mock_zhipuai_sdk) -> None:
        opt = ZhipuAIOptimizer(api_key="test-key")
        assert opt._model == "glm-4"


class TestPromptContent:
    """Verify the prompts sent to ZhipuAI contain the right content."""

    def _make_optimizer_wired(self, mock_zhipuai_sdk, **kwargs):
        opt = ZhipuAIOptimizer(api_key="test-key", **kwargs)
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            _make_response("Good description."),
            _make_response('{"approved": true, "issues": [], "suggestion": ""}'),
        ]
        return opt

    def test_target_sentences_in_system_prompt(self, mock_zhipuai_sdk) -> None:
        opt = self._make_optimizer_wired(mock_zhipuai_sdk, target_sentences=5)
        opt.optimize("P001", "Some desc", {})
        first_call = mock_zhipuai_sdk.chat.completions.create.call_args_list[0]
        system_msg = first_call.kwargs["messages"][0]["content"]
        assert "5 sentence" in system_msg

    def test_style_instructions_in_system_prompt(self, mock_zhipuai_sdk) -> None:
        opt = self._make_optimizer_wired(
            mock_zhipuai_sdk, style_instructions="Start with the main benefit."
        )
        opt.optimize("P001", "Some desc", {})
        first_call = mock_zhipuai_sdk.chat.completions.create.call_args_list[0]
        system_msg = first_call.kwargs["messages"][0]["content"]
        assert "Start with the main benefit." in system_msg

    def test_product_id_not_in_optimize_user_prompt(self, mock_zhipuai_sdk) -> None:
        opt = self._make_optimizer_wired(mock_zhipuai_sdk)
        opt.optimize("SECRET_ID_XYZ", "Some desc", {})
        first_call = mock_zhipuai_sdk.chat.completions.create.call_args_list[0]
        user_msg = first_call.kwargs["messages"][1]["content"]
        assert "SECRET_ID_XYZ" not in user_msg

    def test_no_style_instructions_by_default(self, mock_zhipuai_sdk) -> None:
        opt = self._make_optimizer_wired(mock_zhipuai_sdk)
        opt.optimize("P001", "Some desc", {})
        first_call = mock_zhipuai_sdk.chat.completions.create.call_args_list[0]
        system_msg = first_call.kwargs["messages"][0]["content"]
        assert "Additional Instructions" not in system_msg


class TestTwoStepFlow:
    def test_approved_returns_optimized(self, mock_zhipuai_sdk) -> None:
        """Step 1 optimizes, step 2 approves → return optimized text."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            _make_response("Optimized description here."),
            _make_response('{"approved": true, "issues": [], "suggestion": ""}'),
        ]

        opt = ZhipuAIOptimizer(api_key="test-key")
        result = opt.optimize("P001", "Original desc", {"brand": "TestBrand"})
        assert result == "Optimized description here."
        assert mock_zhipuai_sdk.chat.completions.create.call_count == 2

    def test_rejected_returns_suggestion(self, mock_zhipuai_sdk) -> None:
        """Step 1 optimizes, step 2 rejects → return corrected suggestion."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            _make_response("Optimized but with lies."),
            _make_response(
                '{"approved": false, '
                '"issues": ["Claims product is waterproof but original says water-resistant"], '
                '"suggestion": "Corrected version without lies."}'
            ),
        ]

        opt = ZhipuAIOptimizer(api_key="test-key")
        result = opt.optimize("P002", "Water-resistant pen", {"brand": "PenCo"})
        assert result == "Corrected version without lies."

    def test_rejected_no_suggestion_keeps_optimized(self, mock_zhipuai_sdk) -> None:
        """If validation fails but has no suggestion, keep original optimized."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            _make_response("Optimized text."),
            _make_response('{"approved": false, "issues": ["minor issue"], "suggestion": ""}'),
        ]

        opt = ZhipuAIOptimizer(api_key="test-key")
        result = opt.optimize("P003", "Desc", {})
        assert result == "Optimized text."


class TestValidationParsing:
    def test_handles_markdown_fences(self, mock_zhipuai_sdk) -> None:
        """JSON wrapped in ```json fences should still parse."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            _make_response("Optimized."),
            _make_response('```json\n{"approved": true, "issues": [], "suggestion": ""}\n```'),
        ]

        opt = ZhipuAIOptimizer(api_key="test-key")
        result = opt.optimize("P004", "Desc", {})
        assert result == "Optimized."

    def test_handles_malformed_json(self, mock_zhipuai_sdk) -> None:
        """If validation response isn't valid JSON, fall back to optimized."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            _make_response("Good optimized text."),
            _make_response("Not valid JSON at all"),
        ]

        opt = ZhipuAIOptimizer(api_key="test-key")
        result = opt.optimize("P005", "Desc", {})
        assert result == "Good optimized text."


class TestContextFormatting:
    def test_format_context_none(self) -> None:
        assert ZhipuAIOptimizer._format_context(None) == "(none)"

    def test_format_context_dict(self) -> None:
        result = ZhipuAIOptimizer._format_context({"Brand": "X", "Color": "Blue"})
        assert "- Brand: X" in result
        assert "- Color: Blue" in result

    def test_format_context_skips_empty(self) -> None:
        result = ZhipuAIOptimizer._format_context({"Brand": "X", "Empty": ""})
        assert "- Brand: X" in result
        assert "Empty" not in result


class TestRetryLogic:
    def test_retries_on_failure(self, mock_zhipuai_sdk) -> None:
        """Should retry and succeed on second attempt."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = [
            Exception("API transient error"),
            _make_response("Optimized on retry."),
            _make_response('{"approved": true, "issues": [], "suggestion": ""}'),
        ]

        opt = ZhipuAIOptimizer(api_key="test-key", max_retries=2)

        with patch("pdo.core.zhipuai_optimizer.time.sleep"):
            result = opt.optimize("P006", "Desc", {})

        assert result == "Optimized on retry."

    def test_raises_after_all_retries_exhausted(self, mock_zhipuai_sdk) -> None:
        """Should raise after all retries are used."""
        mock_zhipuai_sdk.chat.completions.create.side_effect = Exception("Persistent error")

        opt = ZhipuAIOptimizer(api_key="test-key", max_retries=2)

        with (
            patch("pdo.core.zhipuai_optimizer.time.sleep"),
            pytest.raises(Exception, match="Persistent error"),
        ):
            opt.optimize("P007", "Desc", {})
