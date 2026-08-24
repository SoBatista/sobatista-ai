"""Typed configuration model and TOML persistence.

Configuration lives at ``~/.config/sobai/config.toml`` and holds **no secrets** —
credentials always live in the OS keyring. Deliberately, no current provider
model identifiers are hard-coded here: model aliases start empty and are filled
in by ``sobai init`` / ``sobai models discover`` / ``sobai model use`` so the
tool never ships stale vendor model IDs.
"""

from __future__ import annotations

import tomllib
from enum import StrEnum
from typing import Any

import tomli_w
from pydantic import BaseModel, Field

from .classification import DataClass
from .errors import ConfigError
from .paths import Paths

CONFIG_VERSION = 1

# Well-known provider defaults. Base URLs only — never models or keys.
DEFAULT_PROVIDER_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434",
}

# Bridge providers wrap a locally installed CLI rather than an HTTP API.
CLI_BRIDGE_PROVIDERS = ("claude-cli", "codex-cli")


class EgressPolicy(StrEnum):
    """What to do before connector data of a given class leaves for a cloud model."""

    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


class ProviderConfig(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    default_model: str | None = None
    timeout_s: float = 120.0
    max_tool_rounds: int = 6


class PolicyConfig(BaseModel):
    local_only: bool = False
    max_tool_rounds: int = 6
    # Consent behavior per data classification. Secure-by-default: only public
    # data flows to a cloud model without a prompt; restricted never does.
    egress: dict[DataClass, EgressPolicy] = Field(
        default_factory=lambda: {
            DataClass.PUBLIC: EgressPolicy.ALLOW,
            DataClass.INTERNAL: EgressPolicy.ASK,
            DataClass.SENSITIVE: EgressPolicy.ASK,
            DataClass.RESTRICTED: EgressPolicy.DENY,
        }
    )
    # Only connectors in this allowlist may be used. Empty == allow all known,
    # populated by `sobai connect` as connectors are authorized.
    allowed_connectors: list[str] = Field(default_factory=list)


class ProfileConfig(BaseModel):
    """A named bundle of provider/model/policy overrides (e.g. creator, private)."""

    provider: str | None = None
    model: str | None = None
    local_only: bool | None = None
    connectors: list[str] | None = None


class SkillsConfig(BaseModel):
    """User configuration for the Skills engine.

    ``models`` maps a fully qualified Skill name to a **logical model alias**
    already defined in ``[models]`` — never a vendor model id. This is the only
    place a per-Skill model preference may live; a Skill manifest must not name
    a model, so a shared Skill cannot pin you to one vendor.

        [skills.models]
        "builtin:summarize" = "fast"
        "user:security-report" = "qwen14b"
    """

    models: dict[str, str] = Field(default_factory=dict)


class ConnectorMeta(BaseModel):
    """Non-secret metadata about a connected external system.

    Tokens live in the keyring; this records only what is safe to persist: which
    account, which scopes were granted, and when. Never store secrets here.
    """

    account: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_at: str | None = None


class Config(BaseModel):
    version: int = CONFIG_VERSION
    active_provider: str | None = None
    active_model: str | None = None
    active_profile: str | None = None
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    # Logical model aliases: alias -> "provider:model". Starts empty.
    models: dict[str, str] = Field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    connectors: dict[str, ConnectorMeta] = Field(default_factory=dict)
    # Absolute path to a validated local sobatista-ai checkout used by
    # `sobai update`. Non-secret; remembered after `sobai update --source PATH`.
    update_source: str | None = None

    @classmethod
    def default(cls) -> Config:
        providers = {
            name: ProviderConfig(base_url=url) for name, url in DEFAULT_PROVIDER_BASE_URLS.items()
        }
        for name in CLI_BRIDGE_PROVIDERS:
            providers[name] = ProviderConfig()
        return cls(providers=providers)


def _to_toml_dict(config: Config) -> dict[str, Any]:
    """Serialize to a plain dict tomli_w can write.

    ``None`` is not representable in TOML, so None-valued keys are dropped
    (absence round-trips back to the field default on load). Enums are rendered
    as their string values by ``mode="json"``.
    """
    return config.model_dump(mode="json", exclude_none=True)


def load_config(paths: Paths) -> Config:
    """Load configuration, returning defaults if the file does not exist yet."""
    path = paths.config_file
    if not path.exists():
        return Config.default()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            f"Could not read config at {path}: {exc}",
            hint="Fix the TOML syntax or run `sobai init` to regenerate it.",
        ) from exc
    try:
        config = Config.model_validate(data)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(
            f"Config at {path} is invalid: {exc}",
            hint="Run `sobai config show` to inspect, or `sobai init` to regenerate.",
        ) from exc
    # Ensure known providers always exist even if the file predates them.
    merged = Config.default()
    for name, provider in config.providers.items():
        merged.providers[name] = provider
    config.providers = merged.providers
    return config


def save_config(config: Config, paths: Paths) -> None:
    """Persist configuration atomically with owner-only permissions."""
    paths.ensure()
    path = paths.config_file
    tmp = path.with_suffix(".toml.tmp")
    payload = _to_toml_dict(config)
    with tmp.open("wb") as fh:
        tomli_w.dump(payload, fh)
    tmp.chmod(0o600)
    tmp.replace(path)


class ConfigStore:
    """Mutable, save-backed wrapper around a :class:`Config`."""

    def __init__(self, config: Config, paths: Paths) -> None:
        self.config = config
        self.paths = paths

    @classmethod
    def load(cls, paths: Paths) -> ConfigStore:
        return cls(load_config(paths), paths)

    def save(self) -> None:
        save_config(self.config, self.paths)
