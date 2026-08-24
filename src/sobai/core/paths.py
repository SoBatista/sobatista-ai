"""Filesystem locations, resolved via :mod:`platformdirs`.

Canonical Linux layout (XDG):

* ``~/.config/sobai/config.toml`` — user configuration
* ``~/.config/sobai/skills/`` — user-installed Skills
* ``~/.local/share/sobai/state.db`` — SQLite state, cache metadata, audit log
* ``~/.cache/sobai/`` — regenerable cache payloads

Every path can be overridden with an environment variable so tests and
sandboxed runs never touch the real user profile:

* ``SOBAI_CONFIG_DIR``
* ``SOBAI_DATA_DIR``
* ``SOBAI_CACHE_DIR``
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "sobai"


def _resolve(env_var: str, default: Path) -> Path:
    override = os.environ.get(env_var)
    return Path(override).expanduser() if override else default


@dataclass(frozen=True, slots=True)
class Paths:
    """Resolved application directories and well-known file locations."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path

    @classmethod
    def resolve(cls) -> Paths:
        return cls(
            config_dir=_resolve("SOBAI_CONFIG_DIR", Path(platformdirs.user_config_dir(APP_NAME))),
            data_dir=_resolve("SOBAI_DATA_DIR", Path(platformdirs.user_data_dir(APP_NAME))),
            cache_dir=_resolve("SOBAI_CACHE_DIR", Path(platformdirs.user_cache_dir(APP_NAME))),
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def skills_dir(self) -> Path:
        """Where user-installed Skills live. Nothing else is ever searched."""
        return self.config_dir / "skills"

    @property
    def state_db(self) -> Path:
        return self.data_dir / "state.db"

    def ensure(self) -> None:
        """Create the directories with restrictive permissions (owner-only)."""
        for directory in (self.config_dir, self.data_dir, self.cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
            # Best effort: tighten to 0700 on POSIX so state/cache aren't world-readable.
            with contextlib.suppress(OSError):  # pragma: no cover - platform dependent
                directory.chmod(0o700)
