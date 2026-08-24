"""Content addressing: the stable SHA-256 digest that identifies a Skill.

The digest is computed over a *normalized* form of the manifest and prompt, so
the same Skill content always yields the same digest regardless of TOML key
order, comment placement, line endings, or trailing whitespace. It is the
identity you can quote in a review, a run record, or an audit trail.

The digest covers exactly the content the author shipped and nothing about this
machine's copy of it, so ``sobai skills validate ./my-skill`` and
``sobai skills show user:my-skill`` report the same digest for the same Skill.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import SkillManifest

#: Domain-separation prefix. Changing the normalization rules requires changing
#: this label, so digests from different rule sets can never be confused.
DIGEST_DOMAIN = "sobai-skill-digest-v1"

DIGEST_PREFIX = "sha256"


def normalize_prompt(prompt: str) -> str:
    """Normalize prompt text for hashing and rendering.

    Line endings collapse to ``\\n``, trailing whitespace is stripped from every
    line, and the text is left with exactly one trailing newline. This makes the
    digest immune to editor and platform differences without touching content.
    """
    text = prompt.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip("\n") + "\n"


def canonical_manifest(manifest: SkillManifest) -> dict[str, Any]:
    """Return the manifest as a plain, fully-defaulted dict for hashing."""
    data: dict[str, Any] = manifest.model_dump(mode="json", by_alias=True)
    return data


def compute_digest(manifest: SkillManifest, prompt: str) -> str:
    """Return the ``sha256:<hex>`` digest for this Skill's content."""
    payload = {
        "domain": DIGEST_DOMAIN,
        "manifest": canonical_manifest(manifest),
        "prompt": normalize_prompt(prompt),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{DIGEST_PREFIX}:{hashlib.sha256(encoded).hexdigest()}"


def digest_bytes(data: bytes) -> str:
    """Return the ``sha256:<hex>`` digest of arbitrary bytes (used for input sizing)."""
    return f"{DIGEST_PREFIX}:{hashlib.sha256(data).hexdigest()}"
