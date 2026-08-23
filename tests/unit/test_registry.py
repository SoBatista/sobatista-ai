from __future__ import annotations

import pytest

from sobai.core.config import Config, ProfileConfig, ProviderConfig
from sobai.core.errors import ConfigError
from sobai.providers.registry import (
    canonical_provider,
    resolve_model_ref,
    select_provider_model,
)


def _cfg() -> Config:
    cfg = Config.default()
    cfg.models = {
        "qwen14b": "ollama:qwen2.5-coder:14b",
        "sonnet": "anthropic:claude-x",
        "fast": "openai:gpt-fast",
    }
    return cfg


def test_canonical_aliases() -> None:
    assert canonical_provider("claude") == "anthropic"
    assert canonical_provider("cx") == "openai"
    assert canonical_provider("local") == "ollama"
    with pytest.raises(ConfigError):
        canonical_provider("nope")


def test_resolve_bare_alias() -> None:
    assert resolve_model_ref(_cfg(), "qwen14b") == ("ollama", "qwen2.5-coder:14b")


def test_resolve_provider_qualified_with_colon_model() -> None:
    # ollama model ids themselves contain a colon
    assert resolve_model_ref(_cfg(), "ollama:qwen2.5-coder:7b") == ("ollama", "qwen2.5-coder:7b")


def test_resolve_provider_alias_then_alias() -> None:
    # claude:sonnet -> provider anthropic, sonnet alias -> anthropic:claude-x
    assert resolve_model_ref(_cfg(), "claude:sonnet") == ("anthropic", "claude-x")


def test_resolve_literal_qualified() -> None:
    assert resolve_model_ref(_cfg(), "anthropic:claude-actual") == ("anthropic", "claude-actual")


def test_resolve_alias_cycle_terminates() -> None:
    cfg = Config.default()
    cfg.models = {"a": "b", "b": "a"}
    # Should not hang; returns something without a provider.
    provider, _model = resolve_model_ref(cfg, "a")
    assert provider is None


def test_select_precedence_explicit_provider_wins() -> None:
    cfg = _cfg()
    cfg.active_provider = "ollama"
    cfg.active_model = "qwen14b"
    # explicit -p anthropic overrides the ollama-bound active model's provider
    provider, _model = select_provider_model(cfg, provider="anthropic")
    assert provider == "anthropic"


def test_select_uses_profile() -> None:
    cfg = _cfg()
    cfg.profiles["creator"] = ProfileConfig(provider="openai", model="fast")
    provider, model = select_provider_model(cfg, profile_name="creator")
    assert provider == "openai"
    assert model == "gpt-fast"


def test_select_uses_default_model() -> None:
    cfg = Config.default()
    cfg.providers["ollama"] = ProviderConfig(default_model="llama3")
    provider, model = select_provider_model(cfg, provider="ollama")
    assert provider == "ollama"
    assert model == "llama3"


def test_select_no_model_raises() -> None:
    cfg = Config.default()
    with pytest.raises(ConfigError):
        select_provider_model(cfg, provider="anthropic")
