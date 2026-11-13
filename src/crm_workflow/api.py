"""Operator-facing HTTP boundary. Temporal, not the web process, executes the saga."""

from __future__ import annotations

import inspect
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, Histogram, generate_latest
from prometheus_client import Counter as PrometheusCounter
from pydantic import ValidationError
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crm_workflow import __version__
from crm_workflow.auth import Authenticator, authenticate_webhook, current_actor, require_role
from crm_workflow.errors import DomainError
from crm_workflow.models import TERMINAL_STATES, Actor, ApprovalRequest, Identifier, OrderRequest, StrictModel

logger = logging.getLogger("crm_workflow.api")
STATIC = Path(__file__).with_name("static")
ActorDependency = Annotated[Actor, Depends(current_actor)]
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)


class EmptyCommand(StrictModel):
    """A reconciliation command carries no caller-selected mutation or identity."""


class TenantMetrics:
    """Each scrape shows one tenant's aggregates, without tenant or record IDs in labels."""

    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = PrometheusCounter(
            "p06_api_requests",
            "Authenticated requests observed by this web process.",
            ["method", "route", "status_code"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "p06_api_request_duration_seconds",
            "HTTP latency, excluding human approval wait.",
            ["method", "route"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=self.registry,
        )
        self.cases = Gauge(
            "p06_cases", "Persisted cases in the authenticated tenant.", ["state"], registry=self.registry
        )
        self.outbox_pending = Gauge(
            "p06_outbox_pending",
            "Tenant outbox entries awaiting delivery, including dead entries.",
            registry=self.registry,
        )
        self.outbox_dead = Gauge(
            "p06_outbox_dead", "Tenant outbox entries requiring controlled replay.", registry=self.registry
        )


class ApiMetrics:
    def __init__(self):
        self._tenants: dict[str, TenantMetrics] = {}

    def for_tenant(self, tenant_id: str) -> TenantMetrics:
        # Tenant IDs reach this method only from a validated configured principal.
        if tenant_id not in self._tenants:
            self._tenants[tenant_id] = TenantMetrics()
        return self._tenants[tenant_id]

    def observe(self, tenant_id: str | None, method: str, route: str, status: int, duration: float):
        if tenant_id:
            metrics = self.for_tenant(tenant_id)
            metrics.requests.labels(method=method, route=route, status_code=str(status)).inc()
            metrics.duration.labels(method=method, route=route).observe(duration)


def error_response(request_id: str, code: str, message: str, status: int, **kwargs) -> JSONResponse:
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": _CSP,
        "Referrer-Policy": "no-referrer",
        "X-Request-ID": request_id,
    }
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id, **kwargs}},
        headers=headers,
    )


