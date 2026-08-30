"""Loading and validating Skills from packaged resources or the filesystem.

Two entry points, with deliberately different trust:

* :func:`load_builtin_skill` reads the Skill pack shipped inside the installed
  package via :mod:`importlib.resources`, so it works identically from a wheel,
  an sdist, or a source checkout.
* :func:`load_skill_directory` reads a directory on disk and treats it as
  hostile: symlinks, hard links, non-regular files, unexpected entries,
  oversized files, invalid encodings, and names that disagree with the manifest
  are all refused *before* anything is parsed.

Both funnel into :func:`parse_skill`, which is pure and does no I/O — that is
what makes the whole surface cheap to fuzz.

One rule is unusual and worth stating: a Skill's text must be **visually
honest**. Terminal escapes, stray control bytes, and Unicode bidirectional
controls are rejected outright rather than stripped, because a prompt that
renders differently from how it reads is a prompt no reviewer can approve.
"""

from __future__ import annotations

import os
import stat
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sobai.core.errors import SkillError

from .models import Namespace, Skill, SkillManifest, SkillNameError, validate_skill_name
from .provenance import compute_digest, normalize_prompt

MANIFEST_FILENAME = "skill.toml"
PROMPT_FILENAME = "prompt.md"

#: The complete set of files a Skill directory may contain. Anything else is an
#: error, not something to ignore: an unexpected file is either a mistake or an
#: attempt to smuggle content past review.
ALLOWED_FILENAMES: frozenset[str] = frozenset({MANIFEST_FILENAME, PROMPT_FILENAME})
REQUIRED_FILENAMES: tuple[str, ...] = (MANIFEST_FILENAME, PROMPT_FILENAME)

MAX_MANIFEST_BYTES = 65_536
MAX_PROMPT_BYTES = 262_144

#: The package holding the built-in Skill pack.
BUILTIN_PACKAGE = "sobai.skills.builtin"

# Control characters permitted in Skill text: tab, newline, carriage return.
_ALLOWED_CONTROL = frozenset({0x09, 0x0A, 0x0D})
# Unicode bidirectional and directional format controls (the "Trojan Source"
# class). Rejected in Skill text so a prompt cannot read one way and mean
# another. Mirrors the display-time defence in :mod:`sobai.core.safeterm`.
_BIDI_CONTROLS = frozenset("‎‏؜‪‫‬‭‮⁦⁧⁨⁩")


class SkillLoadError(SkillError):
    """A Skill could not be loaded, and why."""


def _fail(message: str, *, hint: str | None = None) -> SkillLoadError:
    return SkillLoadError(message, hint=hint)


