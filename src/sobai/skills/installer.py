"""Installing a validated local Skill into the user's Skill directory.

Installation is **local only**. Nothing is ever downloaded: there is no remote
registry, no URL form, and no implicit fetch. You point at a directory you can
already read, it is validated, and a copy is placed under
``~/.config/sobai/skills/``.

Three properties matter here.

*Atomic.* Files are written into a private staging directory and moved into
place with a single rename, so a failure never leaves a half-installed Skill for
the loader to find. If a replacement fails midway, the previous version is
rolled back.

*Race-safe.* A directory-level lock file, created with ``O_EXCL``, serialises
concurrent installs so two processes cannot interleave into the same name.

*Faithful to what was reviewed.* The bytes written are the bytes that were
validated and hashed, held in memory — never a second read of the source. A
source that changes between validation and install cannot substitute content
(a TOCTOU swap), and the installed digest always matches the reported one.
"""

from __future__ import annotations

import contextlib
import errno
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sobai.core.errors import SkillError

from .loader import (
    MANIFEST_FILENAME,
    PROMPT_FILENAME,
    parse_skill,
    read_skill_files,
)
from .models import Namespace, Skill

LOCK_FILENAME = ".install.lock"
STAGING_PREFIX = ".staging-"
BACKUP_PREFIX = ".backup-"


class SkillInstallError(SkillError):
    """A Skill could not be installed."""


@dataclass(frozen=True, slots=True)
class InstallResult:
    """What an installation did."""

    skill: Skill
    destination: Path
    #: "installed" (new), "replaced" (--force over a different version), or
    #: "unchanged" (the same content was already installed).
    action: str

    @property
    def changed(self) -> bool:
        return self.action != "unchanged"


def validate_source(path: Path) -> Skill:
    """Validate a local directory as a Skill without installing it.

    The returned Skill carries the ``user:`` namespace and the digest the
    installed copy would have.
    """
    manifest_bytes, prompt_bytes = read_skill_files(path.expanduser())
    return parse_skill(manifest_bytes, prompt_bytes, namespace=Namespace.USER)


class _DirectoryLock:
    """An exclusive lock over the Skills directory, held for one install."""

    def __init__(self, root: Path) -> None:
        self._path = root / LOCK_FILENAME
        self._fd: int | None = None

    def __enter__(self) -> _DirectoryLock:
        try:
            self._fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SkillInstallError(
                "Another skill installation is in progress.",
                hint=f"If no other `sobai` is running, remove the stale lock at {self._path}.",
            ) from exc
        except OSError as exc:
            raise SkillInstallError(
                f"Cannot lock the skills directory: {exc.strerror or exc}.",
                hint=f"Check permissions on {self._path.parent}.",
            ) from exc
        os.write(self._fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self._path.unlink(missing_ok=True)


def _write_staging(root: Path, manifest_bytes: bytes, prompt_bytes: bytes) -> Path:
    """Write the validated bytes into a fresh private staging directory."""
    staging = Path(tempfile.mkdtemp(dir=root, prefix=STAGING_PREFIX))
    try:
        os.chmod(staging, 0o700)
        for filename, payload in (
            (MANIFEST_FILENAME, manifest_bytes),
            (PROMPT_FILENAME, prompt_bytes),
        ):
            target = staging / filename
            with target.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(target, 0o600)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging


def install_skill(
    source: Path,
    skills_dir: Path,
    *,
    force: bool = False,
) -> InstallResult:
    """Validate *source* and install it atomically into *skills_dir*.

    Returns without changing anything when the identical Skill is already
    installed. Replacing a different version of the same name requires *force*.
    """
    source = source.expanduser()
    manifest_bytes, prompt_bytes = read_skill_files(source)
    skill = parse_skill(manifest_bytes, prompt_bytes, namespace=Namespace.USER)

    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(skills_dir, 0o700)
    except OSError as exc:
        raise SkillInstallError(
            f"Cannot create the skills directory {skills_dir}: {exc.strerror or exc}.",
        ) from exc

    destination = skills_dir / skill.name
    if destination.resolve().parent != skills_dir.resolve():  # pragma: no cover - defensive
        raise SkillInstallError(f"Refusing to install outside {skills_dir}.")

    with _DirectoryLock(skills_dir):
        # Safe here and only here: the lock proves no other install is mid-flight,
        # so anything still staged is debris from an interrupted run.
        cleanup_stale_staging(skills_dir)
        existing = _existing_digest(destination)
        if existing == skill.digest:
            return InstallResult(skill=skill, destination=destination, action="unchanged")
        if existing is not None and not force:
            raise SkillInstallError(
                f"A different skill is already installed as {skill.qualified_name!r}.",
                hint="Re-run with --force to replace it, after comparing "
                f"`sobai skills show {skill.qualified_name}`.",
            )
        if destination.exists() and existing is None and not force:
            raise SkillInstallError(
                f"{destination} already exists but is not a valid skill.",
                hint="Inspect it, then re-run with --force to replace it.",
            )
        staging = _write_staging(skills_dir, manifest_bytes, prompt_bytes)
        action = _swap_into_place(staging, destination, replacing=destination.exists())
    return InstallResult(skill=skill, destination=destination, action=action)


def _existing_digest(destination: Path) -> str | None:
    """Return the digest of an already-installed Skill, or None if absent/invalid."""
    if not destination.is_dir():
        return None
    try:
        manifest_bytes, prompt_bytes = read_skill_files(destination)
        return parse_skill(manifest_bytes, prompt_bytes, namespace=Namespace.USER).digest
    except SkillError:
        return None


def _swap_into_place(staging: Path, destination: Path, *, replacing: bool) -> str:
    """Move *staging* to *destination*, rolling back the previous copy on failure."""
    backup: Path | None = None
    try:
        if replacing:
            backup = destination.with_name(f"{BACKUP_PREFIX}{destination.name}")
            _discard(backup)
            os.rename(destination, backup)
        os.rename(staging, destination)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists() and not destination.exists():
            # Roll back: the previous version is restored, so a failed replace
            # leaves the machine exactly as it was.
            with contextlib.suppress(OSError):
                os.rename(backup, destination)
        raise SkillInstallError(
            f"Could not install into {destination}: {exc.strerror or exc}.",
            hint="Check permissions and free space, then retry.",
        ) from exc
    if backup is not None:
        _discard(backup)
    return "replaced" if replacing else "installed"


def _discard(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def cleanup_stale_staging(skills_dir: Path) -> int:
    """Remove staging/backup directories left by an interrupted install."""
    if not skills_dir.is_dir():
        return 0
    removed = 0
    for entry in skills_dir.iterdir():
        if entry.name.startswith((STAGING_PREFIX, BACKUP_PREFIX)) and entry.is_dir():
            try:
                shutil.rmtree(entry)
                removed += 1
            except OSError as exc:  # pragma: no cover - permissions dependent
                if exc.errno != errno.ENOENT:
                    raise
    return removed
