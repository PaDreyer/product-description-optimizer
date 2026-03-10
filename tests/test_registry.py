"""Tests for the optimizer registry (``pdo.core.registry``)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pdo.core.registry import (
    OptimizerInfo,
    create_optimizer,
    get_default_optimizer_name,
    list_optimizers,
)


class TestListOptimizers:
    def test_returns_known_backends(self) -> None:
        optimizers = list_optimizers()
        names = [o.name for o in optimizers]
        assert "dummy" in names
        assert "gemini" in names

    def test_dummy_always_available(self) -> None:
        optimizers = list_optimizers()
        dummy = next(o for o in optimizers if o.name == "dummy")
        assert dummy.available is True

    @patch.dict("sys.modules", {"google.genai": None})
    def test_gemini_unavailable_without_sdk(self) -> None:
        optimizers = list_optimizers()
        gemini = next(o for o in optimizers if o.name == "gemini")
        assert gemini.available is False
        assert "not installed" in gemini.reason

    def test_gemini_unavailable_without_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            optimizers = list_optimizers()
            gemini = next(o for o in optimizers if o.name == "gemini")
            assert gemini.available is False
            assert "GEMINI_API_KEY not set" in gemini.reason

    def test_returns_optimizer_info_instances(self) -> None:
        for opt in list_optimizers():
            assert isinstance(opt, OptimizerInfo)


class TestCreateOptimizer:
    def test_create_dummy(self) -> None:
        from pdo.core.optimizer import DummyOptimizer

        opt = create_optimizer("dummy")
        assert isinstance(opt, DummyOptimizer)

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown optimizer"):
            create_optimizer("nonexistent")

    def test_gemini_without_key_raises(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API key"):
                create_optimizer("gemini")

    @patch.dict("sys.modules", {"pdo.core.gemini_optimizer": None})
    def test_gemini_without_sdk_raises(self) -> None:
        with pytest.raises(ValueError, match="requires the google-genai package"):
            create_optimizer("gemini")


class TestGetDefaultOptimizerName:
    def test_without_key_returns_dummy(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            name = get_default_optimizer_name()
            # Without GEMINI_API_KEY, should fall back to dummy
            assert name == "dummy"

    def test_with_key_and_sdk(self) -> None:
        """When both the SDK and key are present, default should be gemini."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            assert get_default_optimizer_name() == "gemini"

