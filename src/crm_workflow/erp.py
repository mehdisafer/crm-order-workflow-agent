"""Original synthetic ERP service with an atomic inventory/reservation database."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, field_validator
from sqlalchemy import inspect
from starlette.exceptions import HTTPException

from crm_workflow.api import HttpBoundaryMiddleware, error_response
from crm_workflow.config import Settings
from crm_workflow.demo import DemoERP
from crm_workflow.errors import DomainError
from crm_workflow.models import Identifier, StrictModel
from crm_workflow.store import Store

logger = logging.getLogger("crm_workflow.erp")
bearer = HTTPBearer(auto_error=False)


async def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    token = request.app.state.settings.erp_token.get_secret_value()
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or len(credentials.credentials) > 4096
        or not hmac.compare_digest(credentials.credentials.encode(), token.encode())
    ):
        raise DomainError("UNAUTHENTICATED", "Valid technical credentials are required", 401)
    tenant = request.app.state.settings.webhook_tenant_id
    request.state.metric_tenant = tenant
    return tenant


AuthorisedTenant = Annotated[str, Depends(authenticated)]
EffectKey = Annotated[str, Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_.:-]+$")]
CorrelationID = Annotated[str, Header(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]


class ReservationRequest(StrictModel):
    effect_key: EffectKey
    tenant_id: Identifier
    order_id: Identifier
    sku: Identifier
    quantity: int = Field(gt=0, le=100000)
    expected_revision: int = Field(ge=1)
    approved_plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("expiry must include a timezone")
        return value


def create_app(store: Store | None = None, settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        if len(config.erp_token.get_secret_value()) < 24:
            raise RuntimeError("ERP needs an externally supplied random technical token")
        app.state.settings = config
        app.state.boundary_settings = config
        app.state.store = store or Store(config.database_url, initialize=False)
        app.state.erp = DemoERP(app.state.store)
        try:
            if not app.state.store.ping():
                raise RuntimeError("ERP schema has not been migrated")
            if not all(
                inspect(app.state.store.engine).has_table(name)
                for name in ("demo_inventory", "demo_reservations")
            ):
                raise RuntimeError("Synthetic ERP data has not been initialised; run seed-demo first")
            yield
        finally:
            if store is None:
                app.state.store.close()

    app = FastAPI(
        title="P06 synthetic inventory",
        version="1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(HttpBoundaryMiddleware)

    def tenant_check(actual, expected):
        if actual != expected:
            raise DomainError("NOT_FOUND", "Resource not found", 404)

    @app.exception_handler(DomainError)
    async def business_error(request, exc):
        return error_response(request.state.request_id, exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(
            request.state.request_id,
            "INVALID_REQUEST",
            "The request does not match the versioned contract.",
            422,
            violations=sorted({error["type"] for error in exc.errors()}),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(
            request.state.request_id, "HTTP_ERROR", "The HTTP request was rejected.", exc.status_code
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error(
            "unexpected_erp_error",
            extra={"request_id": request.state.request_id, "exception_type": type(exc).__name__},
        )
        return error_response(
            request.state.request_id,
            "INTERNAL_ERROR",
            "The request could not be completed. Use the request ID to investigate.",
            500,
        )

    @app.get("/health/live")
    async def live():
        return {"status": "alive", "system": "synthetic-erp"}

    @app.get("/v1/availability/{sku}")
    async def availability(
        sku: Identifier, tenant_id: Identifier, request: Request, authorised: AuthorisedTenant
    ):
        tenant_check(tenant_id, authorised)
        return await request.app.state.erp.availability(tenant_id, sku)

    @app.get("/v1/reservations/{key}")
    async def reservation(
        key: EffectKey, tenant_id: Identifier, request: Request, authorised: AuthorisedTenant
    ):
        tenant_check(tenant_id, authorised)
        result = await request.app.state.erp.reservation(tenant_id, key)
        if result is None:
            raise DomainError("NOT_FOUND", "Reservation not found", 404)
        return result

    @app.post("/v1/reservations")
    async def reserve(
        payload: ReservationRequest,
        request: Request,
        x_correlation_id: CorrelationID,
        authorised: AuthorisedTenant,
    ):
        tenant_check(payload.tenant_id, authorised)
        return await request.app.state.erp.reserve(payload.model_dump(mode="json"), x_correlation_id)

    return app


app = create_app()
