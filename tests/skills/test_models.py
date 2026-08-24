"""Manifest schema, schema versioning, and the portable-name syntax."""

from __future__ import annotations

import pytest

from sobai.core.classification import DataClass
from sobai.skills.loader import parse_manifest, parse_skill
from sobai.skills.models import (
    SKILL_SCHEMA_VERSION,
    Namespace,
    SkillNameError,
    validate_skill_name,
    validate_variable_name,
)

from .conftest import MINIMAL_PROMPT, manifest_toml


# -- names -----------------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    ["summarize", "extract-insights", "a1", "security-review-2", "x" * 64],
)
def test_valid_skill_names(name: str) -> None:
    assert validate_skill_name(name) == name


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("", "empty"),
        ("x" * 65, "too long"),
        ("Summarize", "uppercase"),
        ("summarize_v2", "underscore"),
        ("summar ize", "whitespace"),
        ("../etc/passwd", "traversal"),
        ("..", "traversal"),
        (".", "current directory"),
        ("a/b", "posix separator"),
        ("a\\b", "windows separator"),
        ("a:b", "namespace separator"),
        ("-leading", "leading hyphen"),
        ("trailing-", "trailing hyphen"),
        ("double--hyphen", "consecutive hyphens"),
        ("sum\x00marize", "NUL byte"),
        ("sum\nmarize", "newline"),
        ("sum\x1b[31marize", "ANSI escape"),
        ("summariz\u00e9", "non-ASCII"),
        ("\u0441\u0443\u043c\u043c\u0430\u0440ize", "Cyrillic confusables"),
        ("\uff53ummarize", "fullwidth confusable"),
        ("1summarize", "leading digit"),
    ],
)
def test_rejected_skill_names(name: str, why: str) -> None:
    with pytest.raises(SkillNameError):
        validate_skill_name(name)


@pytest.mark.parametrize("name", ["builtin", "user", "skills", "con", "nul", "com1", "lpt9"])
def test_reserved_skill_names_rejected(name: str) -> None:
    with pytest.raises(SkillNameError, match="reserved"):
        validate_skill_name(name)


@pytest.mark.parametrize("name", ["language", "target_language", "n1"])
def test_valid_variable_names(name: str) -> None:
    assert validate_variable_name(name) == name


@pytest.mark.parametrize("name", ["", "Language", "lang-uage", "x" * 33, "1a", "lang.sub"])
def test_rejected_variable_names(name: str) -> None:
    with pytest.raises(SkillNameError):
        validate_variable_name(name)


def test_input_is_a_reserved_variable_name() -> None:
    """`input` is the separate untrusted channel, never a template variable."""
    with pytest.raises(SkillNameError, match="reserved"):
        validate_variable_name("input")


# -- manifest parsing ------------------------------------------------------
def test_parses_a_complete_manifest() -> None:
    manifest = parse_manifest(manifest_toml().encode())
    assert manifest.schema_version == SKILL_SCHEMA_VERSION
    assert manifest.skill.name == "demo"
    assert manifest.skill.license == "MIT"
    assert manifest.policy.recommended_data_class is DataClass.INTERNAL
    assert manifest.policy.required_tools == []
    assert manifest.input.max_bytes == 4096


def test_manifest_defaults_are_conservative() -> None:
    minimal = b"""
schema_version = 1
[skill]
name = "minimal"
version = "0.1.0"
description = "Only the required fields."
"""
    manifest = parse_manifest(minimal)
    assert manifest.skill.license == "private", "an unlicensed skill defaults to private"
    assert manifest.policy.recommended_data_class is DataClass.INTERNAL
    assert manifest.policy.required_tools == []
    assert manifest.variables == []


def test_unknown_manifest_key_is_refused() -> None:
    """A field this build does not understand must not be silently ignored."""
    body = manifest_toml() + "\n[skill_extras]\nallow_shell = true\n"
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(body.encode())


def test_manifest_cannot_declare_a_provider_model() -> None:
    body = manifest_toml() + '\n[model]\nid = "some-vendor-model-v3"\n'
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(body.encode())


def test_manifest_cannot_claim_a_namespace() -> None:
    body = manifest_toml().replace(
        '[skill]\nname = "demo"',
        '[skill]\nnamespace = "builtin"\nname = "demo"',
    )
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(body.encode())


def test_future_schema_version_is_refused_with_an_upgrade_hint() -> None:
    body = manifest_toml(schema_version=SKILL_SCHEMA_VERSION + 1)
    with pytest.raises(Exception, match="Upgrade sobai"):
        parse_manifest(body.encode())


def test_schema_version_zero_is_refused() -> None:
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(manifest_toml(schema_version=0).encode())


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-rc1", "", "1.0.0.1"])
def test_skill_version_must_be_exact_semver(version: str) -> None:
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(manifest_toml(version=version).encode())


def test_empty_description_is_refused() -> None:
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(manifest_toml(description="   ").encode())


def test_duplicate_variable_declaration_is_refused() -> None:
    extra = """
[[variables]]
name = "language"
type = "string"

[[variables]]
name = "language"
type = "string"
"""
    with pytest.raises(Exception, match="duplicate variable"):
        parse_manifest(manifest_toml(extra=extra).encode())


def test_input_limits_are_capped_by_the_build() -> None:
    """A skill may lower its own limits but never raise them past the ceiling."""
    body = manifest_toml().replace("max_bytes = 4096", "max_bytes = 999999999")
    with pytest.raises(Exception, match="invalid"):
        parse_manifest(body.encode())


def test_namespace_comes_from_the_loader_not_the_manifest() -> None:
    skill = parse_skill(
        manifest_toml().encode(),
        MINIMAL_PROMPT.encode(),
        namespace=Namespace.BUILTIN,
    )
    assert skill.namespace == Namespace.BUILTIN
    assert skill.qualified_name == "builtin:demo"
    assert skill.reference == "builtin:demo@1.0.0"


def test_directory_name_must_match_the_manifest_name() -> None:
    with pytest.raises(Exception, match="manifest declares"):
        parse_skill(
            manifest_toml(name="demo").encode(),
            MINIMAL_PROMPT.encode(),
            namespace=Namespace.USER,
            expected_name="something-else",
        )
