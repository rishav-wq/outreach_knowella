"""Single LLM entry point. Provider/model is config, never hardcoded.

Every provider is reached through the OpenAI-compatible API surface, so switching
Gemini <-> Groq <-> OpenAI is just base_url + model + key. Default is Gemini
(gemini-2.5-flash): this is batch/offline work, so Groq's speed advantage buys us
nothing — we optimize purely for quality-per-dollar.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from openai import OpenAI

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GOOGLE_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "openai": {
        "base_url": None,  # SDK default
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
}

DEFAULT_PROVIDER = "gemini"


@dataclass
class ModelSpec:
    provider: str = DEFAULT_PROVIDER
    model: str | None = None  # falls back to the provider default

    @classmethod
    def from_config(cls, cfg: dict | None) -> "ModelSpec":
        cfg = cfg or {}
        return cls(provider=cfg.get("provider", DEFAULT_PROVIDER), model=cfg.get("model"))

    def resolved_model(self) -> str:
        return self.model or PROVIDERS[self.provider]["default_model"]


_clients: dict[str, OpenAI] = {}


def _client(provider: str) -> OpenAI:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}; known: {list(PROVIDERS)}")
    if provider not in _clients:
        meta = PROVIDERS[provider]
        api_key = os.environ.get(meta["key_env"])
        if not api_key:
            raise RuntimeError(f"Missing {meta['key_env']} for provider {provider!r}")
        _clients[provider] = OpenAI(api_key=api_key, base_url=meta["base_url"], max_retries=5)
    return _clients[provider]


def complete(messages: list[dict], spec: ModelSpec | None = None, **kwargs) -> tuple[str, dict]:
    """Run a chat completion. Returns (assistant_text, usage_dict)."""
    spec = spec or ModelSpec()
    resp = _client(spec.provider).chat.completions.create(
        model=spec.resolved_model(), messages=messages, **kwargs
    )
    text = resp.choices[0].message.content or ""
    usage = {}
    if getattr(resp, "usage", None):
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens or 0,
            "completion_tokens": resp.usage.completion_tokens or 0,
        }
    return text, usage


def chat(messages: list[dict], spec: ModelSpec | None = None, **kwargs) -> str:
    return complete(messages, spec, **kwargs)[0]


def parse_json(text: str) -> dict:
    """Parse model JSON, tolerating ```json fences."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
