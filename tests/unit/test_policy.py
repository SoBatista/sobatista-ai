from __future__ import annotations

import pytest

from sobai.core.classification import DataClass
from sobai.core.config import EgressPolicy, PolicyConfig
from sobai.core.errors import LocalOnlyViolation, PolicyError
from sobai.policies import EgressAction, PolicyEngine, is_local_provider


def test_is_local_provider() -> None:
    assert is_local_provider("ollama")
    assert not is_local_provider("anthropic")
    assert not is_local_provider("claude-cli")  # bridges relay to cloud


def test_local_only_blocks_cloud() -> None:
    engine = PolicyEngine(PolicyConfig(), local_only_override=True)
    with pytest.raises(LocalOnlyViolation):
        engine.assert_provider_permitted("anthropic")
    # local provider is fine
    engine.assert_provider_permitted("ollama")


def test_local_only_override_precedence() -> None:
    cfg = PolicyConfig(local_only=False)
    engine = PolicyEngine(cfg, local_only_override=True)
    assert engine.local_only is True
    engine2 = PolicyEngine(PolicyConfig(local_only=True), local_only_override=None)
    assert engine2.local_only is True


def test_decide_egress_local_always_allow() -> None:
    engine = PolicyEngine(PolicyConfig())
    d = engine.decide_egress("ollama", DataClass.RESTRICTED, "notion")
    assert d.action is EgressAction.ALLOW


def test_decide_egress_consent_and_deny() -> None:
    engine = PolicyEngine(PolicyConfig())
    assert engine.decide_egress("anthropic", DataClass.PUBLIC).action is EgressAction.ALLOW
    assert engine.decide_egress("anthropic", DataClass.INTERNAL).action is EgressAction.CONSENT
    assert engine.decide_egress("anthropic", DataClass.RESTRICTED).action is EgressAction.DENY


def test_decide_egress_local_only_denies_cloud() -> None:
    engine = PolicyEngine(PolicyConfig(), local_only_override=True)
    d = engine.decide_egress("anthropic", DataClass.PUBLIC)
    assert d.action is EgressAction.DENY


def test_connector_allowlist() -> None:
    engine = PolicyEngine(PolicyConfig(allowed_connectors=["notion"]))
    engine.assert_connector_allowed("notion")
    with pytest.raises(PolicyError):
        engine.assert_connector_allowed("youtube")


def test_custom_egress_policy_allow() -> None:
    cfg = PolicyConfig(egress={DataClass.INTERNAL: EgressPolicy.ALLOW})
    engine = PolicyEngine(cfg)
    assert engine.decide_egress("openai", DataClass.INTERNAL).action is EgressAction.ALLOW
