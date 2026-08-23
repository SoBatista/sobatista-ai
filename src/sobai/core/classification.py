"""Data classification levels used by the egress / privacy policy engine.

Every connector labels the data it returns with one of these levels. The policy
engine (see :mod:`sobai.policies`) uses the label to decide whether the data may
leave the machine for a cloud model, and whether to prompt the user first.
"""

from __future__ import annotations

from enum import StrEnum


class DataClass(StrEnum):
    """Ordered from least to most sensitive."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"

    @property
    def rank(self) -> int:
        order = [DataClass.PUBLIC, DataClass.INTERNAL, DataClass.SENSITIVE, DataClass.RESTRICTED]
        return order.index(self)
