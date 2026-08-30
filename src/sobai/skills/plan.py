"""The typed, deterministic execution plan for a Skill run.

``--dry-run`` produces a :class:`SkillRunPlan` and stops. Building one performs
**no** provider construction, network call, subprocess, connector access, or
credential read — it resolves names and sizes only. That is what lets you ask
"what would this do, and would anything leave my machine?" without a key
configured and without spending a token.

The plan reports the input by source, size, and hash — never by content — so it
is safe to paste into a ticket or capture in CI logs.

These models are deliberately general. The later ``explain-plan`` work needs the
same vocabulary (what will run, where, under which policy, at what cost), so
:class:`ModelResolution`, :class:`EgressAssessment`, :class:`PlanLimits`, and
:class:`ExecutionShape` are written to be reused rather than re-invented.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sobai.core.classification import DataClass
from sobai.core.config import Config
from sobai.policies import EgressDecision, PolicyEngine, is_local_provider
from sobai.providers.registry import select_provider_model

from .inputs import SkillInput
from .models import Skill

#: Bumped when the plan's JSON shape changes incompatibly.
PLAN_VERSION = 1

ModelSource = Literal["cli-flag", "skill-mapping", "profile", "config-default"]
DataClassSource = Literal["flag", "skill-recommendation"]


class ModelResolution(BaseModel):
    """Which provider and model won, and why."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    source: ModelSource
    #: The logical alias that produced the model, when one was involved.
    alias: str | None = None
    explanation: str


class EgressAssessment(BaseModel):
    """Whether this run would send anything off the machine."""

    model_config = ConfigDict(frozen=True)

    provider_is_local: bool
    data_leaves_machine: bool
    local_only: bool
    decision: str
    reason: str


class InputSummary(BaseModel):
    """The input described by shape, never by content."""

    model_config = ConfigDict(frozen=True)

    source: str
    bytes: int
    chars: int
    digest: str
    origin: str | None = None


class SkillIdentity(BaseModel):
    """Everything needed to identify exactly which Skill would run."""

    model_config = ConfigDict(frozen=True)

    qualified_name: str
    name: str
    namespace: str
    version: str
    digest: str
    description: str
    author: str | None = None
    license: str
    tags: list[str] = Field(default_factory=list)
    source: str


class OutputContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    format: str
    description: str = ""
    has_schema: bool = False


class PlanLimits(BaseModel):
    """The bounds this run is held to."""

    model_config = ConfigDict(frozen=True)

    max_input_bytes: int
    max_input_chars: int
    max_output_tokens: int
    timeout_s: float
    max_tool_rounds: int


class ExecutionShape(BaseModel):
    """The rough shape of the work, without predicting the model's behaviour."""

    model_config = ConfigDict(frozen=True)

    provider_calls: int
    streaming: bool
    tools_available: int
    writes_enabled: bool


class SkillRunPlan(BaseModel):
    """A complete, machine-readable description of what a Skill run would do."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-run-plan"] = "skill-run-plan"
    plan_version: int = PLAN_VERSION
    skill: SkillIdentity
    input: InputSummary
    data_class: DataClass
    data_class_source: DataClassSource
    model: ModelResolution
    egress: EgressAssessment
    required_tools: list[str] = Field(default_factory=list)
    output: OutputContract
    variables: dict[str, str | int | float | bool] = Field(default_factory=dict)
    limits: PlanLimits
    execution: ExecutionShape

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# -- resolution ------------------------------------------------------------
def resolve_skill_model(
    config: Config,
    skill: Skill,
    *,
    provider: str | None = None,
    model: str | None = None,
    profile_name: str | None = None,
) -> ModelResolution:
    """Resolve the provider and model for *skill*, most specific wins.

    Order of precedence:

    1. ``-p/--provider`` / ``-m/--model`` on the command line,
    2. the per-Skill alias in ``[skills.models]``, keyed by fully qualified name,
    3. the active profile, then the configured defaults.

    A per-Skill entry names a **logical alias** from ``[models]``, never a vendor
    model id, so the mapping stays portable across providers.
    """
    mapped = config.skills.models.get(skill.qualified_name)

    if provider or model:
        source: ModelSource = "cli-flag"
        alias = model
        effective_model = model
        explanation = "command-line flags override every configured preference"
    elif mapped:
        source = "skill-mapping"
        alias = mapped
        effective_model = mapped
        explanation = f"[skills.models] maps {skill.qualified_name!r} to alias {mapped!r}"
    else:
        active_profile = profile_name or config.active_profile
        source = "profile" if active_profile else "config-default"
        alias = None
        effective_model = None
        explanation = (
            f"profile {active_profile!r} selection"
            if active_profile
            else "the configured default provider and model"
        )

    resolved_provider, resolved_model = select_provider_model(
        config,
        provider=provider,
        model=effective_model,
        profile_name=profile_name,
    )
    return ModelResolution(
        provider=resolved_provider,
        model=resolved_model,
        source=source,
        alias=alias,
        explanation=explanation,
    )


def assess_egress(
    policy: PolicyEngine,
    decision: EgressDecision,
    provider: str,
) -> EgressAssessment:
    """Summarise an egress decision for a plan."""
    local = is_local_provider(provider)
    return EgressAssessment(
        provider_is_local=local,
        data_leaves_machine=not local,
        local_only=policy.local_only,
        decision=decision.action.value,
        reason=decision.reason,
    )


def skill_identity(skill: Skill) -> SkillIdentity:
    meta = skill.manifest.skill
    return SkillIdentity(
        qualified_name=skill.qualified_name,
        name=skill.name,
        namespace=skill.namespace,
        version=skill.version,
        digest=skill.digest,
        description=meta.description,
        author=meta.author,
        license=meta.license,
        tags=list(meta.tags),
        source=skill.manifest.provenance.source,
    )


def input_summary(data: SkillInput) -> InputSummary:
    return InputSummary(
        source=data.source,
        bytes=data.byte_size,
        chars=data.char_size,
        digest=data.digest,
        origin=data.origin,
    )


def build_plan(
    skill: Skill,
    data: SkillInput,
    *,
    data_class: DataClass,
    data_class_source: DataClassSource,
    resolution: ModelResolution,
    egress: EgressAssessment,
    variables: dict[str, str | int | float | bool],
    max_output_tokens: int,
    timeout_s: float,
    max_tool_rounds: int,
    streaming: bool,
) -> SkillRunPlan:
    """Assemble the typed plan from already-resolved parts."""
    manifest = skill.manifest
    return SkillRunPlan(
        skill=skill_identity(skill),
        input=input_summary(data),
        data_class=data_class,
        data_class_source=data_class_source,
        model=resolution,
        egress=egress,
        required_tools=list(manifest.policy.required_tools),
        output=OutputContract(
            format=manifest.output.format,
            description=manifest.output.description,
            has_schema=manifest.output.schema_ is not None,
        ),
        variables=variables,
        limits=PlanLimits(
            max_input_bytes=manifest.input.max_bytes,
            max_input_chars=manifest.input.max_chars,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s,
            max_tool_rounds=max_tool_rounds,
        ),
        execution=ExecutionShape(
            provider_calls=1,
            streaming=streaming,
            # Skills expose no tools in this phase; the count is explicit so a
            # future change to that is visible in every plan and test.
            tools_available=0,
            writes_enabled=False,
        ),
    )
