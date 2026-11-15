from __future__ import annotations

import json
import ssl
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from crm_workflow.errors import DomainError, TransientError, UnknownOutcome


class CRM(Protocol):
    async def capabilities(self) -> dict: ...
    async def customers(self, tenant_id: str, reference: str) -> list[dict]: ...
    async def orders(self, tenant_id: str, customer_id: str, reference: str) -> list[dict]: ...
    async def order(self, tenant_id: str, order_id: str) -> dict: ...
    async def effect(self, tenant_id: str, key: str) -> dict | None: ...
    async def apply(self, order_id: str, payload: dict, correlation_id: str) -> dict: ...


class ERP(Protocol):
    async def availability(self, tenant_id: str, sku: str) -> dict: ...
    async def reservation(self, tenant_id: str, key: str) -> dict | None: ...
    async def reserve(self, payload: dict, correlation_id: str) -> dict: ...


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError):
            return None


class HTTPSystem:
    def __init__(self, base_url, token, timeout=5, *, transport=None, ca_file=None):
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            verify=ssl.create_default_context(cafile=ca_file) if ca_file else True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=8),
        )

    async def request(self, method, path, *, missing_ok=False, **kwargs):
        writing = method not in {"GET", "HEAD"}
        try:
            async with self.client.stream(method, path, **kwargs) as response:
                content = bytearray()
                if 200 <= response.status_code < 300:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(content) + len(chunk) > 1048576:
                            error = UnknownOutcome if writing else TransientError
                            raise error("Remote response exceeds the contract limit")
                        content.extend(chunk)
        except httpx.TransportError as exc:
            error = UnknownOutcome if writing else TransientError
            raise error("Remote transport failed; reconcile writes before retry") from exc
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code in {408, 429} or response.status_code >= 500:
            error = UnknownOutcome if writing and response.status_code != 429 else TransientError
            raise error(
                f"Remote service returned HTTP {response.status_code}",
                retry_after_seconds(response.headers.get("Retry-After")),
            )
        if response.status_code >= 400:
            code = {
                401: "PROVIDER_UNAUTHENTICATED",
                403: "PROVIDER_FORBIDDEN",
                404: "NOT_FOUND",
                409: "STATE_CHANGED",
                412: "STATE_CHANGED",
            }.get(response.status_code, "REMOTE_REJECTED")
            raise DomainError(
                code,
                f"Remote service rejected the operation (HTTP {response.status_code})",
                response.status_code if response.status_code in {401, 403, 404} else 409,
            )
        if not 200 <= response.status_code < 300:
            raise DomainError("UNEXPECTED_REDIRECT", "Remote redirects are not followed", 502)
        try:
            value = json.loads(content)
        except ValueError as exc:
            error = UnknownOutcome if writing else TransientError
            raise error("Remote response is not valid JSON; reconcile any submitted write") from exc
        if not isinstance(value, dict):
            raise DomainError("REMOTE_SCHEMA", "Remote response does not match the object contract", 502)
        return value

    async def close(self):
        await self.client.aclose()


class MuleCRM(HTTPSystem):
    """Real MuleSoft-facing adapter; this class has no synthetic fallback."""

    async def capabilities(self):
        return await self.request("GET", "/v1/capabilities")

    async def customers(self, tenant_id, reference):
        data = await self.request(
            "GET", "/v1/customers", params={"tenant_id": tenant_id, "reference": reference}
        )
        return data["items"]

    async def orders(self, tenant_id, customer_id, reference):
        data = await self.request(
            "GET",
            "/v1/orders",
            params={"tenant_id": tenant_id, "customer_id": customer_id, "reference": reference},
        )
        return data["items"]

    async def order(self, tenant_id, order_id):
        return await self.request(
            "GET", f"/v1/orders/{quote(order_id, safe='')}", params={"tenant_id": tenant_id}
        )

    async def effect(self, tenant_id, key):
        return await self.request(
            "GET", f"/v1/effects/{quote(key, safe='')}", params={"tenant_id": tenant_id}, missing_ok=True
        )

    async def apply(self, order_id, payload, correlation_id):
        return await self.request(
            "POST",
            f"/v1/orders/{quote(order_id, safe='')}/effects",
            json=payload,
            headers={"X-Correlation-ID": correlation_id},
        )


class HTTPERP(HTTPSystem):
    async def availability(self, tenant_id, sku):
        return await self.request(
            "GET", f"/v1/availability/{quote(sku, safe='')}", params={"tenant_id": tenant_id}
        )

    async def reservation(self, tenant_id, key):
        return await self.request(
            "GET", f"/v1/reservations/{quote(key, safe='')}", params={"tenant_id": tenant_id}, missing_ok=True
        )

    async def reserve(self, payload, correlation_id):
        return await self.request(
            "POST", "/v1/reservations", json=payload, headers={"X-Correlation-ID": correlation_id}
        )
