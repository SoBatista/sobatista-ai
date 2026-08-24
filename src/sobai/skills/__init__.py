"""Skills: versioned, inspectable task recipes that are prompt/data only.

A Skill is a *recipe*, never code. It is a TOML manifest plus a Markdown prompt,
content-addressed by a SHA-256 digest, loaded from packaged application
resources (``builtin:``) or from the user's own config directory (``user:``).

Skills deliberately cannot execute anything. They add no capability to the
system: a Skill prompt is always subordinate to the immutable SoBatista system
policy and can never enable a tool, raise a limit, change privacy policy,
request credentials, authorize writes, or bypass ``--local-only``. Everything a
Skill run does — provider selection, egress consent, redaction, usage
accounting, audit, timeouts, cancellation — goes through the existing core.

See :doc:`docs/skills` for the format and ``docs/adr/0007`` for why Skills are
not executable plugins.
"""

from .inputs import SkillInput, collect_input
from .installer import InstallResult, install_skill, validate_source
from .loader import load_builtin_skill, load_skill_directory, parse_skill
from .models import (
    SKILL_SCHEMA_VERSION,
    Namespace,
    Skill,
    SkillManifest,
    SkillProvenance,
    VariableSpec,
    VariableType,
    validate_skill_name,
)
from .plan import ModelResolution, SkillRunPlan, build_plan, resolve_skill_model
from .provenance import compute_digest
from .registry import SkillRegistry, discover_skills
from .renderer import RenderedPrompt, render_skill
from .runner import SkillRunResult, execute_skill

__all__ = [
    "SKILL_SCHEMA_VERSION",
    "InstallResult",
    "ModelResolution",
    "Namespace",
    "RenderedPrompt",
    "Skill",
    "SkillInput",
    "SkillManifest",
    "SkillProvenance",
    "SkillRegistry",
    "SkillRunPlan",
    "SkillRunResult",
    "VariableSpec",
    "VariableType",
    "build_plan",
    "collect_input",
    "compute_digest",
    "discover_skills",
    "execute_skill",
    "install_skill",
    "load_builtin_skill",
    "load_skill_directory",
    "parse_skill",
    "render_skill",
    "resolve_skill_model",
    "validate_skill_name",
    "validate_source",
]
