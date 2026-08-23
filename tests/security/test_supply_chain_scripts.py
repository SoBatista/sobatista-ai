"""Tests for the supply-chain helper scripts (secret scan, licenses, links)."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.check_doc_links import check_file, extract_targets, is_external
from scripts.check_licenses import classify
from scripts.secret_scan import ALLOW_MARKER, scan_file, scan_tree

# Built by concatenation so this test file never itself contains a full match.
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_GH = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789AB"
FAKE_ANTHROPIC = "sk-ant-" + "abcdefghijklmnopqrstuvwxyz012345"


def test_secret_scan_detects_known_formats(tmp_path: Path) -> None:
    (tmp_path / "leak.txt").write_text(
        f"key={FAKE_AWS}\ntoken={FAKE_GH}\nanthropic={FAKE_ANTHROPIC}\n",
        encoding="utf-8",
    )
    findings = scan_tree(tmp_path)
    labels = {label for _, _, label in findings}
    assert "AWS access key id" in labels
    assert "GitHub token" in labels
    assert "Anthropic API key" in labels


def test_secret_scan_clean_file(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 'hello world'\n", encoding="utf-8")
    assert scan_tree(tmp_path) == []


def test_secret_scan_respects_allow_marker(tmp_path: Path) -> None:
    f = tmp_path / "fixture.txt"
    f.write_text(f"# {ALLOW_MARKER}\nkey={FAKE_AWS}\n", encoding="utf-8")
    assert scan_file(f) == []


def test_secret_scan_skips_binary(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + FAKE_AWS.encode())
    assert scan_tree(tmp_path) == []


def test_repo_is_secret_clean() -> None:
    # The real repository must be clean under the deterministic scan.
    assert scan_tree(Path(__file__).resolve().parent.parent.parent) == []


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ("MIT License", "ok"),
        ("License :: OSI Approved :: MIT License", "ok"),
        ("Apache-2.0", "ok"),
        ("BSD-3-Clause", "ok"),
        ("GNU General Public License v3 (GPLv3)", "denied"),
        ("GPL-3.0-or-later", "denied"),
        ("LGPLv2", "denied"),
        ("GNU Affero General Public License v3", "denied"),
        ("", "unknown"),
        ("   ", "unknown"),
    ],
)
def test_license_classify(text: str, verdict: str) -> None:
    assert classify(text) == verdict


def test_doc_links_external_and_extraction() -> None:
    assert is_external("https://example.com")
    assert is_external("#section")
    assert is_external("mailto:x@example.com")
    assert not is_external("./other.md")
    text = "See [a](a.md) and [b](https://x.y) and `[c](c.md)`.\n```\n[d](d.md)\n```\n"
    targets = extract_targets(text)
    assert "a.md" in targets
    assert "c.md" not in targets  # inline code ignored
    assert "d.md" not in targets  # fenced code ignored


def test_doc_links_broken_detection(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("hi\n", encoding="utf-8")
    src = tmp_path / "index.md"
    src.write_text(
        "[ok](target.md)\n[bad](missing.md)\n[ext](https://x.y)\n[anchor](#top)\n",
        encoding="utf-8",
    )
    broken = check_file(src)
    assert [t for _, t in broken] == ["missing.md"]


def test_repo_docs_links_resolve() -> None:
    # Every internal Markdown link in the repo must resolve.
    from scripts.check_doc_links import iter_markdown

    root = Path(__file__).resolve().parent.parent.parent
    broken: list[str] = []
    for md in iter_markdown(root):
        broken.extend(f"{md}: {t}" for _, t in check_file(md))
    assert broken == [], broken
