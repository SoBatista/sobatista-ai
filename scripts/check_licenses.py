#!/usr/bin/env python3
"""Enforce a license policy on installed runtime dependencies.

Copyleft licenses (GPL / AGPL / LGPL) are incompatible with this MIT project's
redistribution model. This scans the metadata of every installed distribution
(the CI job installs runtime dependencies only) and fails if any is copyleft.
Unknown/unstated licenses are reported but not failed on. Used by
``.github/workflows/security.yml`` and unit-tested directly.
"""

from __future__ import annotations

import sys
from importlib import metadata

# Substrings (case-insensitive) that indicate a disallowed copyleft license.
DENY_SUBSTRINGS = (
    "gnu general public license",
    "affero",
    "agpl",
    "lgpl",
    "lesser general public license",
    "gpl-2",
    "gpl-3",
    "gplv2",
    "gplv3",
    " gpl",
)

# Our own package is exempt (it is MIT and is the subject, not a dependency).
SELF = {"sobatista-ai", "sobatista_ai"}


def _license_text(name: str, meta: metadata.PackageMetadata) -> str:
    parts: list[str] = []
    for key in ("License-Expression", "License"):
        value = meta.get(key)
        if value:
            parts.append(str(value))
    classifiers = meta.get_all("Classifier") or []
    parts.extend(str(c) for c in classifiers if str(c).startswith("License ::"))
    return "\n".join(parts)


def classify(license_text: str) -> str:
    """Return 'denied', 'unknown', or 'ok' for a license description."""
    lowered = license_text.lower()
    if not lowered.strip():
        return "unknown"
    if any(token in lowered for token in DENY_SUBSTRINGS):
        return "denied"
    return "ok"


def evaluate() -> tuple[list[str], list[str]]:
    """Return (denied, unknown) distribution descriptions."""
    denied: list[str] = []
    unknown: list[str] = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name or name.lower() in SELF:
            continue
        text = _license_text(name, dist.metadata)
        verdict = classify(text)
        summary = text.replace("\n", " | ") or "<none stated>"
        if verdict == "denied":
            denied.append(f"{name}: {summary}")
        elif verdict == "unknown":
            unknown.append(f"{name}: {summary}")
    return sorted(set(denied)), sorted(set(unknown))


def main() -> int:
    denied, unknown = evaluate()
    for entry in unknown:
        print(f"::notice::license unknown for {entry}")
    if denied:
        print("ERROR: disallowed copyleft license(s) detected:", file=sys.stderr)
        for entry in denied:
            print(f"  - {entry}", file=sys.stderr)
        return 1
    print("License policy OK: no copyleft runtime dependencies detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
