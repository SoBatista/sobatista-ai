#!/usr/bin/env python3
"""Validate that a pull request declares exactly one release impact.

The PR body is read from the ``PR_BODY`` environment variable (never from the
command line) so untrusted content cannot be interpreted as shell. Used by
``.github/workflows/pr-release-impact.yml`` and unit-tested directly.
"""

from __future__ import annotations

import os
import re
import sys

IMPACTS = ("major", "minor", "patch", "none")


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
