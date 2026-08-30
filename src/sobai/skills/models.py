"""Typed Skill schema: manifest, variables, provenance, and the loaded Skill.

The manifest is the stable, schema-versioned contract for a Skill. Every model
here sets ``extra="forbid"`` so an unknown key is a loud validation failure
rather than a silently ignored field — a Skill that asks for something this
build does not understand must never run as if it had been honoured.

Two fields are deliberately *not* author-controlled:

* **namespace** — assigned by the loader from *where* the Skill came from, so a
  user Skill can never claim to be ``builtin:``.
* **digest** — computed over the normalized manifest and prompt, so it cannot be
  asserted by the author.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sobai.core.classification import DataClass

#: Manifest schema version. Bumped only for an incompatible manifest change;
#: a Skill declaring a newer version than this build understands is refused.
SKILL_SCHEMA_VERSION = 1

# -- naming ----------------------------------------------------------------
# Strict, portable, ASCII-only. This rejects path separators, traversal (`..`),
# control characters, whitespace, leading/trailing/double hyphens, and every
# non-ASCII character — which is the practical defence against Unicode
# confusables: a Cyrillic look-alike letter simply cannot appear in a name.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VARIABLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

NAME_MAX_LENGTH = 64
VARIABLE_NAME_MAX_LENGTH = 32

#: Names that must never identify a Skill: namespace labels, filesystem
#: specials, and legacy Windows device names (a Skill name becomes a directory).
RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "builtin",
        "user",
        "skill",
        "skills",
        "all",
        "none",
        "new",
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

#: ``input`` is the primary-input channel, not a template variable. Reserving it
#: keeps untrusted input out of the rendered system prompt by construction.
RESERVED_VARIABLE_NAMES: frozenset[str] = frozenset({"input", "system", "skill", "sobai"})


class SkillNameError(ValueError):
    """A Skill or variable name violates the portable-name syntax."""


def validate_skill_name(name: str) -> str:
    """Return *name* if it is a legal Skill name, else raise :class:`SkillNameError`."""
    if not name:
        raise SkillNameError("a skill name must not be empty")
    if len(name) > NAME_MAX_LENGTH:
        raise SkillNameError(f"skill name is longer than {NAME_MAX_LENGTH} characters")
    if not _NAME_RE.match(name):
        raise SkillNameError(
            f"invalid skill name {name!r}: use lowercase ASCII letters, digits, and "
            "single hyphens, starting with a letter (e.g. 'extract-insights')"
        )
    if name in RESERVED_NAMES:
        raise SkillNameError(f"{name!r} is a reserved name and cannot identify a skill")
    return name


def validate_variable_name(name: str) -> str:
    """Return *name* if it is a legal variable name, else raise :class:`SkillNameError`."""
    if not name:
        raise SkillNameError("a variable name must not be empty")
    if len(name) > VARIABLE_NAME_MAX_LENGTH:
        raise SkillNameError(f"variable name is longer than {VARIABLE_NAME_MAX_LENGTH} characters")
    if not _VARIABLE_RE.match(name):
        raise SkillNameError(
            f"invalid variable name {name!r}: use lowercase ASCII letters, digits, and "
            "underscores, starting with a letter"
        )
    if name in RESERVED_VARIABLE_NAMES:
        raise SkillNameError(f"{name!r} is reserved and cannot be a skill variable")
    return name


class Namespace:
    """Skill namespaces. Assigned by the loader, never read from a manifest."""

    BUILTIN = "builtin"
    USER = "user"

    #: Search order for an unqualified short name. Built-ins are listed first so
    #: they are never *replaced* — an ambiguity is reported, not resolved.
    ALL: tuple[str, ...] = (BUILTIN, USER)


def qualify(namespace: str, name: str) -> str:
    """Return the fully qualified ``namespace:name`` reference."""
    return f"{namespace}:{name}"


VariableType = Literal["string", "integer", "number", "boolean"]

#: Upper bound on any single rendered string variable, so a variable can never
#: become a bulk-content channel that bypasses the input size limits.
VARIABLE_VALUE_MAX_LENGTH = 512


class VariableSpec(BaseModel):
    """A declared, typed template variable.

    Only scalars are permitted. There are no objects, lists, or expressions —
    the renderer substitutes validated scalar values and nothing else.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    type: VariableType = "string"
    description: str = ""
    required: bool = True
    default: str | int | float | bool | None = None
    #: Optional closed set of permitted values (string variables only).
    choices: list[str] | None = None
    max_length: Annotated[int, Field(gt=0, le=VARIABLE_VALUE_MAX_LENGTH)] = (
        VARIABLE_VALUE_MAX_LENGTH
    )

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return validate_variable_name(value)

    @field_validator("choices")
    @classmethod
    def _check_choices(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not value:
            raise ValueError("choices must not be an empty list")
        return value


class SkillMeta(BaseModel):
    """Identity and attribution for a Skill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str
    description: str
    author: str | None = None
    #: An SPDX identifier (e.g. "MIT"), or the literal "private" for a Skill the
    #: author keeps to themselves. Never blank — provenance is not optional.
    license: str = "private"
    tags: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return validate_skill_name(value)

    @field_validator("version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if not _VERSION_RE.match(value):
            raise ValueError(f"skill version must be exact SemVer (x.y.z), got {value!r}")
        return value

    @field_validator("description")
    @classmethod
    def _check_description(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("a skill needs a non-empty description")
        if len(text) > 400:
            raise ValueError("description is longer than 400 characters")
        return text

    @field_validator("license")
    @classmethod
    def _check_license(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("license must name an SPDX identifier or 'private'")
        return text

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: list[str]) -> list[str]:
        if len(value) > 12:
            raise ValueError("a skill may declare at most 12 tags")
        for tag in value:
            if not _NAME_RE.match(tag):
                raise ValueError(f"invalid tag {tag!r}: use lowercase letters, digits, hyphens")
        return value


#: Hard ceilings the manifest may not exceed. A Skill can lower its own limits
#: but never raise them above what this build permits.
INPUT_MAX_BYTES_CEILING = 1_048_576  # 1 MiB
INPUT_MAX_CHARS_CEILING = 400_000


class InputSpec(BaseModel):
    """What the Skill expects as its primary input, and how much of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = ""
    max_bytes: Annotated[int, Field(gt=0, le=INPUT_MAX_BYTES_CEILING)] = 262_144
    max_chars: Annotated[int, Field(gt=0, le=INPUT_MAX_CHARS_CEILING)] = 200_000
    #: Whether the Skill can do anything useful with no input at all.
    required: bool = True


class OutputSpec(BaseModel):
    """The Skill's output contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["markdown", "text", "json"] = "markdown"
    description: str = ""
    #: Optional JSON Schema for structured output, passed to providers that
    #: support it. Only meaningful when ``format`` is "json".
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    @field_validator("schema_")
    @classmethod
    def _check_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and "type" not in value:
            raise ValueError("output schema must be a JSON Schema object with a 'type'")
        return value


class PolicySpec(BaseModel):
    """The Skill's *recommendation* to the policy engine — never an override.

    ``recommended_data_class`` is a default the user can raise or lower with
    ``--data-class``; it can never relax the configured egress policy.
    ``required_tools`` is a declaration of need, not a grant: a Skill cannot
    enable a tool, and running one that requires unavailable tools fails.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommended_data_class: DataClass = DataClass.INTERNAL
    required_tools: list[str] = Field(default_factory=list)

    @field_validator("required_tools")
    @classmethod
    def _check_tools(cls, value: list[str]) -> list[str]:
        for tool in value:
            if not _VARIABLE_RE.match(tool.replace("-", "_")):
                raise ValueError(f"invalid tool name {tool!r}")
        return value


class SkillProvenance(BaseModel):
    """Where a Skill came from and who stands behind its prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = "unspecified"
    created: str | None = None
    #: Free-text authorship note, e.g. that the prompt is original work, or the
    #: attribution required by the licence of any reused material.
    notes: str | None = None


class SkillManifest(BaseModel):
    """The parsed, validated ``skill.toml``."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: int
    skill: SkillMeta
    input: InputSpec = Field(default_factory=InputSpec)
    output: OutputSpec = Field(default_factory=OutputSpec)
    policy: PolicySpec = Field(default_factory=PolicySpec)
    variables: list[VariableSpec] = Field(default_factory=list)
    provenance: SkillProvenance = Field(default_factory=SkillProvenance)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("schema_version must be 1 or greater")
        if value > SKILL_SCHEMA_VERSION:
            raise ValueError(
                f"skill declares schema_version {value}, but this build understands "
                f"at most {SKILL_SCHEMA_VERSION}. Upgrade sobai to run it."
            )
        return value

    @field_validator("variables")
    @classmethod
    def _check_variables(cls, value: list[VariableSpec]) -> list[VariableSpec]:
        if len(value) > 16:
            raise ValueError("a skill may declare at most 16 variables")
        seen: set[str] = set()
        for spec in value:
            if spec.name in seen:
                raise ValueError(f"duplicate variable declaration: {spec.name!r}")
            seen.add(spec.name)
        return value

    def variable(self, name: str) -> VariableSpec | None:
        return next((v for v in self.variables if v.name == name), None)


class Skill(BaseModel):
    """A fully loaded Skill: manifest, prompt, assigned namespace, and digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: SkillManifest
    prompt: str
    #: Assigned by the loader from the load location, never from the manifest.
    namespace: str
    #: ``sha256:<hex>`` over the normalized manifest and prompt.
    digest: str

    @property
    def name(self) -> str:
        return self.manifest.skill.name

    @property
    def version(self) -> str:
        return self.manifest.skill.version

    @property
    def qualified_name(self) -> str:
        return qualify(self.namespace, self.name)

    @property
    def reference(self) -> str:
        """Human-readable identity used in plans, run records, and audit detail."""
        return f"{self.qualified_name}@{self.version}"


#: Alias kept for readability at call sites that talk about the *recommendation*
#: rather than an effective classification.
DataClassRecommendation = DataClass
