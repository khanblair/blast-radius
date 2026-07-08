"""Unit tests for the provider-configurable LLM client (agent/narrative/llm_client.py).

No test here makes a real network call or requires a real API key -- provider
routing is verified by monkeypatching each SDK's client class with an inert
fake and inspecting what it was called with; the no-key fallback path is
verified by clearing/blanking the relevant env var.
"""
from __future__ import annotations

import pytest

from agent.narrative.llm_client import (
    PROVIDER_API_KEY_ENV,
    LLMClient,
    LLMNotConfigured,
    build_llm_client,
)


def _clear_all_provider_keys(monkeypatch):
    for env_var in PROVIDER_API_KEY_ENV.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


# --- generate_fn injection (bypasses provider/key resolution entirely) -----


def test_generate_fn_injection_bypasses_key_resolution(monkeypatch):
    _clear_all_provider_keys(monkeypatch)  # no LLM_PROVIDER, no keys at all

    client = build_llm_client(provider="anthropic", generate_fn=lambda system, user: f"FAKE:{system}|{user}")

    assert isinstance(client, LLMClient)
    assert client.provider == "anthropic"
    assert client.generate("sys", "usr") == "FAKE:sys|usr"


def test_generate_fn_injection_defaults_provider_from_env(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    client = build_llm_client(generate_fn=lambda system, user: "ok")

    assert client.provider == "gemini"


# --- no-key fallback path ---------------------------------------------------


def test_raises_not_configured_when_key_missing(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    with pytest.raises(LLMNotConfigured):
        build_llm_client()


def test_raises_not_configured_when_key_blank(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")  # blank/whitespace-only

    with pytest.raises(LLMNotConfigured):
        build_llm_client()


def test_defaults_to_anthropic_when_provider_unset(monkeypatch):
    _clear_all_provider_keys(monkeypatch)

    with pytest.raises(LLMNotConfigured, match="anthropic"):
        build_llm_client()


def test_unknown_provider_raises_value_error(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")

    with pytest.raises(ValueError, match="not-a-real-provider"):
        build_llm_client()


# --- provider routing: each provider wires up the right SDK call shape -----


def test_anthropic_routing_calls_messages_create_with_system_and_user(monkeypatch):
    import anthropic

    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    captured = {}

    class FakeBlock:
        def __init__(self, type_, text):
            self.type = type_
            self.text = text

    class FakeResponse:
        def __init__(self):
            self.content = [FakeBlock("text", "anthropic says hi")]

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)

    client = build_llm_client()
    result = client.generate("system prompt", "user prompt")

    assert result == "anthropic says hi"
    assert captured["api_key"] == "sk-test-key"
    assert captured["system"] == "system prompt"
    assert captured["messages"] == [{"role": "user", "content": "user prompt"}]
    assert client.model == "claude-opus-4-8"


def test_openrouter_routing_uses_openai_sdk_with_openrouter_base_url(monkeypatch):
    import openai

    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")

    captured = {}

    class FakeMessage:
        content = "openrouter says hi"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletionResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletionResponse()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAIClient:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAIClient)

    client = build_llm_client()
    result = client.generate("sys", "usr")

    assert result == "openrouter says hi"
    assert captured["api_key"] == "or-test-key"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["create_kwargs"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def test_deepseek_routing_uses_openai_sdk_with_deepseek_base_url(monkeypatch):
    import openai

    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test-key")

    captured = {}

    class FakeMessage:
        content = "deepseek says hi"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletionResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeCompletionResponse()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAIClient:
        def __init__(self, api_key=None, base_url=None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAIClient)

    client = build_llm_client()
    result = client.generate("sys", "usr")

    assert result == "deepseek says hi"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert client.model == "deepseek-chat"


def test_gemini_routing_uses_google_genai_sdk(monkeypatch):
    from google import genai

    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test-key")

    captured = {}

    class FakeGeminiResponse:
        text = "gemini says hi"

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return FakeGeminiResponse()

    class FakeGenaiClient:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeGenaiClient)

    client = build_llm_client()
    result = client.generate("sys prompt", "usr prompt")

    assert result == "gemini says hi"
    assert captured["api_key"] == "g-test-key"
    assert captured["contents"] == "usr prompt"
    assert captured["config"].system_instruction == "sys prompt"


def test_llm_model_env_override_applies_to_any_provider(monkeypatch):
    import anthropic

    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "claude-custom-model")

    class FakeBlock:
        type = "text"
        text = "hi"

    class FakeResponse:
        content = [FakeBlock()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropicClient)

    client = build_llm_client()

    assert client.model == "claude-custom-model"
