"""Executing a Skill through the existing core, and the typed result it returns.

The runner owns no policy of its own. It receives an already-resolved provider,
an already-rendered prompt, and an already-approved egress decision, then drives
the standard :class:`~sobai.core.orchestrator.Orchestrator` — the same loop,
timeouts, cancellation, retries, usage accounting, and run records that
``sobai ask`` uses. There is no second execution path, and no Skill-specific
network code exists anywhere in this package.

Tools stay off. A Skill runs with ``registry=None``, so no tool can be called
even if a prompt asks for one. A Skill that *declares* required tools is refused
up front by :func:`assert_tools_available` rather than quietly running without
them, because silently doing less than the recipe promised is its own failure.

Audit records carry identity and size — never the prompt, the input, or the
output. See ``PRIVACY.md``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sobai.core.classification import DataClass
from sobai.core.errors import SkillError
from sobai.core.orchestrator import Orchestrator
from sobai.core.types import GenerateParams, Message, Usage
from sobai.providers.base import Provider
from sobai.storage import Database

from .inputs import SkillInput
from .models import Skill
from .plan import InputSummary, SkillIdentity, input_summary, skill_identity
from .renderer import RenderedPrompt

#: Bumped when the execution-result JSON shape changes incompatibly.
RESULT_VERSION = 1


class SkillToolsUnavailable(SkillError):
    """A Skill declares connector tools that this run cannot provide."""


def assert_tools_available(skill: Skill, available: frozenset[str] | set[str]) -> None:
    """Refuse to run a Skill whose declared tools are not all available.

    A Skill cannot *enable* a tool — declaring one is a statement of need. If the
    need cannot be met, the run fails loudly instead of silently degrading.
    """
    required = list(skill.manifest.policy.required_tools)
    if not required:
        return
    missing = sorted(set(required) - set(available))
    if missing:
        raise SkillToolsUnavailable(
            f"{skill.qualified_name} requires connector tools that are not available: "
            f"{', '.join(missing)}.",
            hint="Connect the relevant connector, or choose a skill that needs no tools.",
        )


@dataclass(frozen=True, slots=True)
class SkillExecution:
    """The raw outcome of one Skill run."""

    text: str
    usage: Usage
    stop_reason: str
    tool_rounds: int
    duration_ms: int


class SkillProvenanceView(BaseModel):
    """The provenance travelling with a result, so output can be traced to a recipe."""

    model_config = ConfigDict(frozen=True)

    digest: str
    license: str
    author: str | None = None
    source: str
    namespace: str


class SkillRunResult(BaseModel):
    """The stable JSON contract for a completed Skill run."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-run-result"] = "skill-run-result"
    result_version: int = RESULT_VERSION
    run_id: str
    skill: SkillIdentity
    provider: str
    model: str
    billing_mode: str
    cost_kind: str
    data_class: DataClass
    output: str
    output_format: str
    stop_reason: str
    usage: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int
    #: Input shape only — size and hash, never the input itself.
    input: InputSummary
    provenance: SkillProvenanceView

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_params(
    skill: Skill,
    rendered: RenderedPrompt,
    *,
    model: str,
    max_tokens: int,
    timeout_s: float,
    temperature: float | None = None,
) -> GenerateParams:
    """Assemble provider parameters, keeping input in its own user message."""
    output = skill.manifest.output
    return GenerateParams(
        model=model,
        messages=[Message.user(rendered.user)],
        system=rendered.system,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
        response_schema=output.schema_ if output.format == "json" else None,
    )


async def execute_skill(
    provider: Provider,
    params: GenerateParams,
    *,
    db: Database | None = None,
    run_id: str | None = None,
    stream: bool = False,
    on_text: Callable[[str], None] | None = None,
) -> SkillExecution:
    """Run the prompt through the standard orchestrator with tools disabled."""
    started = time.monotonic()
    orchestrator = Orchestrator(
        provider,
        # No registry means no tool can be called, whatever the prompt asks for.
        registry=None,
        db=db,
        run_id=run_id,
    )
    try:
        result = await orchestrator.run(params, stream=stream, on_text=on_text)
    finally:
        await provider.aclose()
    return SkillExecution(
        text=result.text,
        usage=result.usage,
        stop_reason=str(result.stop_reason),
        tool_rounds=result.tool_rounds,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def run_summary(skill: Skill) -> str:
    """The run-history summary for a Skill run.

    Deliberately the Skill's identity and nothing about the input. ``sobai ask``
    records a truncated prompt; a Skill run must not, because the input is
    frequently the sensitive part.
    """
    return f"skill {skill.reference}"


def audit_detail(skill: Skill, data: SkillInput) -> dict[str, Any]:
    """Metadata recorded alongside an egress event — identity and shape only."""
    return {
        "skill": skill.qualified_name,
        "skill_version": skill.version,
        "skill_digest": skill.digest,
        "input_source": data.source,
        "input_bytes": data.byte_size,
        "input_digest": data.digest,
    }


def build_result(
    skill: Skill,
    execution: SkillExecution,
    data: SkillInput,
    *,
    run_id: str,
    provider: str,
    model: str,
    billing_mode: str,
    cost_kind: str,
    data_class: DataClass,
) -> SkillRunResult:
    """Assemble the typed, machine-readable result of a completed run."""
    return SkillRunResult(
        run_id=run_id,
        skill=skill_identity(skill),
        provider=provider,
        model=model,
        billing_mode=billing_mode,
        cost_kind=cost_kind,
        data_class=data_class,
        output=execution.text,
        output_format=skill.manifest.output.format,
        stop_reason=execution.stop_reason,
        usage=execution.usage.model_dump(),
        duration_ms=execution.duration_ms,
        input=input_summary(data),
        provenance=SkillProvenanceView(
            digest=skill.digest,
            license=skill.manifest.skill.license,
            author=skill.manifest.skill.author,
            source=skill.manifest.provenance.source,
            namespace=skill.namespace,
        ),
    )
