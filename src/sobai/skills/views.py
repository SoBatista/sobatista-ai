"""Stable JSON payload schemas for Skill automation.

Every ``--json`` document produced by a ``sobai skills`` command is one of these
models. Each carries a ``kind`` discriminator and a version, so a script can
branch on the shape and detect an incompatible change instead of guessing.

Nothing decorative appears here: no colour, no spinners, no prose framing. What
a caller gets is the data.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sobai.core.classification import DataClass

from .models import Skill, SkillManifest, VariableSpec
from .plan import ModelResolution
from .registry import BrokenSkill, SkillRegistry

#: Bumped when any payload in this module changes incompatibly.
VIEW_VERSION = 1


class SkillListEntry(BaseModel):
    """One row of ``sobai skills list``."""

    model_config = ConfigDict(frozen=True)

    qualified_name: str
    name: str
    namespace: str
    version: str
    description: str
    license: str
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    digest: str
    recommended_data_class: DataClass
    required_tools: list[str] = Field(default_factory=list)


class BrokenSkillEntry(BaseModel):
    """A Skill directory that exists but did not validate."""

    model_config = ConfigDict(frozen=True)

    qualified_name: str
    namespace: str
    name: str
    reason: str


class SkillListing(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-list"] = "skill-list"
    view_version: int = VIEW_VERSION
    skills: list[SkillListEntry] = Field(default_factory=list)
    broken: list[BrokenSkillEntry] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VariableView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    description: str = ""
    required: bool
    default: str | int | float | bool | None = None
    choices: list[str] | None = None
    max_length: int


class SkillDetail(BaseModel):
    """The payload of ``sobai skills show``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-detail"] = "skill-detail"
    view_version: int = VIEW_VERSION
    schema_version: int
    qualified_name: str
    name: str
    namespace: str
    version: str
    digest: str
    description: str
    author: str | None = None
    license: str
    tags: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    recommended_data_class: DataClass
    required_tools: list[str] = Field(default_factory=list)
    variables: list[VariableView] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    #: The Skill's prompt, so what will be sent is inspectable before it is sent.
    prompt: str
    #: How provider/model would resolve for this Skill right now, or ``None``
    #: with ``model_resolution_error`` explaining why it cannot be determined.
    model: ModelResolution | None = None
    model_resolution_error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ValidationReport(BaseModel):
    """The payload of ``sobai skills validate``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-validation"] = "skill-validation"
    view_version: int = VIEW_VERSION
    valid: bool
    path: str
    qualified_name: str | None = None
    name: str | None = None
    version: str | None = None
    digest: str | None = None
    license: str | None = None
    variables: list[str] = Field(default_factory=list)
    error: str | None = None
    hint: str | None = None

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class InstallReport(BaseModel):
    """The payload of ``sobai skills install``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-install"] = "skill-install"
    view_version: int = VIEW_VERSION
    action: str
    changed: bool
    qualified_name: str
    name: str
    version: str
    digest: str
    license: str
    destination: str

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SkillPaths(BaseModel):
    """The payload of ``sobai skills paths``."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["skill-paths"] = "skill-paths"
    view_version: int = VIEW_VERSION
    user_skills_dir: str
    user_skills_dir_exists: bool
    builtin_source: str
    #: Locations that are deliberately never searched, and why.
    never_searched: list[str] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# -- builders --------------------------------------------------------------
def list_entry(skill: Skill) -> SkillListEntry:
    meta = skill.manifest.skill
    return SkillListEntry(
        qualified_name=skill.qualified_name,
        name=skill.name,
        namespace=skill.namespace,
        version=skill.version,
        description=meta.description,
        license=meta.license,
        author=meta.author,
        tags=list(meta.tags),
        digest=skill.digest,
        recommended_data_class=skill.manifest.policy.recommended_data_class,
        required_tools=list(skill.manifest.policy.required_tools),
    )


def broken_entry(broken: BrokenSkill) -> BrokenSkillEntry:
    return BrokenSkillEntry(
        qualified_name=broken.qualified_name,
        namespace=broken.namespace,
        name=broken.name,
        reason=broken.reason,
    )


def listing(registry: SkillRegistry) -> SkillListing:
    return SkillListing(
        skills=[list_entry(s) for s in registry.list()],
        broken=[broken_entry(b) for b in registry.broken],
    )


def variable_view(spec: VariableSpec) -> VariableView:
    return VariableView(
        name=spec.name,
        type=spec.type,
        description=spec.description,
        required=spec.required,
        default=spec.default,
        choices=list(spec.choices) if spec.choices else None,
        max_length=spec.max_length,
    )


def _input_view(manifest: SkillManifest) -> dict[str, Any]:
    spec = manifest.input
    return {
        "description": spec.description,
        "required": spec.required,
        "max_bytes": spec.max_bytes,
        "max_chars": spec.max_chars,
    }


def _output_view(manifest: SkillManifest) -> dict[str, Any]:
    spec = manifest.output
    return {
        "format": spec.format,
        "description": spec.description,
        "has_schema": spec.schema_ is not None,
        "schema": spec.schema_,
    }


def detail(
    skill: Skill,
    *,
    model: ModelResolution | None = None,
    model_resolution_error: str | None = None,
) -> SkillDetail:
    manifest = skill.manifest
    meta = manifest.skill
    return SkillDetail(
        schema_version=manifest.schema_version,
        qualified_name=skill.qualified_name,
        name=skill.name,
        namespace=skill.namespace,
        version=skill.version,
        digest=skill.digest,
        description=meta.description,
        author=meta.author,
        license=meta.license,
        tags=list(meta.tags),
        input=_input_view(manifest),
        output=_output_view(manifest),
        recommended_data_class=manifest.policy.recommended_data_class,
        required_tools=list(manifest.policy.required_tools),
        variables=[variable_view(v) for v in manifest.variables],
        provenance=manifest.provenance.model_dump(mode="json"),
        prompt=skill.prompt,
        model=model,
        model_resolution_error=model_resolution_error,
    )
