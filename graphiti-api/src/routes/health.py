from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..graphiti_client import GraphitiService

router = APIRouter(tags=["health"])


class ServiceHealthPayload(BaseModel):
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    status: str
    services: dict[str, ServiceHealthPayload]


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> JSONResponse:
    service: GraphitiService = request.app.state.graphiti_service
    report = await service.check_health()
    payload = HealthResponse(
        status="ok" if report.ok else "degraded",
        services={
            name: ServiceHealthPayload(ok=status_item.ok, detail=status_item.detail)
            for name, status_item in report.services.items()
        },
    )
    code = status.HTTP_200_OK if report.ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=payload.model_dump())
