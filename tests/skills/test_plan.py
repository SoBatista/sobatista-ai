"""Provider/model resolution order and the typed dry-run plan."""

from __future__ import annotations

import pytest

from sobai.core.classification import DataClass
from sobai.core.config import Config, PolicyConfig, ProfileConfig, SkillsConfig
from sobai.core.errors import ConfigError
from sobai.policies import PolicyEngine
from sobai.skills.inputs import SkillInput
from sobai.skills.loader import parse_skill
from sobai.skills.models import Skill
from sobai.skills.plan import (
    PLAN_VERSION,
    assess_egress,
    build_plan,
    resolve_skill_model,
)
from sobai.skills.provenance import digest_bytes

from .conftest import MINIMAL_PROMPT, manifest_toml


def make_skill(name: str = "summarize", namespace: str = "builtin") -> Skill:
    return parse_skill(
        manifest_toml(name=name).encode(),
        MINIMAL_PROMPT.encode(),
        namespace=namespace,
    )


def config_with(**kwargs: object) -> Config:
    config = Config.default()
    config.models = {"fast": "ollama:qwen2.5:7b", "big": "anthropic:some-model-id"}
    config.active_provider = "ollama"
    config.active_model = "fast"
    for key, value in kwargs.items():
        setattr(config, key, value)
    return config


SAMPLE_INPUT = SkillInput(
    text="material",
    source="file",
    byte_size=8,
    char_size=8,
    digest=digest_bytes(b"material"),
    origin="notes.md",
)


# -- resolution precedence -------------------------------------------------
def test_defaults_resolve_from_active_config() -> None:
    resolution = resolve_skill_model(config_with(), make_skill())
    assert (resolution.provider, resolution.model) == ("ollama", "qwen2.5:7b")
    assert resolution.source == "config-default"


def test_per_skill_mapping_beats_the_config_default() -> None:
    config = config_with(skills=SkillsConfig(models={"builtin:summarize": "big"}))
    resolution = resolve_skill_model(config, make_skill())
    assert resolution.source == "skill-mapping"
    assert resolution.alias == "big"
    assert (resolution.provider, resolution.model) == ("anthropic", "some-model-id")
    assert "builtin:summarize" in resolution.explanation


def test_command_line_flags_beat_the_per_skill_mapping() -> None:
    config = config_with(skills=SkillsConfig(models={"builtin:summarize": "big"}))
    resolution = resolve_skill_model(config, make_skill(), provider="ollama", model="fast")
    assert resolution.source == "cli-flag"
    assert (resolution.provider, resolution.model) == ("ollama", "qwen2.5:7b")


def test_provider_flag_alone_still_counts_as_a_cli_override() -> None:
    config = config_with(skills=SkillsConfig(models={"builtin:summarize": "big"}))
    resolution = resolve_skill_model(config, make_skill(), provider="ollama")
    assert resolution.source == "cli-flag"
    assert resolution.provider == "ollama"


def test_profile_is_used_when_no_flag_or_mapping_applies() -> None:
    config = config_with(profiles={"private": ProfileConfig(provider="ollama", model="fast")})
    resolution = resolve_skill_model(config, make_skill(), profile_name="private")
    assert resolution.source == "profile"
    assert "private" in resolution.explanation


def test_mapping_beats_the_profile() -> None:
    config = config_with(
        profiles={"private": ProfileConfig(provider="ollama", model="fast")},
        skills=SkillsConfig(models={"builtin:summarize": "big"}),
    )
    resolution = resolve_skill_model(config, make_skill(), profile_name="private")
    assert resolution.source == "skill-mapping"
    assert resolution.provider == "anthropic"


def test_mapping_is_keyed_by_the_fully_qualified_name() -> None:
    """A short-name key must not silently apply to both namespaces."""
    config = config_with(skills=SkillsConfig(models={"summarize": "big"}))
    resolution = resolve_skill_model(config, make_skill())
    assert resolution.source == "config-default"


