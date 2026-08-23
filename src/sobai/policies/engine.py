"""Policy engine: local-only enforcement, cloud-egress consent, connector allowlist.

The engine is deliberately pure — it returns decisions and raises typed errors,
but never prompts or performs I/O. The CLI layer turns a ``CONSENT`` decision
into an interactive prompt (or an automatic allow/deny under a configured
persistent policy). This separation makes every rule unit-testable without a TTY.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sobai.core.classification import DataClass
from sobai.core.config import EgressPolicy, PolicyConfig
from sobai.core.errors import LocalOnlyViolation, PolicyError

# Providers that run entirely on the local machine and therefore never cause
# data to leave it. Everything else — cloud APIs *and* the CLI bridges, which
# relay prompts to Claude Code / Codex cloud backends — is treated as egress.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama"})


def is_local_provider(provider: str) -> bool:
    return provider in LOCAL_PROVIDERS


class EgressAction(StrEnum):
    ALLOW = "allow"
    CONSENT = "consent"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class EgressDecision:
    action: EgressAction
    provider: str
    data_class: DataClass
    connector: str | None
    reason: str


class PolicyEngine:
    def __init__(
        self,
        policy: PolicyConfig,
        *,
        local_only_override: bool | None = None,
    ) -> None:
        self._policy = policy
        self._local_only_override = local_only_override

    @property
    def local_only(self) -> bool:
        if self._local_only_override is not None:
            return self._local_only_override
        return self._policy.local_only

    @property
    def max_tool_rounds(self) -> int:
        return self._policy.max_tool_rounds

    # -- local-only --------------------------------------------------------
    def assert_provider_permitted(self, provider: str) -> None:
        """Hard-fail if ``--local-only`` is active and the provider would egress."""
        if self.local_only and not is_local_provider(provider):
            raise LocalOnlyViolation(
                f"--local-only is active but provider '{provider}' sends data to an "
                "external service.",
                hint="Use a local provider (e.g. `-p ollama`) or drop --local-only.",
            )

    # -- connector allowlist ----------------------------------------------
    def assert_connector_allowed(self, connector: str) -> None:
        allow = self._policy.allowed_connectors
        if allow and connector not in allow:
            raise PolicyError(
                f"Connector '{connector}' is not in the configured allowlist.",
                hint=f"Add it with `sobai connect {connector}` or edit policy.allowed_connectors.",
            )

    # -- cloud egress of connector data -----------------------------------
    def decide_egress(
        self,
        provider: str,
        data_class: DataClass,
        connector: str | None = None,
    ) -> EgressDecision:
        """Decide whether connector data may flow to *provider*.

        Local providers always allow (nothing leaves). Otherwise the per-class
        egress policy applies: ALLOW proceeds silently, ASK yields CONSENT (the
        CLI prompts), DENY blocks.
        """
        if is_local_provider(provider):
            return EgressDecision(
                action=EgressAction.ALLOW,
                provider=provider,
                data_class=data_class,
                connector=connector,
                reason="local provider — data does not leave the machine",
            )
        if self.local_only:
            return EgressDecision(
                action=EgressAction.DENY,
                provider=provider,
                data_class=data_class,
                connector=connector,
                reason="--local-only active",
            )
        policy = self._policy.egress.get(data_class, EgressPolicy.ASK)
        action = {
            EgressPolicy.ALLOW: EgressAction.ALLOW,
            EgressPolicy.ASK: EgressAction.CONSENT,
            EgressPolicy.DENY: EgressAction.DENY,
        }[policy]
        return EgressDecision(
            action=action,
            provider=provider,
            data_class=data_class,
            connector=connector,
            reason=f"egress policy for '{data_class}' is '{policy.value}'",
        )
