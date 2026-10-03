"""
Tests for the LLM provider fallback (primary GROQ -> Sarvam on failure).

Covers:
  - FallbackLLMProvider: primary-first behaviour, fallback on primary
    failure, honest error when both fail, structured-output delegation
  - SarvamProvider: request shape (model, messages, JSON mode) and
    error propagation, using an injected fake client (no network)
  - get_llm_provider factory: wraps with the Sarvam fallback only when
    SARVAM_API_KEY is set
"""
from unittest.mock import patch

import pytest

from app.llm.base import LLMProvider
from app.llm.fallback import FallbackLLMProvider
from app.llm.groq_provider import GroqProvider
from app.llm.sarvam_provider import SarvamProvider


class _Stub(LLMProvider):
    """Configurable stub provider recording call counts."""

    def __init__(self, reply: str = "stub", raise_exc: Exception | None = None):
        self.reply = reply
        self.raise_exc = raise_exc
        self.calls = 0
        self.last_prompts: tuple[str, str] | None = None

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.last_prompts = (system_prompt, user_prompt)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.reply


class _StructuredStub(_Stub):
    def supports_structured_output(self) -> bool:
        return True


class TestFallbackLLMProvider:
    def test_primary_used_when_it_succeeds(self):
        primary = _Stub(reply="from-primary")
        fallback = _Stub(reply="from-fallback")
        out = FallbackLLMProvider(primary, fallback).generate("sys", "usr")
        assert out == "from-primary"
        assert primary.calls == 1
        assert fallback.calls == 0
        assert primary.last_prompts == ("sys", "usr")

    def test_fallback_used_when_primary_fails(self):
        primary = _Stub(raise_exc=RuntimeError("groq down"))
        fallback = _Stub(reply="from-fallback")
        out = FallbackLLMProvider(primary, fallback, fallback_name="sarvam").generate(
            "sys", "usr"
        )
        assert out == "from-fallback"
        assert primary.calls == 1
        assert fallback.calls == 1
        assert fallback.last_prompts == ("sys", "usr")

    def test_both_fail_raises_honest_error_with_cause(self):
        primary = _Stub(raise_exc=RuntimeError("groq down"))
        fallback = _Stub(raise_exc=ConnectionError("sarvam down"))
        provider = FallbackLLMProvider(primary, fallback, fallback_name="sarvam")
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate("sys", "usr")
        message = str(exc_info.value)
        assert "sarvam" in message.lower()
        assert "sarvam down" in message
        # primary exception preserved as the explicit cause
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert "groq down" in str(exc_info.value.__cause__)

    def test_supports_structured_output_delegates_to_primary(self):
        primary = _Stub(reply="x")             # base default: False
        fallback = _StructuredStub(reply="y")  # True
        provider = FallbackLLMProvider(primary, fallback)
        assert provider.supports_structured_output() is False

        primary_structured = _StructuredStub(reply="x")
        provider = FallbackLLMProvider(primary_structured, _Stub(reply="y"))
        assert provider.supports_structured_output() is True


class _FakeMsg:
    content = '{"answer": "ok"}'


class _FakeChoice:
    message = _FakeMsg()


class _FakeResponse:
    choices = [_FakeChoice()]


class _FakeChat:
    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.kwargs: dict | None = None

    def completions(self, **kwargs):
        self.kwargs = kwargs
        if self.exc is not None:
            raise self.exc
        return _FakeResponse()


class _FakeClient:
    def __init__(self, exc: Exception | None = None):
        self.chat = _FakeChat(exc)


