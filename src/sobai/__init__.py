"""SoBatista AI — One CLI. Any model. Your tools.

A provider-neutral AI command-line orchestration layer that connects models to
explicitly authorized external tools. This package deliberately does *not*
implement a model runtime; it orchestrates providers (models that reason and
request tool calls) and connectors (external systems that retrieve or modify
data) through strict, dependency-injected interfaces.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

# The single authoritative version is the installed package metadata (built from
# pyproject's [project].version). This constant is only the source-checkout
# fallback when the package is not installed. Kept in step with pyproject by
# scripts/check_version.py, which fails CI if the two ever disagree.
_FALLBACK_VERSION = "0.2.0"

try:
    __version__ = version("sobatista-ai")
except PackageNotFoundError:  # pragma: no cover - only when running uninstalled
    __version__ = _FALLBACK_VERSION
