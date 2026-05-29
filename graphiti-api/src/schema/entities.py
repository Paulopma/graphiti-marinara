from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Character(BaseModel):
    """An individual in the world: named NPC, named creature, or the protagonist.
    Use when a specific person is mentioned by name or unique role.
    Do not use for anonymous groups such as guards or nameless bandits; use Faction."""

    role: str | None = Field(
        default=None,
        description="Narrative role such as ally, antagonist, mentor, or victim.",
    )
    status: Literal["alive", "dead", "missing", "unknown"] = "alive"
    occupation: str | None = None


class Faction(BaseModel):
    """An organized group: guild, cult, city, gang, army, or family.
    Use for collectives with a shared identity, not casual crowds."""

    faction_type: Literal[
        "guild",
        "cult",
        "city",
        "criminal",
        "noble_house",
        "military",
        "religious",
        "other",
    ]
    disposition_to_player: (
        Literal["hostile", "wary", "neutral", "friendly", "allied"] | None
    ) = None


class Location(BaseModel):
    """A named geographic place: city, district, dungeon, wilderness, building, or region.
    Use for places that can be revisited or anchor significant events."""

    location_type: Literal[
        "city",
        "district",
        "wilderness",
        "dungeon",
        "building",
        "region",
        "other",
    ]
    region: str | None = Field(default=None, description="Larger region containing this place.")


class Item(BaseModel):
    """A notable physical object: specific weapon, artifact, quest item, or prized possession.
    Do not use for generic inventory such as rations or coins; Marinara already tracks those."""

    item_type: str | None = None
    is_unique: bool = False


class Promise(BaseModel):
    """An explicit verbal commitment between Characters.
    Use whenever someone promises to do or not do something.
    This is critical for dark fantasy campaigns because broken promises can matter for many turns."""

    promise_content: str
    status: Literal["pending", "kept", "broken", "renegotiated"] = "pending"


class Event(BaseModel):
    """A significant happening: battle, death, revelation, betrayal, or pivotal encounter.
    Use for events that permanently change the state of the world."""

    event_type: str | None = None
    significance: Literal["minor", "moderate", "major", "campaign_defining"] = "moderate"


class Trauma(BaseModel):
    """A lasting psychological or physical scar on a Character.
    Captures the long-tail emotional or behavioral consequence of past events."""

    trigger: str = Field(description="What caused the trauma or what activates it.")
    severity: Literal["light", "moderate", "severe"] = "moderate"


class Reputation(BaseModel):
    """How a Character or Faction perceives another Character.
    This is social perception, not internal trauma."""

    perception: Literal[
        "unknown",
        "infamous",
        "feared",
        "despised",
        "respected",
        "loved",
        "legendary",
    ]


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Character": Character,
    "Faction": Faction,
    "Location": Location,
    "Item": Item,
    "Promise": Promise,
    "Event": Event,
    "Trauma": Trauma,
    "Reputation": Reputation,
}