def test_mapping_distinguishes_builtin_from_user() -> None:
    config = config_with(skills=SkillsConfig(models={"user:summarize": "big"}))
    assert resolve_skill_model(config, make_skill(namespace="builtin")).provider == "ollama"
    assert resolve_skill_model(config, make_skill(namespace="user")).provider == "anthropic"


def test_an_unknown_alias_in_a_mapping_fails_loudly() -> None:
    config = config_with(skills=SkillsConfig(models={"builtin:summarize": "no-such-alias"}))
    config.active_provider = None
    with pytest.raises(ConfigError):
        resolve_skill_model(config, make_skill())


# -- egress assessment -----------------------------------------------------
def test_local_provider_does_not_leave_the_machine() -> None:
    policy = PolicyEngine(PolicyConfig())
    decision = policy.decide_egress("ollama", DataClass.SENSITIVE)
    assessment = assess_egress(policy, decision, "ollama")
    assert assessment.provider_is_local
    assert not assessment.data_leaves_machine
    assert assessment.decision == "allow"


def test_cloud_provider_with_internal_data_requires_consent() -> None:
    policy = PolicyEngine(PolicyConfig())
    decision = policy.decide_egress("anthropic", DataClass.INTERNAL)
    assessment = assess_egress(policy, decision, "anthropic")
    assert assessment.data_leaves_machine
    assert assessment.decision == "consent"


def test_restricted_data_is_denied_by_default() -> None:
    policy = PolicyEngine(PolicyConfig())
    decision = policy.decide_egress("anthropic", DataClass.RESTRICTED)
    assert assess_egress(policy, decision, "anthropic").decision == "deny"


def test_local_only_denies_a_cloud_provider() -> None:
    policy = PolicyEngine(PolicyConfig(), local_only_override=True)
    decision = policy.decide_egress("anthropic", DataClass.PUBLIC)
    assessment = assess_egress(policy, decision, "anthropic")
    assert assessment.local_only
    assert assessment.decision == "deny"


# -- the plan --------------------------------------------------------------
def build_sample_plan() -> object:
    policy = PolicyEngine(PolicyConfig())
    skill = make_skill()
    resolution = resolve_skill_model(config_with(), skill)
    decision = policy.decide_egress(resolution.provider, DataClass.INTERNAL)
    return build_plan(
        skill,
        SAMPLE_INPUT,
        data_class=DataClass.INTERNAL,
        data_class_source="skill-recommendation",
        resolution=resolution,
        egress=assess_egress(policy, decision, resolution.provider),
        variables={"tone": "neutral"},
        max_output_tokens=4096,
        timeout_s=120.0,
        max_tool_rounds=6,
        streaming=True,
    )


def test_plan_json_is_versioned_and_discriminated() -> None:
    payload = build_sample_plan().to_json()  # type: ignore[attr-defined]
    assert payload["kind"] == "skill-run-plan"
    assert payload["plan_version"] == PLAN_VERSION


def test_plan_reports_input_by_shape_never_by_content() -> None:
    payload = build_sample_plan().to_json()  # type: ignore[attr-defined]
    assert payload["input"] == {
        "source": "file",
        "bytes": 8,
        "chars": 8,
        "digest": SAMPLE_INPUT.digest,
        "origin": "notes.md",
    }
    assert "material" not in str(payload["input"])
    assert "text" not in payload["input"]


def test_plan_records_identity_limits_and_shape() -> None:
    payload = build_sample_plan().to_json()  # type: ignore[attr-defined]
    assert payload["skill"]["digest"].startswith("sha256:")
    assert payload["skill"]["license"] == "MIT"
    assert payload["limits"]["max_output_tokens"] == 4096
    assert payload["limits"]["max_tool_rounds"] == 6
    assert payload["execution"] == {
        "provider_calls": 1,
        "streaming": True,
        "tools_available": 0,
        "writes_enabled": False,
    }


def test_plan_explains_the_model_decision() -> None:
    payload = build_sample_plan().to_json()  # type: ignore[attr-defined]
    assert payload["model"]["source"] == "config-default"
    assert payload["model"]["explanation"]
