"""YouTube connector (read-only, Phase 1).

Uses the official Google APIs only — YouTube Data API v3 and YouTube Analytics
API v2. Never scrapes YouTube or YouTube Studio. Authentication is installed-app
OAuth 2.0 with a loopback redirect and PKCE; tokens live in the OS keyring.
"""

from .connector import YouTubeConnector

__all__ = ["YouTubeConnector"]
