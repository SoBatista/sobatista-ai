"""Reading the primary input for a Skill run — bounded, typed, and untrusted.

Exactly one input source is used per run, and the choice is explicit:

* a positional argument,
* ``--file PATH``,
* piped stdin, used only when neither of the other two was given.

Supplying both a positional argument and ``--file`` is an error rather than a
silent precedence rule. When no source is available and stdin is a terminal, the
run fails immediately with instructions — it never blocks waiting for a human to
type, which is what makes ``sobai run`` safe to put in a script or CI job.

Input is data. Nothing here interprets it: no URL in the text is fetched, no
path in it is opened, no command in it is run. There is no code in this package
that could do any of those things.
"""

from __future__ import annotations

import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sobai.core.errors import SkillError

from .models import InputSpec
from .provenance import digest_bytes

InputSource = Literal["argument", "file", "stdin", "none"]


class SkillInputError(SkillError):
    """The input for a Skill run is missing, ambiguous, oversized, or not text."""


@dataclass(frozen=True, slots=True)
class SkillInput:
    """Validated primary input, described by size and hash rather than content."""

    text: str
    source: InputSource
    byte_size: int
    char_size: int
    #: ``sha256:<hex>`` of the raw bytes — provenance without disclosure.
    digest: str
    #: Basename only for a file source, so JSON output never leaks a home path.
    origin: str | None = None

    @property
    def present(self) -> bool:
        return self.source != "none"

    def describe(self) -> str:
        if self.source == "none":
            return "no input"
        where = f" ({self.origin})" if self.origin else ""
        return f"{self.source}{where}, {self.byte_size} bytes"


def _empty() -> SkillInput:
    return SkillInput(
        text="",
        source="none",
        byte_size=0,
        char_size=0,
        digest=digest_bytes(b""),
    )


def _decode(data: bytes, *, source: InputSource, origin: str | None, spec: InputSpec) -> SkillInput:
    """Decode and bound raw input bytes."""
    if len(data) > spec.max_bytes:
        raise SkillInputError(
            f"input is {len(data)} bytes, over this skill's limit of {spec.max_bytes}.",
            hint="Trim the input, or split it and run the skill on each part.",
        )
    if b"\x00" in data:
        raise SkillInputError(
            "input contains NUL bytes, so it is binary rather than text.",
            hint="Skills read UTF-8 text. Extract the text first (e.g. with `pdftotext`).",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillInputError(
            f"input is not valid UTF-8 ({exc.reason} at byte {exc.start}).",
            hint="Convert it to UTF-8 first, e.g. with `iconv -t utf-8`.",
        ) from exc
    text = text.removeprefix("﻿")
    if len(text) > spec.max_chars:
        raise SkillInputError(
            f"input decodes to {len(text)} characters, over this skill's limit "
            f"of {spec.max_chars}.",
            hint="Trim the input, or split it and run the skill on each part.",
        )
    return SkillInput(
        text=text,
        source=source,
        byte_size=len(data),
        char_size=len(text),
        digest=digest_bytes(data),
        origin=origin,
    )


def read_file_input(path: Path, spec: InputSpec) -> SkillInput:
    """Read *path* as bounded UTF-8 text."""
    resolved = path.expanduser()
    try:
        info = resolved.stat()
    except OSError as exc:
        raise SkillInputError(
            f"cannot read {resolved}: {exc.strerror or exc}.",
            hint="Check the path exists and is readable.",
        ) from exc
    if stat.S_ISDIR(info.st_mode):
        raise SkillInputError(
            f"{resolved} is a directory.",
            hint="Pass a single text file to --file.",
        )
    if not stat.S_ISREG(info.st_mode):
        # Character devices and FIFOs can block forever or stream without end.
        raise SkillInputError(
            f"{resolved} is not a regular file.",
            hint="Pass a regular text file, or pipe the data on stdin.",
        )
    if info.st_size > spec.max_bytes:
        raise SkillInputError(
            f"{resolved.name} is {info.st_size} bytes, over this skill's limit "
            f"of {spec.max_bytes}.",
            hint="Trim the file, or split it and run the skill on each part.",
        )
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise SkillInputError(f"cannot read {resolved}: {exc.strerror or exc}.") from exc
    return _decode(data, source="file", origin=resolved.name, spec=spec)


def read_stdin_input(spec: InputSpec) -> SkillInput:
    """Read piped stdin, bounded by the Skill's byte limit."""
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:  # pragma: no cover - exercised only by exotic stdin shims
        data = sys.stdin.read().encode("utf-8", errors="surrogateescape")
    else:
        # Read one byte past the limit so an oversized stream is reported rather
        # than silently truncated.
        data = stream.read(spec.max_bytes + 1)
    return _decode(data, source="stdin", origin=None, spec=spec)


def stdin_is_pipe() -> bool:
    """True when stdin is redirected, so reading it will not block on a human."""
    try:
        return not sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - closed/detached stdin
        return False


def collect_input(
    spec: InputSpec,
    *,
    positional: str | None = None,
    file: Path | None = None,
    allow_stdin: bool = True,
) -> SkillInput:
    """Resolve the single input source for this run, or raise an actionable error."""
    text = (positional or "").strip()
    has_positional = bool(text) and text != "-"
    explicit = [name for name, given in (("input", has_positional), ("--file", file)) if given]
    if len(explicit) > 1:
        raise SkillInputError(
            f"{' and '.join(explicit)} were both given.",
            hint="Pass the text, or --file PATH, or pipe on stdin — exactly one.",
        )

    if file is not None:
        return read_file_input(file, spec)
    if has_positional:
        data = text.encode("utf-8")
        return _decode(data, source="argument", origin=None, spec=spec)
    if allow_stdin and stdin_is_pipe():
        piped = read_stdin_input(spec)
        if piped.text.strip():
            return piped
        if spec.required:
            raise SkillInputError(
                "stdin was empty.",
                hint="Pipe the material to process, e.g. `cat notes.md | sobai run NAME`.",
            )
        return _empty()
    if spec.required:
        raise SkillInputError(
            "no input was supplied.",
            hint='Pass text ("..."), use --file PATH, or pipe on stdin '
            "(e.g. `cat article.md | sobai run NAME`).",
        )
    return _empty()
