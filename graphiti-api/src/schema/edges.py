from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class KILLED(BaseModel):
    """Character killed Character. Permanent unless explicitly retconned."""

    method: str | None = None


class BETRAYED(BaseModel):
    """Character betrayed Character or Faction, including broken promises or broken alliances."""

    context: str | None = None


class ALLIED_WITH(BaseModel):
    """Active alliance between Characters or between a Character and a Faction."""

    nature: Literal["mercenary", "ideological", "personal", "coerced"] | None = None


class MEMBER_OF(BaseModel):
    """Character belongs to Faction."""

    rank: str | None = None


class LOCATED_AT(BaseModel):
    """Notable Item is stored, hidden, or anchored at a Location.
    Do not use for a Character's current scene location; Marinara World State owns that."""


class OWNS(BaseModel):
    """Character owns Item."""


class KNOWS(BaseModel):
    """Character knows another Character or has knowledge of Event or Item."""

    familiarity: Literal["acquaintance", "associate", "close", "intimate"] | None = None


class PROMISED_TO(BaseModel):
    """Character made a Promise to another Character."""


class HARMED(BaseModel):
    """Character caused physical, psychological, social, or financial harm to another Character."""

    harm_type: Literal["physical", "psychological", "social", "financial"] | None = None


class WITNESSED(BaseModel):
    """Character witnessed Event."""


class PERCEIVES_AS(BaseModel):
    """Character or Faction holds a Reputation about another Character."""


EDGE_TYPES: dict[str, type[BaseModel]] = {
    "KILLED": KILLED,
    "BETRAYED": BETRAYED,
    "ALLIED_WITH": ALLIED_WITH,
    "MEMBER_OF": MEMBER_OF,
    "LOCATED_AT": LOCATED_AT,
    "OWNS": OWNS,
    "KNOWS": KNOWS,
    "PROMISED_TO": PROMISED_TO,
    "HARMED": HARMED,
    "WITNESSED": WITNESSED,
    "PERCEIVES_AS": PERCEIVES_AS,
}

EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Character", "Character"): [
        "KILLED",
        "BETRAYED",
        "ALLIED_WITH",
        "KNOWS",
        "PROMISED_TO",
        "HARMED",
        "PERCEIVES_AS",
    ],
    ("Character", "Faction"): ["MEMBER_OF", "ALLIED_WITH", "BETRAYED", "PERCEIVES_AS"],
    ("Faction", "Character"): ["PERCEIVES_AS"],
    ("Item", "Location"): ["LOCATED_AT"],
    ("Character", "Item"): ["OWNS"],
    ("Character", "Event"): ["WITNESSED"],
    ("Character", "Promise"): ["PROMISED_TO"],
}
