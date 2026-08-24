#!/usr/bin/env python3
"""Create the tag and GitHub Release for the version recorded in the tree.

The version is not decided here — it arrives already reviewed, because every
pull request carries its own bump (see ``scripts/check_version.py``). This script
only turns that reviewed version into a tag and a GitHub Release, and it refuses
to do anything surprising:

* an existing tag must point at the commit being released — a tag is never moved
  or rewritten;
* the version must be strictly newer than the newest existing release tag;
* release notes come from that version's reviewed ``CHANGELOG.md`` section, and
  an empty section is an error rather than an empty release.

``--check`` validates and reports without changing anything, writing ``tag``,
``version`` and ``needs_release`` to ``$GITHUB_OUTPUT`` when present. ``--publish``
performs the tag and release, reusing whatever already exists so a re-run after a
partial failure converges instead of failing. Every git and gh call uses an argv
array — never a shell string.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Importable both as ``scripts.release`` (tests, pythonpath = ".") and when run
# directly as ``python scripts/release.py``, where sys.path[0] is scripts/.
try:  # pragma: no cover - exercised by whichever entry point is used
    from scripts.check_version import VersionError, check_consistency
except ModuleNotFoundError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from check_version import VersionError, check_consistency
# New tags are plain ``vX.Y.Z``. The 0.1.0 tag Release Please created carries a
# ``sobatista-ai-`` component prefix (a monorepo convention this single-package
# repo never needed), so ordering still recognises it and the guard stays live.
_TAG_RE = re.compile(r"^(?:sobatista-ai-)?v(\d+)\.(\d+)\.(\d+)$")


class ReleaseError(Exception):
    """The tree is not in a state that may be released."""


def _run(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv array, never a shell string
        args, cwd=str(root), capture_output=True, text=True, check=False
    )


def read_version(root: Path) -> str:
    """Return the reviewed version, after full consistency validation."""
    try:
        return check_consistency(root)
    except VersionError as exc:
        raise ReleaseError(str(exc)) from exc


def release_notes(version: str, root: Path) -> str:
    """Return the body of that version's changelog section."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$(.*?)(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    notes = match[1].strip() if match else ""
    if not notes:
        raise ReleaseError(f"release notes for {version} are empty.")
    return notes


def tag_commit(tag: str, root: Path) -> str | None:
    """Return the commit a tag resolves to, or None when it does not exist."""
    result = _run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"], root)
    return result.stdout.strip() or None


def newest_tag(exclude: str, root: Path) -> str | None:
    """Return the highest existing ``vX.Y.Z`` tag, ignoring ``exclude``."""
    result = _run(["git", "tag", "--list"], root)
    versions = [
        (tuple(int(p) for p in m.groups()), line)
        for line in result.stdout.split()
        if line != exclude and (m := _TAG_RE.match(line))
    ]
    return max(versions)[1] if versions else None


@dataclass(frozen=True)
class Plan:
    version: str
    tag: str
    head: str
    needs_tag: bool
    needs_release: bool


def build_plan(root: Path, release_exists: bool = False) -> Plan:
    """Validate the tree and describe what publishing would do."""
    version = read_version(root)
    tag = f"v{version}"
    head = _run(["git", "rev-parse", "HEAD"], root).stdout.strip()
    release_notes(version, root)

    existing = tag_commit(tag, root)
    if existing is not None and existing != head:
        raise ReleaseError(
            f"tag {tag} already points at {existing[:12]}, not {head[:12]}. "
            "Refusing to move it — the version must be bumped instead. This "
            "usually means a pull request merged without its version increment."
        )

    previous = newest_tag(tag, root)
    if previous is not None:
        current = tuple(int(p) for p in version.split("."))
        if current <= tuple(int(p) for p in _TAG_RE.match(previous).groups()):  # type: ignore[union-attr]
            raise ReleaseError(f"version {version} is not newer than {previous}.")

    return Plan(
        version=version,
        tag=tag,
        head=head,
        needs_tag=existing is None,
        needs_release=not release_exists,
    )


def _release_exists(tag: str, root: Path) -> bool:
    return _run(["gh", "release", "view", tag], root).returncode == 0


def publish(plan: Plan, root: Path) -> None:
    """Create the tag and GitHub Release, reusing anything already present."""
    if plan.needs_tag:
        _check(_run(["git", "tag", "-a", plan.tag, "-m", f"SoBatista AI {plan.version}"], root))
        _check(_run(["git", "push", "origin", f"refs/tags/{plan.tag}"], root))
        print(f"created tag: {plan.tag}")
    else:
        print(f"tag already at this commit: {plan.tag}")

    if _release_exists(plan.tag, root):
        print(f"GitHub Release already exists: {plan.tag}")
        return
    notes_path = root / ".release-notes.md"
    notes_path.write_text(release_notes(plan.version, root), encoding="utf-8")
    try:
        _check(
            _run(
                [
                    "gh",
                    "release",
                    "create",
                    plan.tag,
                    "--title",
                    f"SoBatista AI {plan.version}",
                    "--notes-file",
                    str(notes_path),
                    "--verify-tag",
                ],
                root,
            )
        )
    finally:
        notes_path.unlink(missing_ok=True)
    print(f"created GitHub Release: {plan.tag}")


def _check(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        raise ReleaseError((result.stderr or result.stdout).strip())


def _emit_outputs(plan: Plan) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"tag={plan.tag}\n")
        handle.write(f"version={plan.version}\n")
        handle.write(f"needs_release={'true' if plan.needs_tag else 'false'}\n")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--check"
    if mode not in ("--check", "--publish") or len(argv) > 2:
        print("usage: release.py [--check|--publish]", file=sys.stderr)
        return 2
    try:
        plan = build_plan(_ROOT)
        _emit_outputs(plan)
        print(f"release check passed: {plan.tag} at {plan.head[:12]}")
        if mode == "--publish":
            publish(plan, _ROOT)
    except ReleaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
