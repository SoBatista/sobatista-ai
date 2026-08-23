from __future__ import annotations

from sobai.core.classification import DataClass
from sobai.core.config import (
    Config,
    EgressPolicy,
    ProfileConfig,
    load_config,
    save_config,
)


def test_default_has_known_providers() -> None:
    cfg = Config.default()
    assert set(cfg.providers) >= {"anthropic", "openai", "ollama", "claude-cli", "codex-cli"}
    # No hard-coded model ids ship in defaults.
    assert all(p.default_model is None for p in cfg.providers.values())
    assert cfg.models == {}


def test_egress_defaults_secure() -> None:
    cfg = Config.default()
    assert cfg.policy.egress[DataClass.PUBLIC] is EgressPolicy.ALLOW
    assert cfg.policy.egress[DataClass.RESTRICTED] is EgressPolicy.DENY


def test_load_returns_default_when_missing(isolated_paths) -> None:
    cfg = load_config(isolated_paths)
    assert cfg.version == 1
    assert not isolated_paths.config_file.exists()


def test_save_load_roundtrip_with_none_fields(isolated_paths) -> None:
    cfg = Config.default()
    cfg.active_provider = "ollama"
    cfg.models["qwen7b"] = "ollama:qwen2.5-coder:7b"
    cfg.profiles["creator"] = ProfileConfig(provider="anthropic", model="sonnet")
    save_config(cfg, isolated_paths)
    assert isolated_paths.config_file.exists()

    loaded = load_config(isolated_paths)
    assert loaded.active_provider == "ollama"
    assert loaded.active_model is None  # None round-trips via absence
    assert loaded.models["qwen7b"] == "ollama:qwen2.5-coder:7b"
    assert loaded.profiles["creator"].provider == "anthropic"
    assert loaded.policy.egress[DataClass.RESTRICTED] is EgressPolicy.DENY


def test_config_file_permissions(isolated_paths) -> None:
    save_config(Config.default(), isolated_paths)
    mode = isolated_paths.config_file.stat().st_mode & 0o777
    assert mode == 0o600
