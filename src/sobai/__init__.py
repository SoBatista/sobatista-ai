"""SoBatista AI — One CLI. Any model. Your tools.

A provider-neutral AI command-line orchestration layer that connects models to
explicitly authorized external tools. This package deliberately does *not*
implement a model runtime; it orchestrates providers (models that reason and
request tool calls) and connectors (external systems that retrieve or modify
data) through strict, dependency-injected interfaces.
"""

from __future__ import annotations

__all__ = ["__version__"]

# Kept in sync with pyproject via the release workflow. The source of truth for
# a built distribution is the package metadata; this constant is the fallback
# used for `sobai --version` when running from a source checkout.
__version__ = "0.1.0.dev0"
