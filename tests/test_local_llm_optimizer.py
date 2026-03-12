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


def test_optimize_success(mock_openai_client):
    """Test a successful optimize flow where step 2 (validation) approves it."""
    optimizer = LocalLLMOptimizer(address="http://127.0.0.1:11434/v1")

    # Setup the mock to return responses for both step 1 and step 2
    mock_choices = MagicMock()
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
