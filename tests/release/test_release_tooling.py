"""Tests for the release helper scripts (version/tag, checksums, PR impact)."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_release_impact import is_release_pr, selected_impacts
from scripts.check_version_tag import read_project_version, tag_matches
from scripts.gen_checksums import SUMS_NAME, compute_checksums, render, write_sumfile


def test_read_project_version_from_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    assert read_project_version(pyproject) == "1.2.3"


@pytest.mark.parametrize(
    ("tag", "version", "expected"),
    [
        ("v0.1.0", "0.1.0", True),
        ("0.1.0", "0.1.0", True),
        ("v0.1.0.dev0", "0.1.0.dev0", True),
        ("v0.1.0a1", "0.1.0a1", True),
        ("v0.2.0", "0.1.0", False),
        ("v1.0.0", "0.1.0", False),
        ("garbage", "0.1.0", False),
    ],
)
def test_tag_matches(tag: str, version: str, expected: bool) -> None:
    assert tag_matches(tag, version) is expected


def test_repo_pyproject_version_readable() -> None:
    # The real project version must parse (guards against a malformed edit).
    assert read_project_version()


def test_selected_impacts_exactly_one() -> None:
    body = "## Release impact\n- [x] `minor` — new feature\n- [ ] `patch` — fix\n"
    assert selected_impacts(body) == ["minor"]


def test_selected_impacts_none() -> None:
    body = "- [ ] `major`\n- [ ] `minor`\n- [ ] `patch`\n- [ ] `none`\n"
    assert selected_impacts(body) == []


@pytest.mark.parametrize(
    "head_ref",
    [
        "release-please--branches--main",
        "release-please--branches--main--components--sobatista-ai",
    ],
)
def test_is_release_pr_true(head_ref: str) -> None:
    assert is_release_pr(head_ref) is True


@pytest.mark.parametrize(
    "head_ref",
    ["", "main", "feat/thing", "fix/release-please-notes"],
)
def test_is_release_pr_false(head_ref: str) -> None:
    assert is_release_pr(head_ref) is False


def test_selected_impacts_multiple() -> None:
    body = "- [x] `major`\n- [x] `patch`\n"
    assert set(selected_impacts(body)) == {"major", "patch"}


def test_checksums_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "a.whl").write_bytes(b"alpha")
    (tmp_path / "b.tar.gz").write_bytes(b"beta")
    sums = compute_checksums(tmp_path)
    assert set(sums) == {"a.whl", "b.tar.gz"}
    assert all(len(h) == 64 for h in sums.values())

    out = write_sumfile(tmp_path)
    assert out.name == SUMS_NAME
    text = out.read_text(encoding="utf-8")
    # Rendered lines use the "<hex>  <name>" coreutils format.
    assert "  a.whl\n" in text
    # The sums file itself must not be checksummed.
    assert SUMS_NAME not in compute_checksums(tmp_path)


def test_render_format() -> None:
    assert render({"x": "deadbeef"}) == "deadbeef  x\n"


def test_write_sumfile_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_sumfile(tmp_path)
