#!/usr/bin/env python3
"""Write a ``SHA256SUMS`` file for the distribution artifacts in a directory.

The output uses the GNU coreutils format (``<hex>  <name>``) so it can be
verified with ``sha256sum -c SHA256SUMS``. Used by ``release.yml`` and
unit-tested directly.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SUMS_NAME = "SHA256SUMS"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_checksums(directory: Path) -> dict[str, str]:
    """Return ``{filename: sha256hex}`` for every regular file in *directory*."""
    result: dict[str, str] = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name != SUMS_NAME:
            result[path.name] = _sha256(path)
    return result


def render(checksums: dict[str, str]) -> str:
    return "".join(f"{digest}  {name}\n" for name, digest in checksums.items())


def write_sumfile(directory: Path) -> Path:
    checksums = compute_checksums(directory)
    if not checksums:
        raise FileNotFoundError(f"no files to checksum in {directory}")
    out = directory / SUMS_NAME
    out.write_text(render(checksums), encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: gen_checksums.py <dist-dir>", file=sys.stderr)
        return 2
    directory = Path(argv[1])
    if not directory.is_dir():
        print(f"ERROR: not a directory: {directory}", file=sys.stderr)
        return 1
    out = write_sumfile(directory)
    print(f"Wrote {out}")
    print(out.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
