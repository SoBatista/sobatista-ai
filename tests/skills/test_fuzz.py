"""Deterministic fuzz-style property tests for names, paths, and the renderer.

Seeded ``random`` rather than a property-testing dependency: the repository is
deliberate about its dependency surface, and a fixed seed gives reproducible
counter-examples without adding one. Each test states the invariant it is
checking, so a failure names the broken property rather than a random string.
"""

from __future__ import annotations

import random
import string
from pathlib import Path

import pytest

from sobai.core.errors import SkillError
from sobai.skills.loader import decode_skill_text
from sobai.skills.models import (
    RESERVED_NAMES,
    SkillNameError,
    validate_skill_name,
    validate_variable_name,
)
from sobai.skills.renderer import (
    INPUT_BEGIN,
    INPUT_END,
    SkillRenderError,
    defang_input,
    placeholders,
    substitute,
)

ITERATIONS = 500

#: A deliberately nasty alphabet: separators, traversal, control bytes,
#: confusables, quoting, and template syntax.
HOSTILE_ALPHABET = (
    string.ascii_letters
    + string.digits
    + "-_. /\\:;,'\"`$(){}[]<>|&*?!#%^~+=@\t\n\r\x00\x1b\x7f"
    + "‮​асｓé中"
)


def _random_string(rng: random.Random, alphabet: str = HOSTILE_ALPHABET) -> str:
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))


# -- names -----------------------------------------------------------------
def test_accepted_names_are_always_safe_path_components(tmp_path: Path) -> None:
    """Anything validate_skill_name accepts must stay inside its parent directory."""
    rng = random.Random(20260824)
    root = tmp_path.resolve()
    accepted = 0
    for _ in range(ITERATIONS):
        candidate = _random_string(rng)
        try:
            name = validate_skill_name(candidate)
        except SkillNameError:
            continue
        accepted += 1
        assert name == candidate, "validation must not silently rewrite a name"
        assert name.isascii()
        assert not set(name) & set("/\\:. \t\n\r\x00")
        assert name not in RESERVED_NAMES
        # The decisive property: it can only ever name a direct child.
        resolved = (root / name).resolve()
        assert resolved.parent == root
        assert resolved != root
    assert accepted > 0, "the generator must produce some valid names"


def test_names_built_from_the_legal_alphabet_are_accepted() -> None:
    """The complement: well-formed names are not rejected by accident."""
    rng = random.Random(7)
    legal = string.ascii_lowercase + string.digits
    for _ in range(ITERATIONS):
        parts = [
            "".join(rng.choice(legal) for _ in range(rng.randint(1, 6)))
            for _ in range(rng.randint(1, 3))
        ]
        candidate = "-".join(parts)
        if not candidate[0].isalpha() or candidate in RESERVED_NAMES:
            continue
        assert validate_skill_name(candidate) == candidate


def test_name_validation_never_raises_an_unexpected_exception() -> None:
    rng = random.Random(99)
    for _ in range(ITERATIONS):
        candidate = _random_string(rng)
        try:
            validate_skill_name(candidate)
            validate_variable_name(candidate)
        except SkillNameError:
            pass


@pytest.mark.parametrize(
    "traversal",
    ["..", "../..", "a/../..", "%2e%2e", "..%2f", "....//", "\\..\\", "a\x00/..", "./."],
)
def test_traversal_shapes_are_never_accepted(traversal: str) -> None:
    with pytest.raises(SkillNameError):
        validate_skill_name(traversal)


# -- decoding --------------------------------------------------------------
def test_decoding_arbitrary_bytes_either_succeeds_or_raises_a_skill_error() -> None:
    rng = random.Random(4242)
    for _ in range(ITERATIONS):
        data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))
        try:
            text = decode_skill_text(data, what="fuzz", limit=4096)
        except SkillError:
            continue
        # Anything accepted must be reviewable: no control or bidi characters.
        assert all(ord(c) >= 0x20 or c in "\t\n\r" for c in text)
        assert "‮" not in text


# -- renderer --------------------------------------------------------------
def test_placeholder_scanning_never_accepts_a_non_bare_name() -> None:
    rng = random.Random(1234)
    for _ in range(ITERATIONS):
        template = _random_string(rng, HOSTILE_ALPHABET + "{}")
        try:
            names = placeholders(template)
        except SkillRenderError:
            continue
        for name in names:
            assert name.isascii()
            assert name.replace("_", "a").isalnum()
            assert name[0].islower()


def test_substitution_is_single_pass_for_arbitrary_values() -> None:
    """A value is inserted, never rescanned — whatever it contains."""
    rng = random.Random(555)
    for _ in range(ITERATIONS):
        payload = _random_string(rng, HOSTILE_ALPHABET + "{}%")
        rendered = substitute("[{{a}}]", {"a": payload})
        assert rendered == f"[{payload}]"


def test_defanging_leaves_exactly_one_pair_of_boundary_markers() -> None:
    """Untrusted input can never close or reopen its own block."""
    rng = random.Random(31337)
    fragments = [INPUT_BEGIN, INPUT_END, "text", "\n", "<<<", ">>>", "SOBAI"]
    for _ in range(ITERATIONS):
        hostile = "".join(rng.choice(fragments) for _ in range(rng.randint(0, 12)))
        body = f"{INPUT_BEGIN}\n{defang_input(hostile)}\n{INPUT_END}"
        assert body.count(INPUT_BEGIN) == 1
        assert body.count(INPUT_END) == 1
