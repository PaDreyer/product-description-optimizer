from __future__ import annotations

__doc__ = """OpenAI adapter, credential, discovery, and request compatibility tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from pdo.config import PdoConfig
from pdo.core.model_discovery import discover_openai_models
from pdo.core.openai_optimizer import OpenAIOptimizer
from pdo.core.provider_defaults import OPENAI_ADDRESS, OPENAI_MODEL
from pdo.core.registry import create_optimizer, list_optimizers
from pdo.exceptions import ConfigError, OptimizationError


def response(text: str, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(output_text=text, status=status)


def api_error(status: int) -> APIStatusError:
    return APIStatusError(
        "test error",
        response=httpx.Response(status, request=httpx.Request("POST", OPENAI_ADDRESS)),
        body=None,
    )


@pytest.fixture
def client() -> MagicMock:
    with patch("openai.OpenAI") as factory:
        yield factory.return_value


def test_optimize_and_validate_use_responses(client: MagicMock) -> None:
    client.responses.create.side_effect = [
        response(" Improved copy. "),
        response('{"approved": false, "suggestion": "Corrected copy."}'),
    ]
    opt = OpenAIOptimizer(api_key="test", model="gpt-5-mini", target_sentences=2)
    assert opt.optimize("P1", "Original copy", {"Brand": "Acme"}) == "Corrected copy."
    generation, validation = client.responses.create.call_args_list
    assert generation.kwargs["model"] == "gpt-5-mini"
    assert generation.kwargs["store"] is False
    assert "temperature" not in generation.kwargs
    assert "2 sentences" in generation.kwargs["instructions"]
    assert "Acme" in generation.kwargs["input"]
    assert "Improved copy." in validation.kwargs["input"]


def test_legacy_text_model_receives_temperature(client: MagicMock) -> None:
    client.responses.create.return_value = response("text")
    opt = OpenAIOptimizer(api_key="test", model="gpt-4.1-mini")
    opt._call_llm(system="system", user="user", temperature=0.1)
    assert client.responses.create.call_args.kwargs["temperature"] == 0.1


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_transient_failures_are_retried(client: MagicMock, status: int) -> None:
    client.responses.create.side_effect = [api_error(status), response("ok")]
    with patch("pdo.core.openai_optimizer.time.sleep") as sleep:
        assert (
            OpenAIOptimizer(api_key="test")._call_llm(system="s", user="u", temperature=0.4) == "ok"
        )
    sleep.assert_called_once_with(2.0)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_failures_are_not_retried(client: MagicMock, status: int) -> None:
    client.responses.create.side_effect = api_error(status)
    with pytest.raises(APIStatusError):
        OpenAIOptimizer(api_key="test")._call_llm(system="s", user="u", temperature=0.4)
    assert client.responses.create.call_count == 1


def test_connection_retries_stop_at_limit(client: MagicMock) -> None:
    client.responses.create.side_effect = APIConnectionError(
        request=httpx.Request("GET", OPENAI_ADDRESS)
    )
    with patch("pdo.core.openai_optimizer.time.sleep") as sleep, pytest.raises(APIConnectionError):
        OpenAIOptimizer(api_key="test")._call_llm(system="s", user="u", temperature=0.4)
    assert client.responses.create.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [2.0, 4.0]


@pytest.mark.parametrize("result", [response("partial", "incomplete"), response("   ")])
def test_incomplete_or_empty_output_is_rejected(client: MagicMock, result: SimpleNamespace) -> None:
    client.responses.create.return_value = result
    with pytest.raises(OptimizationError):
        OpenAIOptimizer(api_key="test")._call_llm(system="s", user="u", temperature=0.4)
    assert client.responses.create.call_count == 1


def test_registry_uses_saved_credentials_and_common_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid")
    config = PdoConfig(
        options={"openai.api_key": "saved-key", "openai.model": "chosen", "target_sentences": "5"}
    )
    with patch("openai.OpenAI") as factory:
        opt = create_optimizer("openai", config)
    assert opt._model == "chosen"
    assert opt._target_sentences == 5
    assert factory.call_args.kwargs["api_key"] == "saved-key"
    assert factory.call_args.kwargs["base_url"] == OPENAI_ADDRESS
    assert factory.call_args.kwargs["max_retries"] == 0


def test_registry_environment_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    with patch("openai.OpenAI") as factory:
        assert create_optimizer("openai")._model == OPENAI_MODEL
    assert factory.call_args.kwargs["api_key"] == "environment-key"
    assert next(o for o in list_optimizers() if o.name == "openai").available


def test_missing_key_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not next(o for o in list_optimizers() if o.name == "openai").available
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        create_optimizer("openai")
    with pytest.raises(ConfigError, match="API key"):
        OpenAIOptimizer(api_key="   ")


def test_sdk_optional() -> None:
    with patch.dict("sys.modules", {"openai": None}):
        info = next(o for o in list_optimizers() if o.name == "openai")
        assert not info.available
        assert "not installed" in info.reason
        with pytest.raises(ConfigError, match="SDK"):
            OpenAIOptimizer(api_key="test")
        with pytest.raises(ConfigError, match="SDK"):
            discover_openai_models("test")


def test_model_discovery_filters_specialized_models(client: MagicMock) -> None:
    ids = [
        "gpt-5-mini",
        "gpt-4.1",
        "gpt-5-mini",
        "gpt-image-1",
        "gpt-4o-audio-preview",
        "text-embedding-3-small",
        "o3",
        "gpt-5-codex",
    ]
    client.__enter__.return_value.models.list.return_value.data = [
        SimpleNamespace(id=id_) for id_ in ids
    ]
    assert discover_openai_models("test") == ["gpt-4.1", "gpt-5-mini", "o3"]
    client.__exit__.assert_called_once()


def test_discovery_missing_key_and_no_text_models(client: MagicMock) -> None:
    with pytest.raises(ConfigError, match="API key"):
        discover_openai_models("")
    client.__enter__.return_value.models.list.return_value.data = [SimpleNamespace(id="whisper-1")]
    with pytest.raises(ConfigError, match="no compatible text models"):
        discover_openai_models("test")


def test_discovery_authentication_error_is_actionable(client: MagicMock) -> None:
    client.__enter__.return_value.models.list.side_effect = api_error(401)
    with pytest.raises(ConfigError, match="HTTP 401"):
        discover_openai_models("test")
