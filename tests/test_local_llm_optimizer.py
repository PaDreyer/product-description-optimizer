import json
from unittest.mock import MagicMock, patch

import pytest

from pdo.core.local_llm_optimizer import LocalLLMOptimizer


@pytest.fixture
def mock_openai_client():
    with patch("openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        yield mock_client


def test_init_missing_address():
    with pytest.raises(ValueError, match="address must be provided"):
        LocalLLMOptimizer(address="")


class TestPromptContent:
    """Verify the prompts sent to the LLM contain the right content."""

    def _make_optimizer(self, mock_client, **kwargs):
        opt = LocalLLMOptimizer(address="http://127.0.0.1:11434/v1", **kwargs)
        # Wire up generic success responses
        ok_step1 = MagicMock()
        ok_step1.choices = [MagicMock()]
        ok_step1.choices[0].message.content = "Good description."
        ok_step2 = MagicMock()
        ok_step2.choices = [MagicMock()]
        ok_step2.choices[0].message.content = '{"approved": true, "issues": [], "suggestion": ""}'
        mock_client.chat.completions.create.side_effect = [ok_step1, ok_step2]
        return opt

    def test_target_sentences_in_system_prompt(self, mock_openai_client):
        """The target_sentences value must appear in the system prompt."""
        opt = self._make_optimizer(mock_openai_client, target_sentences=5)
        opt.optimize("P001", "Some desc", {})
        first_call_args = mock_openai_client.chat.completions.create.call_args_list[0]
        system_msg = first_call_args.kwargs["messages"][0]["content"]
        assert "5 sentence" in system_msg

    def test_style_instructions_in_system_prompt(self, mock_openai_client):
        """Custom style_instructions must be appended to the system prompt."""
        opt = self._make_optimizer(
            mock_openai_client, style_instructions="Start with the main benefit."
        )
        opt.optimize("P001", "Some desc", {})
        first_call_args = mock_openai_client.chat.completions.create.call_args_list[0]
        system_msg = first_call_args.kwargs["messages"][0]["content"]
        assert "Start with the main benefit." in system_msg

    def test_product_id_not_in_optimize_user_prompt(self, mock_openai_client):
        """The product ID must NOT appear in the step-1 user message."""
        opt = self._make_optimizer(mock_openai_client)
        opt.optimize("SECRET_ID_XYZ", "Some desc", {})
        first_call_args = mock_openai_client.chat.completions.create.call_args_list[0]
        user_msg = first_call_args.kwargs["messages"][1]["content"]
        assert "SECRET_ID_XYZ" not in user_msg

    def test_no_style_instructions_by_default(self, mock_openai_client):
        """If no style_instructions given, section must not appear."""
        opt = self._make_optimizer(mock_openai_client)
        opt.optimize("P001", "Some desc", {})
        first_call_args = mock_openai_client.chat.completions.create.call_args_list[0]
        system_msg = first_call_args.kwargs["messages"][0]["content"]
        assert "Additional Instructions" not in system_msg

def test_optimize_success(mock_openai_client):
    """Test a successful optimize flow where step 2 (validation) approves it."""
    optimizer = LocalLLMOptimizer(address="http://127.0.0.1:11434/v1")

    # Setup the mock to return responses for both step 1 and step 2
    mock_msg1 = MagicMock()
    mock_msg1.message.content = "Optimized text here."

    mock_msg2 = MagicMock()
    mock_msg2.message.content = '{"approved": true, "issues": [], "suggestion": ""}'

    # First call returns optimized text, second returns validation JSON
    mock_choices_1 = MagicMock()
    mock_choices_1.choices = [mock_msg1]
    mock_choices_2 = MagicMock()
    mock_choices_2.choices = [mock_msg2]

    # Assign side_effect to create()
    mock_openai_client.chat.completions.create.side_effect = [
        mock_choices_1,
        mock_choices_2,
    ]

    result = optimizer.optimize("123", "Old description", {"Brand": "Acme"})
    assert result == "Optimized text here."
    assert mock_openai_client.chat.completions.create.call_count == 2



def test_optimize_validation_failure_uses_suggestion(mock_openai_client):
    """Test when validation fails and returns a corrected suggestion."""
    optimizer = LocalLLMOptimizer(address="http://127.0.0.1:1234/v1")

    mock_msg1 = MagicMock()
    mock_msg1.message.content = "Optimized but hallucinated features."
    
    mock_msg2 = MagicMock()
    mock_msg2.message.content = '{"approved": false, "issues": ["hallucination"], "suggestion": "Corrected text."}'
    
    mock_choices_1 = MagicMock()
    mock_choices_1.choices = [mock_msg1]
    mock_choices_2 = MagicMock()
    mock_choices_2.choices = [mock_msg2]

    mock_openai_client.chat.completions.create.side_effect = [
        mock_choices_1,
        mock_choices_2,
    ]

    result = optimizer.optimize("123", "Old description")
    assert result == "Corrected text."
