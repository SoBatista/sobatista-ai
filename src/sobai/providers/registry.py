"""Provider construction and model-alias resolution.

This is the dependency-injection seam: given the config and the credential
store, it builds a concrete :class:`Provider`. It also resolves logical model
references (aliases, provider-qualified ids) into a ``(provider, model_id)``
pair without ever hard-coding vendor model identifiers.
"""

from __future__ import annotations

from sobai.auth import CredentialStore
from sobai.core.config import CLI_BRIDGE_PROVIDERS, DEFAULT_PROVIDER_BASE_URLS, Config
from sobai.core.errors import AuthError, ConfigError

from .anthropic import AnthropicProvider
from .base import Provider
from .cli_bridge import ClaudeCliProvider, CodexCliProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider

# Friendly names → canonical provider names.
PROVIDER_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "openai": "openai",
    "cx": "openai",
    "gpt": "openai",
    "ollama": "ollama",
    "local": "ollama",
    "claude-cli": "claude-cli",
    "claudecli": "claude-cli",
    "codex-cli": "codex-cli",
    "codex": "codex-cli",
}

ALL_PROVIDERS: tuple[str, ...] = (
    "anthropic",
    "openai",
    "ollama",
    *CLI_BRIDGE_PROVIDERS,
)


def canonical_provider(name: str) -> str:
    canon = PROVIDER_ALIASES.get(name)
    if canon is None:
        raise ConfigError(
            f"Unknown provider '{name}'.",
            hint=f"Known providers: {', '.join(ALL_PROVIDERS)}.",
        )
    return canon


def cred_key(provider: str) -> str:
    """Keyring key for a provider's API credential."""
    return f"provider:{canonical_provider(provider)}:api_key"


def resolve_model_ref(
    config: Config,
    ref: str,
    provider: str | None = None,
) -> tuple[str | None, str]:
    """Resolve a model reference to ``(provider, model_id)``.

    Handles logical aliases (``qwen14b``), provider-qualified ids
    (``anthropic:claude-x``, ``ollama:qwen2.5-coder:7b``), and provider-alias
    prefixes (``claude:sonnet`` where ``sonnet`` is itself an alias). Loops with a
    ``seen`` guard so alias cycles terminate.
    """
    seen: set[str] = set()
    while True:
        if ":" in ref:
            prefix, rest = ref.split(":", 1)
            canon = PROVIDER_ALIASES.get(prefix)
            if canon is not None:
                provider = canon
                ref = rest
                continue
        if ref in config.models and ref not in seen:
            seen.add(ref)
            ref = config.models[ref]
            continue
        break
    return (canonical_provider(provider) if provider else None), ref


def select_provider_model(
    config: Config,
    *,
    provider: str | None = None,
    model: str | None = None,
    profile_name: str | None = None,
) -> tuple[str, str]:
    """Resolve the effective ``(provider, model_id)`` from flags, profile, and config.

    Precedence for both provider and model: explicit flag → active profile →
    active config setting → the provider's configured ``default_model``.
    """
    profile = None
    name = profile_name or config.active_profile
    if name:
        profile = config.profiles.get(name)
        if profile is None:
            raise ConfigError(
                f"Unknown profile '{name}'.",
                hint="List profiles with `sobai profile list`.",
            )

    provider_hint = provider or (profile.provider if profile else None) or config.active_provider
    provider_hint = canonical_provider(provider_hint) if provider_hint else None

    model_ref = model or (profile.model if profile else None) or config.active_model
    if model_ref is None and provider_hint:
        pconf = config.providers.get(provider_hint)
        model_ref = pconf.default_model if pconf else None

    if model_ref is None:
        raise ConfigError(
            "No model selected.",
            hint="Pass -m/--model, run `sobai model use ...`, or set one in `sobai init`.",
        )

    resolved_provider, model_id = resolve_model_ref(config, model_ref, provider_hint)
    # An explicit -p always wins over a provider implied by the model reference.
    final_provider = (canonical_provider(provider) if provider else None) or resolved_provider
    final_provider = final_provider or provider_hint
    if final_provider is None:
        raise ConfigError(
            "No provider selected.",
            hint="Pass -p/--provider, run `sobai provider use ...`, or set one in `sobai init`.",
        )
    if not model_id:
        raise ConfigError(
            "Resolved model id is empty.",
            hint="Check your model aliases with `sobai models list`.",
        )
    return final_provider, model_id


def build_provider(name: str, config: Config, creds: CredentialStore) -> Provider:
    """Instantiate a provider by name from config + keyring credentials."""
    canon = canonical_provider(name)
    pconf = config.providers.get(canon)
    base_url = (pconf.base_url if pconf else None) or DEFAULT_PROVIDER_BASE_URLS.get(canon, "")
    timeout_s = pconf.timeout_s if pconf else 120.0

    if pconf is not None and not pconf.enabled:
        raise ConfigError(
            f"Provider '{canon}' is disabled in config.",
            hint="Enable it in config.toml or choose another provider.",
        )

    if canon == "anthropic":
        key = creds.get(cred_key("anthropic"))
        if not key:
            raise AuthError(
                "No Anthropic API key stored.",
                hint="Run `sobai init` or `sobai connect anthropic` to add one.",
            )
        return AnthropicProvider(api_key=key, base_url=base_url, timeout_s=timeout_s)
    if canon == "openai":
        key = creds.get(cred_key("openai"))
        if not key:
            raise AuthError(
                "No OpenAI API key stored.",
                hint="Run `sobai init` or `sobai connect openai` to add one.",
            )
        return OpenAIProvider(api_key=key, base_url=base_url, timeout_s=timeout_s)
    if canon == "ollama":
        return OllamaProvider(base_url=base_url, timeout_s=timeout_s)
    if canon == "claude-cli":
        return ClaudeCliProvider(timeout_s=timeout_s)
    if canon == "codex-cli":
        return CodexCliProvider(timeout_s=timeout_s)
    raise ConfigError(f"Unsupported provider '{canon}'.")  # pragma: no cover
