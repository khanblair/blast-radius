"""Provider-configurable LLM client for narrative generation (spec §7: "a
thin, provider-configurable client -- Anthropic Claude by default, with
OpenRouter, DeepSeek, and Gemini supported as alternates").

Two seams for testability, matching Phase 2's no-mocking-what-you-don't-have-to
discipline:
  1. `generate_fn` injection on `build_llm_client()` bypasses provider/key
     resolution entirely -- unit tests substitute a fake callable, no SDK
     imports or network calls involved.
  2. The per-provider `_call_*` functions each take an already-constructed
     SDK client as a plain parameter, so tests can verify request/response
     handling against an inert fake client object -- no real API key, no
     patched-in fake module, no network access.

If the configured provider has no API key set, `build_llm_client()` raises
`LLMNotConfigured`. The narrative builder (agent/narrative/builder.py) catches
this and falls back to a deterministic template -- this is required for the
demo (no key is configured in this project's .env) and for tests to run
without live API access, so it's a first-class path, not an afterthought.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from dotenv import load_dotenv

load_dotenv()

PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# Overridable per run via LLM_MODEL -- narrative generation is one short
# completion per affected asset, not latency/cost-sensitive enough to need
# more than a single sane default per provider.
PROVIDER_DEFAULT_MODEL = {
    "anthropic": "claude-opus-4-8",
    "openrouter": "anthropic/claude-3.5-sonnet",
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash",
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class LLMNotConfigured(RuntimeError):
    """Raised when the selected provider has no API key set. Callers (the
    narrative builder) must catch this and fall back to a template -- a
    missing key should never crash or hang the pipeline."""


@dataclass
class LLMClient:
    provider: str
    model: str
    _generate: Callable[[str, str], str]

    def generate(self, system: str, user: str) -> str:
        """Returns the model's text response to a (system, user) prompt pair."""
        return self._generate(system, user)


def _call_anthropic(client, model: str, system: str, user: str) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return next(b.text for b in response.content if b.type == "text")


def _call_openai_compatible(client, model: str, system: str, user: str) -> str:
    """Shared by OpenRouter and DeepSeek -- both are OpenAI-API-compatible,
    reached via the `openai` package pointed at a different `base_url`."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content


def _call_gemini(client, model: str, system: str, user: str) -> str:
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return response.text


def build_llm_client(
    provider: str | None = None, generate_fn: Callable[[str, str], str] | None = None
) -> LLMClient:
    """Resolves `LLM_PROVIDER` (or the explicit `provider` override) and
    returns a ready `LLMClient`.

    Pass `generate_fn` to substitute a fake response in tests -- it bypasses
    provider/key resolution and SDK construction entirely, so unit tests
    never touch the network or need a real API key.

    Raises `LLMNotConfigured` if the resolved provider's API key is blank or
    missing. Raises `ValueError` if `LLM_PROVIDER` names a provider this
    client doesn't know how to route.
    """
    resolved_provider = (provider or os.environ.get("LLM_PROVIDER", "anthropic")).strip().lower()

    if generate_fn is not None:
        model = os.environ.get("LLM_MODEL", PROVIDER_DEFAULT_MODEL.get(resolved_provider, ""))
        return LLMClient(provider=resolved_provider, model=model, _generate=generate_fn)

    if resolved_provider not in PROVIDER_API_KEY_ENV:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{resolved_provider}' -- expected one of {sorted(PROVIDER_API_KEY_ENV)}"
        )

    api_key_env = PROVIDER_API_KEY_ENV[resolved_provider]
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise LLMNotConfigured(
            f"No API key configured for LLM_PROVIDER='{resolved_provider}' (expected ${api_key_env})"
        )

    model = os.environ.get("LLM_MODEL", PROVIDER_DEFAULT_MODEL[resolved_provider])

    if resolved_provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        return LLMClient(
            provider=resolved_provider,
            model=model,
            _generate=lambda system, user: _call_anthropic(client, model, system, user),
        )

    if resolved_provider == "openrouter":
        import openai

        client = openai.OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
        return LLMClient(
            provider=resolved_provider,
            model=model,
            _generate=lambda system, user: _call_openai_compatible(client, model, system, user),
        )

    if resolved_provider == "deepseek":
        import openai

        client = openai.OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        return LLMClient(
            provider=resolved_provider,
            model=model,
            _generate=lambda system, user: _call_openai_compatible(client, model, system, user),
        )

    if resolved_provider == "gemini":
        from google import genai

        client = genai.Client(api_key=api_key)
        return LLMClient(
            provider=resolved_provider,
            model=model,
            _generate=lambda system, user: _call_gemini(client, model, system, user),
        )

    raise ValueError(f"Unhandled LLM_PROVIDER '{resolved_provider}'")  # pragma: no cover
