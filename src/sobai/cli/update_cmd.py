"""``sobai update`` — safe, canonical self-update from a local checkout.

Refreshes the globally installed ``sobai`` tool from a validated local
``sobatista-ai`` checkout using ``uv tool install --force``. Everything runs via
argv arrays (never a shell string, ``shell=True``, ``eval``, interpolation, or
globs), with timeouts, sanitized errors, and a privacy-preserving audit record.

It never runs ``git``, fetches remote code, changes branches, discards local
changes, publishes, tags, or releases. ``--check`` delegates to the existing
``update-check`` logic without changing anything.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Annotated

import typer

from sobai import __version__
from sobai.core.errors import (
    BuildError,
    ConfigError,
    DependencyError,
    NotFoundError,
    OperationDeclined,
    OperationTimeout,
    UpdateError,
)
from sobai.core.redaction import redact

from .common import get_ctx

PROJECT_NAME = "sobatista-ai"
_BUILD_TIMEOUT_S = 300.0
_INSTALL_TIMEOUT_S = 600.0
_VERIFY_TIMEOUT_S = 30.0


def _run(argv: list[str], *, timeout: float, cwd: str | None = None) -> tuple[int, str, str]:
    """Run an argv array with no shell, no stdin, and a timeout. Test seam."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv array, no shell, resolved paths
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OperationTimeout(f"'{argv[0]}' timed out after {timeout:.0f}s.") from exc
    except OSError as exc:  # pragma: no cover - defensive
        raise UpdateError(f"Failed to run '{argv[0]}': {redact(str(exc))}") from exc
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def validate_source(path_str: str) -> tuple[Path, str]:
    """Resolve and validate a sobatista-ai checkout. Returns (abs_path, version).

    Refuses missing, non-directory, root/overly-broad, or non-sobatista-ai paths.
    Performs no writes.
    """
    abs_path = Path(path_str).expanduser().resolve()
    # Refuse overly broad paths (a filesystem root has no distinct parent).
    if abs_path == abs_path.parent:
        raise ConfigError(
            f"Refusing an overly broad update source: {abs_path}",
            hint="Point --source at a specific sobatista-ai checkout directory.",
        )
    if not abs_path.is_dir():
        raise NotFoundError(
            f"Update source is not a directory: {abs_path}",
            hint="Pass the path to your sobatista-ai checkout, e.g. `sobai update --source .`",
        )
    pyproject = abs_path / "pyproject.toml"
    if not pyproject.is_file():
        raise ConfigError(
            f"No pyproject.toml in {abs_path}; not a sobatista-ai checkout.",
            hint="Run this from (or point --source at) your sobatista-ai checkout.",
        )
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read {pyproject}: {redact(str(exc))}") from exc
    project = data.get("project", {})
    name = project.get("name")
    if name != PROJECT_NAME:
        raise ConfigError(
            f"{pyproject} is project '{name}', not '{PROJECT_NAME}'.",
            hint="The update source must be a sobatista-ai checkout.",
        )
    version = str(project.get("version", "unknown"))
    return abs_path, version


def update_command(
    ctx: typer.Context,
    check: Annotated[
        bool, typer.Option("--check", help="Only check for a newer release; change nothing.")
    ] = False,
    source: Annotated[
        str | None,
        typer.Option("--source", help="Path to a sobatista-ai checkout (remembered for later)."),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Refresh the installed ``sobai`` from a validated local checkout."""
    app = get_ctx(ctx)

    if check:
        # Delegate to the existing update-check logic; it changes nothing.
        from .app import update_check

        update_check(ctx)
        return

    # Resolve the source: explicit --source (validated + remembered) or the stored one.
    if source is not None:
        abs_path, source_version = validate_source(source)
        app.config.config.update_source = str(abs_path)
        app.save_config()
    else:
        stored = app.config.config.update_source
        if not stored:
            raise ConfigError(
                "No update source configured.",
                hint="Run `sobai update --source .` from your sobatista-ai checkout first.",
            )
        abs_path, source_version = validate_source(stored)

    current_version = __version__
    uv = shutil.which("uv")
    if not uv:
        raise DependencyError(
            "`uv` is required to update but was not found on PATH.",
            hint="Install uv (https://docs.astral.sh/uv/) or reinstall via pipx, then retry.",
        )
    installer_cmd = f"uv tool install --force {abs_path}"

    # Show the plan (suppressed in JSON mode).
    app.ui.rule("Update plan")
    app.ui.print(f"  [heading]source[/heading]:            {abs_path}")
    app.ui.print(f"  [heading]installed version[/heading]: {current_version}")
    app.ui.print(f"  [heading]source version[/heading]:    {source_version}")
    app.ui.print(f"  [heading]installer[/heading]:         {installer_cmd}")

    # Confirmation (unless --yes). Non-interactive without --yes is declined.
    if not yes:
        if not app.ui.is_interactive():
            raise OperationDeclined(
                "Update requires confirmation.",
                hint="Re-run with --yes in a non-interactive context.",
            )
        if not typer.confirm("Proceed with the update?", default=False):
            raise OperationDeclined("Update declined; nothing was changed.")

    # Build/validate the source before replacing the installed tool.
    with tempfile.TemporaryDirectory(prefix="sobai-build-") as out_dir:
        rc, _out, err = _run(
            [uv, "build", "--out-dir", out_dir], timeout=_BUILD_TIMEOUT_S, cwd=str(abs_path)
        )
        if rc != 0:
            raise BuildError(
                "Building the source checkout failed; the installed tool was not changed.",
                hint=redact(err.strip())[:400] or "Run `uv build` in the checkout to see details.",
            )

    # Replace the installed tool.
    rc, _out, err = _run(
        [uv, "tool", "install", "--force", str(abs_path)], timeout=_INSTALL_TIMEOUT_S
    )
    if rc != 0:
        raise UpdateError(
            "Installing the refreshed tool failed.",
            hint=redact(err.strip())[:400] or "See uv's output for details.",
        )

    # Verify the refreshed executable.
    installed_version = None
    verified = False
    sobai_path = shutil.which("sobai")
    if sobai_path:
        vrc, vout, _verr = _run([sobai_path, "--version"], timeout=_VERIFY_TIMEOUT_S)
        verified = vrc == 0 and "sobai" in vout.lower()
        installed_version = vout.strip() or None

    app.db.record_audit(
        "self_update",
        detail={
            "source": str(abs_path),
            "from_version": current_version,
            "to_version": source_version,
            "verified": verified,
        },
    )

    if not verified:
        raise UpdateError(
            "Update installed but the refreshed `sobai` could not be verified.",
            hint="Check `sobai --version` and your PATH.",
        )

    if app.ui.json_mode:
        app.ui.print_json(
            {
                "status": "updated",
                "source": str(abs_path),
                "from_version": current_version,
                "to_version": source_version,
                "installed": installed_version,
                "verified": verified,
            }
        )
        return
    app.ui.success(f"Updated sobai from {current_version} to {source_version}.")
    app.ui.print(f"[muted]verified:[/muted] {installed_version}")