class HttpBoundaryMiddleware:
    """Bound streamed bodies before JSON parsing; apply headers to successes and errors."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        try:
            await self._http(scope, receive, send)
        except Exception as exc:
            state = scope.setdefault("state", {})
            request_id = state.get("request_id") or uuid4().hex
            logger.error(
                "unexpected_http_failure",
                extra={"request_id": request_id, "exception_type": type(exc).__name__},
            )
            if state.get("response_started"):
                # The status is already on the wire. Preserve the interrupted-response
                # signal without letting the server log an upstream exception body.
                raise RuntimeError("HTTP response was interrupted; inspect its request ID") from None
            state["response_status"] = 500
            await error_response(
                request_id,
                "internal_error",
                "The request could not be completed. Use the request ID to investigate.",
                500,
            )(scope, receive, send)
        finally:
            state = scope.get("state", {})
            route = getattr(scope.get("route"), "path", "unmatched")
            status = state.get("response_status", 500)
            elapsed = time.monotonic() - started
            metrics = getattr(scope["app"].state, "metrics", None)
            if metrics:
                metrics.observe(state.get("metric_tenant"), scope["method"], route, status, elapsed)
            logger.info(
                "api_request",
                extra={
                    "request_id": state.get("request_id"),
                    "route": route,
                    "status": status,
                    "duration_seconds": round(elapsed, 6),
                },
            )

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                scope["state"]["response_started"] = True
                scope["state"]["response_status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                headers["Content-Security-Policy"] = _CSP
                headers["Cache-Control"] = "no-store"
            await send(message)

        if scope["method"] in {"POST", "PUT", "PATCH"}:
            settings = scope["app"].state.boundary_settings
            limit = settings.max_request_bytes
            headers = Headers(scope=scope)
            length = headers.get("content-length")
            if length is not None and (not length.isdecimal() or len(length) > 12):
                await error_response(request_id, "invalid_length", "Invalid Content-Length.", 400)(
                    scope, receive, secured_send
                )
                return
            if length is not None and int(length) > limit:
                await error_response(request_id, "payload_too_large", "Request body exceeds the limit.", 413)(
                    scope, receive, secured_send
                )
                return
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                await error_response(request_id, "unsupported_media_type", "Use application/json.", 415)(
                    scope, receive, secured_send
                )
                return
            chunks = bytearray()
            while True:
                incoming = await receive()
                if incoming["type"] == "http.disconnect":
                    return
                chunk = incoming.get("body", b"")
                if len(chunks) + len(chunk) > limit:
                    await error_response(
                        request_id, "payload_too_large", "Request body exceeds the limit.", 413
                    )(scope, receive, secured_send)
                    return
                chunks.extend(chunk)
                if not incoming.get("more_body", False):
                    break
            raw_body = bytes(chunks)
            delivered = False

            async def replay_body() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": raw_body, "more_body": False}
                return await receive()

            await self.app(scope, replay_body, secured_send)
            return
        await self.app(scope, receive, secured_send)


def create_app(runtime: Any | None = None) -> FastAPI:
    """Inject an isolated runtime in tests; production startup reads only external configuration."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        owned = runtime is None
        active_runtime = runtime
        if active_runtime is None:
            # Delayed import prevents module import from creating a database or opening clients.
            from crm_workflow.runtime import build_runtime

            active_runtime = build_runtime()
        application.state.runtime = active_runtime
        application.state.boundary_settings = active_runtime.settings
        try:
            application.state.authenticator = Authenticator(active_runtime.settings.auth_file)
            application.state.metrics = ApiMetrics()
            yield
        finally:
            if owned:
                await active_runtime.close()

    application = FastAPI(
        title="CRM Order Workflow Agent",
        version=__version__,
        description="Approved delivery-date changes, observed effects and reconciliation for synthetic orders.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(HttpBoundaryMiddleware)

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return error_response(request.state.request_id, exc.code, exc.message, exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Pydantic's default payload includes the rejected input, including arbitrary message text.
        return error_response(
            request.state.request_id,
            "invalid_request",
            "The request does not match the versioned contract.",
            422,
            violations=sorted({error["type"] for error in exc.errors()}),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        messages = {404: "Resource not found.", 405: "Method not allowed."}
        return error_response(
            request.state.request_id,
            "http_error",
            messages.get(exc.status_code, "The HTTP request was rejected."),
            exc.status_code,
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "unexpected_api_error",
            extra={"request_id": request.state.request_id, "exception_type": type(exc).__name__},
        )
        response = error_response(
            request.state.request_id,
            "internal_error",
            "The request could not be completed. Use the request ID to investigate.",
            500,
        )
        # Starlette renders unhandled errors outside user middleware.
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": _CSP,
                "Referrer-Policy": "no-referrer",
                "X-Request-ID": request.state.request_id,
            }
        )
        return response

    @application.get("/health/live", include_in_schema=False)
    async def live():
        return {"status": "alive"}

    @application.get("/health/ready")
    async def ready(request: Request, actor: ActorDependency):
        try:
            available = request.app.state.runtime.store.ping()
            if inspect.isawaitable(available):
                available = await available
            if not available:
                raise RuntimeError("Database check failed")
        except Exception:
            raise DomainError("not_ready", "Transactional storage is unavailable.", 503) from None
        # A storage probe does not prove that a worker, Salesforce or MuleSoft is healthy.
        return {"status": "ready", "checks": {"transactional_storage": "available"}}

    @application.get("/api/v1/session")
    async def session(request: Request, actor: ActorDependency):
        return {
            "schema_version": "1.0",
            "actor": actor.model_dump(mode="json"),
            "profile": request.app.state.runtime.settings.profile,
        }

    @application.get("/api/v1/openapi.json", include_in_schema=False)
    async def openapi(actor: ActorDependency):
        return application.openapi()

    @application.get("/api/v1/cases")
    async def cases(request: Request, actor: ActorDependency):
        items = await request.app.state.runtime.service.list_cases(actor)
        return {"schema_version": "1.0", "items": items}

    @application.post("/api/v1/cases", status_code=202)
    async def create_case(request: Request, body: OrderRequest, actor: ActorDependency, response: Response):
        require_role(actor, "requester")
        case = await request.app.state.runtime.service.create_case(body, actor)
        response.headers["Location"] = f"/api/v1/cases/{case['id']}"
        response.headers["X-Correlation-ID"] = case["correlation_id"]
        return case

    @application.get("/api/v1/cases/{case_id}")
    async def case_detail(case_id: Identifier, request: Request, actor: ActorDependency):
        return await request.app.state.runtime.service.get_case(case_id, actor)

    @application.post("/api/v1/cases/{case_id}/approval", status_code=202)
    async def approval(case_id: Identifier, request: Request, body: ApprovalRequest, actor: ActorDependency):
        require_role(actor, "approver")
        return await request.app.state.runtime.service.approve(case_id, body, actor)

    @application.post("/api/v1/cases/{case_id}/reconcile")
    async def reconcile(case_id: Identifier, request: Request, body: EmptyCommand, actor: ActorDependency):
        require_role(actor, "operator")
        return await request.app.state.runtime.service.reconcile(case_id, actor)

    @application.get("/metrics", include_in_schema=False)
    async def metrics(request: Request, actor: ActorDependency):
        require_role(actor, "operator")
        runtime = request.app.state.runtime
        observed = request.app.state.metrics.for_tenant(actor.tenant_id)
        counts = runtime.store.case_counts(actor.tenant_id)
        states = TERMINAL_STATES | {
            "RECEIVED",
            "AWAITING_APPROVAL",
            "APPROVED",
            "CRM_APPLIED",
            "STOCK_RESERVED",
        }
        for state in sorted(states):
            observed.cases.labels(state=state).set(counts.get(state, 0))
        outbox = runtime.store.outbox_stats(tenant_id=actor.tenant_id)
        observed.outbox_pending.set(outbox["pending"])
        observed.outbox_dead.set(outbox["dead"])
        return Response(generate_latest(observed.registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @application.post("/api/v1/webhooks/requests", status_code=202)
    async def webhook(request: Request, response: Response):
        settings = request.app.state.runtime.settings
        raw = await request.body()
        authenticate_webhook(
            raw=raw,
            timestamp=request.headers.get("X-P06-Timestamp"),
            signature=request.headers.get("X-P06-Signature"),
            secret=settings.webhook_secret.get_secret_value(),
        )
        try:
            body = OrderRequest.model_validate_json(raw)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from None
        actor = Actor(
            actor_id=settings.webhook_actor_id,
            tenant_id=settings.webhook_tenant_id,
            roles=["requester"],
        )
        request.state.metric_tenant = actor.tenant_id
        case = await request.app.state.runtime.service.create_case(body, actor)
        response.headers["Location"] = f"/api/v1/cases/{case['id']}"
        response.headers["X-Correlation-ID"] = case["correlation_id"]
        return case

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    application.mount("/static", StaticFiles(directory=STATIC), name="static")
    return application


app = create_app()
