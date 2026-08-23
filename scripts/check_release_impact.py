#!/usr/bin/env python3
"""Validate that a pull request declares exactly one release impact.

The PR body is read from the ``PR_BODY`` environment variable (never from the
command line) so untrusted content cannot be interpreted as shell. The head
branch is read from ``PR_HEAD_REF`` the same way. Used by
``.github/workflows/pr-release-impact.yml`` and unit-tested directly.
"""

from __future__ import annotations

import os
import re
import sys

IMPACTS = ("major", "minor", "patch", "none")

# Release Please composes its release-PR body from the changelog, so it can never
# carry the template's checkboxes. Those PRs are exempt: their release impact is
# already derived from the Conventional Commits they roll up.
RELEASE_BRANCH_PREFIX = "release-please--"


def is_release_pr(head_ref: str) -> bool:
    """Return True when ``head_ref`` is a Release Please-generated branch."""
    return head_ref.startswith(RELEASE_BRANCH_PREFIX)


def selected_impacts(body: str) -> list[str]:
    """Return the release impacts whose checkbox is ticked in ``body``."""
    found: list[str] = []
    for impact in IMPACTS:
        # Matches e.g. "- [x] `minor` — ..." (case-insensitive on the mark).
        pattern = re.compile(rf"-\s*\[[xX]\]\s*`{impact}`")
        if pattern.search(body):
            found.append(impact)
    return found


def main() -> int:
    head_ref = os.environ.get("PR_HEAD_REF", "")
    if is_release_pr(head_ref):
        print(f"Release Please PR ({head_ref}); impact comes from the commits it rolls up.")
        return 0
    body = os.environ.get("PR_BODY", "")
    chosen = selected_impacts(body)
    if len(chosen) == 1:
        print(f"Release impact declared: {chosen[0]}")
        return 0
    if not chosen:
        print(
            "ERROR: no release impact selected. Tick exactly one of "
            "`major` / `minor` / `patch` / `none` in the PR template.",
            file=sys.stderr,
        )
    else:
        print(
            f"ERROR: multiple release impacts selected ({', '.join(chosen)}). Tick exactly one.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