class TestSarvamProvider:
    def test_generate_returns_content_with_expected_request_shape(self):
        provider = SarvamProvider(api_key="k", model="sarvam-105b-conversations")
        provider._client = _FakeClient()

        out = provider.generate("system text", "user text")

        assert out == '{"answer": "ok"}'
        kwargs = provider._client.chat.kwargs
        assert kwargs["model"] == "sarvam-105b-conversations"
        assert kwargs["messages"] == [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "user text"},
        ]
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["reasoning_effort"] is None

    def test_api_error_propagates(self):
        provider = SarvamProvider(api_key="k")
        provider._client = _FakeClient(exc=ConnectionError("boom"))
        with pytest.raises(ConnectionError):
            provider.generate("sys", "usr")

    def test_supports_structured_output(self):
        assert SarvamProvider(api_key="k").supports_structured_output() is True


class _FakeSettings:
    def __init__(self, sarvam_key: str):
        self.llm_provider = "groq"
        self.llm_model = "openai/gpt-oss-120b"
        self.groq_api_key = "gsk-test"
        self.openai_api_key = ""
        self.gemini_api_key = ""
        self.sarvam_api_key = sarvam_key
        self.sarvam_model = "sarvam-105b-conversations"


class TestProviderFactory:
    def teardown_method(self):
        from app.llm.provider import get_llm_provider
        get_llm_provider.cache_clear()

    def test_factory_wraps_primary_with_sarvam_fallback(self):
        from app.llm.provider import get_llm_provider

        get_llm_provider.cache_clear()
        with patch(
            "app.llm.provider.get_settings",
            return_value=_FakeSettings(sarvam_key="sk-test"),
        ):
            provider = get_llm_provider()

        assert isinstance(provider, FallbackLLMProvider)
        assert isinstance(provider.primary, GroqProvider)
        assert isinstance(provider.fallback, SarvamProvider)
        assert provider._fallback_name == "sarvam"

    def test_factory_returns_primary_when_no_sarvam_key(self):
        from app.llm.provider import get_llm_provider

        get_llm_provider.cache_clear()
        with patch(
            "app.llm.provider.get_settings",
            return_value=_FakeSettings(sarvam_key=""),
        ):
            provider = get_llm_provider()

        assert isinstance(provider, GroqProvider)

    def test_factory_does_not_wrap_when_key_is_whitespace(self):
        from app.llm.provider import get_llm_provider

        get_llm_provider.cache_clear()
        with patch(
            "app.llm.provider.get_settings",
            return_value=_FakeSettings(sarvam_key="   "),
        ):
            provider = get_llm_provider()

        assert isinstance(provider, GroqProvider)


class _ChoiceSettings:
    def __init__(self, sarvam_key: str):
        self.sarvam_api_key = sarvam_key
        self.sarvam_model = "sarvam-105b-conversations"


class TestGetLLMProviderFor:
    """Chat provider toggle: None/groq -> default chain, sarvam -> strict."""

    def test_none_and_groq_use_the_default_chain(self, monkeypatch):
        from app.llm import provider as provider_module

        sentinel = object()
        monkeypatch.setattr(provider_module, "get_llm_provider", lambda: sentinel)
        assert provider_module.get_llm_provider_for(None) is sentinel
        assert provider_module.get_llm_provider_for("groq") is sentinel

    def test_sarvam_returns_strict_sarvam_provider(self, monkeypatch):
        from app.llm import provider as provider_module

        monkeypatch.setattr(
            provider_module, "get_settings", lambda: _ChoiceSettings("sk-test")
        )
        chosen = provider_module.get_llm_provider_for("sarvam")
        assert isinstance(chosen, SarvamProvider)

    def test_sarvam_without_key_raises(self, monkeypatch):
        from app.llm import provider as provider_module

        monkeypatch.setattr(
            provider_module, "get_settings", lambda: _ChoiceSettings("")
        )
        with pytest.raises(ValueError, match="SARVAM_API_KEY"):
            provider_module.get_llm_provider_for("sarvam")

    def test_unknown_choice_raises(self):
        from app.llm.provider import get_llm_provider_for

        with pytest.raises(ValueError, match="Unknown LLM choice"):
            get_llm_provider_for("openai")
