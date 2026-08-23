"""Page/database id and Notion URL normalization.

Accepts a bare Notion id (32 hex chars, dashed or not) or a Notion URL on the
``notion.so`` host, and normalizes it to a dashed UUID. Arbitrary/non-Notion
URLs are refused — we never fetch content from a URL the user pastes; we only
extract an id we then look up through the official API.
"""

from __future__ import annotations

import re
import urllib.parse

from sobai.core.errors import ConnectorError

_DASHED = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ALLOWED_HOSTS = {"notion.so", "www.notion.so"}


def _dash(hex32: str) -> str:
    h = hex32.lower()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def normalize_id(value: str) -> str:
    """Return a dashed UUID for a Notion id or a notion.so URL.

    Raises :class:`ConnectorError` for missing ids, non-Notion hosts, or values
    with no extractable 32-hex id.
    """
    value = value.strip()
    if not value:
        raise ConnectorError("Empty Notion page/database id.")

    # Already a dashed UUID.
    if _DASHED.match(value):
        return value.lower()
    # A bare 32-hex id (no dashes, no URL).
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return _dash(value)

    # Otherwise it must be a Notion URL on an allowed host.
    if "://" in value or value.startswith("www.") or "notion.so" in value:
        parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
        host = (parsed.hostname or "").lower()
        if host not in _ALLOWED_HOSTS:
            raise ConnectorError(
                f"Refusing non-Notion URL host '{host or value}'.",
                hint="Pass a notion.so URL or a page id — not an arbitrary URL.",
            )
        # A Notion page id is the final 32 hex chars of the path (a title slug may
        # precede it and can itself contain hex letters, so take the *last* 32).
        hex_only = re.sub(r"[^0-9a-fA-F]", "", parsed.path)
        if len(hex_only) >= 32:
            return _dash(hex_only[-32:])
        raise ConnectorError(
            f"Could not find a Notion id in URL: {value}",
            hint="Use the page's URL that ends with a 32-character id.",
        )

    raise ConnectorError(
        f"Not a valid Notion id or notion.so URL: {value}",
        hint="Pass a 32-character page id or a notion.so page URL.",
    )
