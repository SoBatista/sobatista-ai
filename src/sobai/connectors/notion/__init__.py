"""Notion connector (read-only, Phase 1).

Uses the official Notion API only. The integration can access only pages and
databases (data sources) that have been explicitly shared with it. All Phase 1
capabilities are strictly read-only: nothing is ever created, edited, archived,
restored, commented on, or deleted.
"""

from .connector import NotionConnector

__all__ = ["NotionConnector"]
