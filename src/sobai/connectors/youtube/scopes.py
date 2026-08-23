"""OAuth scopes for the YouTube connector.

Least-privilege by default: only read-only Data + non-monetary Analytics scopes
are requested. Revenue data and caption access are separate, explicit opt-ins
because they broaden access (caption access in particular requires ``force-ssl``,
which is a read/write-capable scope).
"""

from __future__ import annotations

# Read-only YouTube Data API (channel/video/caption metadata).
DATA_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
# Non-monetary YouTube Analytics.
ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"
# Monetary (revenue) YouTube Analytics — separate opt-in.
ANALYTICS_MONETARY = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
# Caption list/download for your OWN channel — separate opt-in. NOTE: this is a
# broad, read/write-capable scope (it also permits editing videos/comments); it
# is requested only when the user explicitly opts in with --captions.
CAPTIONS_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"

DEFAULT_SCOPES: tuple[str, ...] = (DATA_READONLY, ANALYTICS)


def scope_set(*, monetary: bool = False, captions: bool = False) -> list[str]:
    """Return the least-privilege scope list for the requested capabilities."""
    scopes = list(DEFAULT_SCOPES)
    if monetary:
        scopes.append(ANALYTICS_MONETARY)
    if captions:
        scopes.append(CAPTIONS_FORCE_SSL)
    return scopes
