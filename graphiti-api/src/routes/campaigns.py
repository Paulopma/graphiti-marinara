from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..graphiti_client import CharacterAnchorResult, GraphitiService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CharacterAnchor(BaseModel):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class UpsertCampaignAnchorsRequest(BaseModel):
    persona: CharacterAnchor
    primary_characters: list[CharacterAnchor] = Field(default_factory=list)


class CharacterAnchorResponse(BaseModel):
    uuid: str
    name: str
    labels: list[str]
    role_class: Literal["persona", "primary_character"]
    aliases: list[str]
    created: bool


class UpsertCampaignAnchorsResponse(BaseModel):
    campaign_id: str
    anchors: list[CharacterAnchorResponse]


@router.post("/{campaign_id}/anchors", response_model=UpsertCampaignAnchorsResponse)
async def upsert_campaign_anchors(
    campaign_id: str,
    payload: UpsertCampaignAnchorsRequest,
    request: Request,
) -> UpsertCampaignAnchorsResponse:
    service: GraphitiService = request.app.state.graphiti_service
    anchors: list[CharacterAnchorResult] = [
        await service.upsert_character_anchor(
            campaign_id=campaign_id,
            name=payload.persona.name,
            role_class="persona",
            aliases=payload.persona.aliases,
        )
    ]

    for primary_character in payload.primary_characters:
        anchors.append(
            await service.upsert_character_anchor(
                campaign_id=campaign_id,
                name=primary_character.name,
                role_class="primary_character",
                aliases=primary_character.aliases,
            )
        )

    return UpsertCampaignAnchorsResponse(
        campaign_id=campaign_id,
        anchors=[
            CharacterAnchorResponse(
                uuid=anchor.uuid,
                name=anchor.name,
                labels=anchor.labels,
                role_class=anchor.role_class,
                aliases=anchor.aliases,
                created=anchor.created,
            )
            for anchor in anchors
        ],
    )