# -- text safety -----------------------------------------------------------
def decode_skill_text(data: bytes, *, what: str, limit: int) -> str:
    """Decode *data* as strict UTF-8 text suitable for a Skill, or raise.

    Rejects oversized content, binary content, invalid encodings, and text that
    carries control or bidirectional-format characters.
    """
    if len(data) > limit:
        raise _fail(
            f"{what} is {len(data)} bytes, over the {limit}-byte limit.",
            hint=f"Shorten {what} or split the skill into smaller ones.",
        )
    if b"\x00" in data:
        raise _fail(
            f"{what} contains NUL bytes and is not text.",
            hint="A skill must be a UTF-8 text file.",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail(
            f"{what} is not valid UTF-8 ({exc.reason} at byte {exc.start}).",
            hint="Re-save the file as UTF-8.",
        ) from exc
    text = text.removeprefix("﻿")
    assert_reviewable_text(text, what=what)
    return text


def assert_reviewable_text(text: str, *, what: str) -> None:
    """Raise unless *text* renders exactly as it reads."""
    for index, char in enumerate(text):
        code = ord(char)
        if code < 0x20 and code not in _ALLOWED_CONTROL:
            raise _fail(
                f"{what} contains a control character (U+{code:04X}) at offset {index}.",
                hint="Remove terminal escape and control characters from the skill.",
            )
        if code == 0x7F or 0x80 <= code <= 0x9F:
            raise _fail(
                f"{what} contains a control character (U+{code:04X}) at offset {index}.",
                hint="Remove terminal escape and control characters from the skill.",
            )
        if char in _BIDI_CONTROLS:
            raise _fail(
                f"{what} contains a Unicode bidirectional control (U+{code:04X}) at "
                f"offset {index}, which can make the prompt display differently from "
                "how it reads.",
                hint="Remove Unicode directional formatting characters from the skill.",
            )


# -- pure parsing ----------------------------------------------------------
def parse_manifest(data: bytes) -> SkillManifest:
    """Parse and validate ``skill.toml`` bytes into a typed manifest."""
    text = decode_skill_text(data, what=MANIFEST_FILENAME, limit=MAX_MANIFEST_BYTES)
    try:
        raw: dict[str, Any] = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _fail(
            f"{MANIFEST_FILENAME} is not valid TOML: {exc}",
            hint="Fix the TOML syntax; see `sobai skills validate PATH`.",
        ) from exc
    try:
        return SkillManifest.model_validate(raw)
    except ValidationError as exc:
        raise _fail(
            f"{MANIFEST_FILENAME} is invalid: {_format_validation_error(exc)}",
            hint="See the skill authoring guide for the manifest schema.",
        ) from exc


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(p) for p in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def parse_skill(
    manifest_bytes: bytes,
    prompt_bytes: bytes,
    *,
    namespace: str,
    expected_name: str | None = None,
) -> Skill:
    """Build a validated :class:`Skill` from raw manifest and prompt bytes.

    Pure: no filesystem, network, or environment access. ``namespace`` is
    supplied by the caller from *where the bytes came from* — it is never read
    from the manifest, so a user Skill cannot claim to be a built-in.
    """
    manifest = parse_manifest(manifest_bytes)
    prompt_text = decode_skill_text(prompt_bytes, what=PROMPT_FILENAME, limit=MAX_PROMPT_BYTES)
    prompt = normalize_prompt(prompt_text)
    if not prompt.strip():
        raise _fail(
            f"{PROMPT_FILENAME} is empty.",
            hint="A skill needs prompt instructions.",
        )
    if expected_name is not None and manifest.skill.name != expected_name:
        raise _fail(
            f"skill directory is named {expected_name!r} but the manifest declares "
            f"{manifest.skill.name!r}.",
            hint="Rename the directory to match the manifest's skill name.",
        )
    return Skill(
        manifest=manifest,
        prompt=prompt,
        namespace=namespace,
        digest=compute_digest(manifest, prompt),
    )


# -- filesystem loading (untrusted) ---------------------------------------
def _lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise _fail(f"cannot read {path.name}: {exc.strerror or exc}.") from exc


def assert_safe_directory(path: Path) -> None:
    """Raise unless *path* is a real, non-symlinked directory we may read."""
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise _fail(
            f"{path} is a symbolic link.",
            hint="Point at the real skill directory; symlinks are refused.",
        )
    if not stat.S_ISDIR(info.st_mode):
        raise _fail(
            f"{path} is not a directory.",
            hint=f"A skill is a directory containing {MANIFEST_FILENAME} and {PROMPT_FILENAME}.",
        )


def assert_safe_file(path: Path) -> None:
    """Raise unless *path* is a plain, unshared regular file."""
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise _fail(
            f"{path.name} is a symbolic link.",
            hint="Skill files must be regular files, not links.",
        )
    if not stat.S_ISREG(info.st_mode):
        raise _fail(
            f"{path.name} is not a regular file.",
            hint="Devices, FIFOs, and sockets are refused.",
        )
    # A hard link means the same inode is reachable under another name, so the
    # reviewed content can be swapped without touching this directory. Detected
    # where the filesystem reports it; not detectable everywhere, hence the
    # digest as the authoritative identity.
    if info.st_nlink > 1:
        raise _fail(
            f"{path.name} has {info.st_nlink} hard links.",
            hint="Copy the skill to a fresh directory before installing it.",
        )


def read_skill_files(path: Path) -> tuple[bytes, bytes]:
    """Return ``(manifest_bytes, prompt_bytes)`` from a validated Skill directory."""
    assert_safe_directory(path)
    present: set[str] = set()
    for entry in sorted(path.iterdir(), key=lambda p: p.name):
        name = entry.name
        if name in ALLOWED_FILENAMES:
            present.add(name)
            continue
        # A case variant resolves to the required file on a case-insensitive
        # filesystem and to a stray extra file on a case-sensitive one. Either
        # way it is ambiguous about which bytes were reviewed.
        folded = name.casefold()
        if folded in ALLOWED_FILENAMES:
            raise _fail(
                f"{name!r} differs only in case from {folded!r} in skill directory {path.name}.",
                hint="Skill filenames are lowercase; keep exactly one of each.",
            )
        raise _fail(
            f"unexpected entry {name!r} in skill directory {path.name}.",
            hint=f"A skill contains exactly {MANIFEST_FILENAME} and {PROMPT_FILENAME}.",
        )
    missing = [f for f in REQUIRED_FILENAMES if f not in present]
    if missing:
        raise _fail(
            f"skill directory {path.name} is missing {', '.join(missing)}.",
            hint="An installation may have been interrupted; re-install the skill.",
        )
    payloads: list[bytes] = []
    for filename in REQUIRED_FILENAMES:
        file_path = path / filename
        assert_safe_file(file_path)
        try:
            payloads.append(file_path.read_bytes())
        except OSError as exc:
            raise _fail(f"cannot read {filename}: {exc.strerror or exc}.") from exc
    return payloads[0], payloads[1]


def load_skill_directory(
    path: Path,
    *,
    namespace: str = Namespace.USER,
    require_matching_name: bool = True,
) -> Skill:
    """Load and validate a Skill from an untrusted directory on disk."""
    resolved = path.expanduser()
    manifest_bytes, prompt_bytes = read_skill_files(resolved)
    expected: str | None = None
    if require_matching_name:
        expected = resolved.name
        try:
            validate_skill_name(expected)
        except SkillNameError as exc:
            raise _fail(
                f"skill directory name {expected!r} is not a valid skill name: {exc}",
                hint="Rename the directory, e.g. 'security-report'.",
            ) from exc
    return parse_skill(
        manifest_bytes,
        prompt_bytes,
        namespace=namespace,
        expected_name=expected,
    )


# -- packaged built-ins (trusted, but still validated) --------------------
def builtin_root() -> Traversable:
    """Return the packaged built-in Skill directory as a resource traversable."""
    return files(BUILTIN_PACKAGE)


def builtin_names() -> list[str]:
    """List the Skill names shipped inside the installed package."""
    names: list[str] = []
    for entry in builtin_root().iterdir():
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        if not entry.joinpath(MANIFEST_FILENAME).is_file():
            continue
        names.append(entry.name)
    return sorted(names)


def load_builtin_skill(name: str) -> Skill:
    """Load one built-in Skill from packaged resources (wheel, sdist, or source)."""
    validate_skill_name(name)
    directory = builtin_root().joinpath(name)
    if not directory.is_dir():
        raise _fail(f"no built-in skill named {name!r}.")
    try:
        manifest_bytes = directory.joinpath(MANIFEST_FILENAME).read_bytes()
        prompt_bytes = directory.joinpath(PROMPT_FILENAME).read_bytes()
    except (OSError, FileNotFoundError) as exc:
        raise _fail(f"built-in skill {name!r} is incomplete: {exc}") from exc
    return parse_skill(
        manifest_bytes,
        prompt_bytes,
        namespace=Namespace.BUILTIN,
        expected_name=name,
    )
