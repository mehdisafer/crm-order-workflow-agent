"""Server-owned principals and signed intake; callers never supply their permissions."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, model_validator

from crm_workflow.errors import DomainError
from crm_workflow.models import Actor, StrictModel

bearer = HTTPBearer(auto_error=False, scheme_name="OperatorToken")


class Principal(Actor):
    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PrincipalDocument(StrictModel):
    principals: list[Principal] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_credentials(self):
        digests = [principal.token_sha256 for principal in self.principals]
        if len(digests) != len(set(digests)):
            raise ValueError("Each credential must identify exactly one principal")
        if any(not principal.roles for principal in self.principals):
            raise ValueError("Every principal requires an explicit role")
        return self


class Authenticator:
    """Load hashes from an external secret mount; keep no plaintext operator token."""

    def __init__(self, path: str | Path):
        try:
            raw = Path(path).read_bytes()
            if len(raw) > 65536:
                raise ValueError("Principal document exceeds its maximum size")
            document = PrincipalDocument.model_validate(json.loads(raw))
        except (OSError, ValueError):
            # Validation exceptions can include input. Do not expose that document.
            raise RuntimeError("Authentication configuration is missing or invalid") from None
        self._principals = tuple(document.principals)

    def resolve(self, token: str | None) -> Actor:
        if not token or len(token) > 4096:
            raise unauthenticated()
        supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
        matched = None
        # Scan every entry and compare fixed-length digests without early return.
        for principal in self._principals:
            if hmac.compare_digest(supplied, principal.token_sha256):
                matched = principal
        if matched is None:
            raise unauthenticated()
        return Actor(
            actor_id=matched.actor_id,
            tenant_id=matched.tenant_id,
            roles=matched.roles,
        )


def unauthenticated() -> DomainError:
    return DomainError("unauthenticated", "Valid bearer credentials are required.", 401)


async def current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Actor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthenticated()
    actor = request.app.state.authenticator.resolve(credentials.credentials)
    request.state.metric_tenant = actor.tenant_id
    return actor


def require_role(actor: Actor, role: str) -> None:
    if role not in actor.roles:
        raise DomainError("forbidden", f"The {role} role is required for this operation.", 403)


def authenticate_webhook(
    *, raw: bytes, timestamp: str | None, signature: str | None, secret: str, now: float | None = None
) -> None:
    """Verify the signed raw bytes before parsing JSON; identical deliveries are idempotent in the core."""
    if not secret:
        raise DomainError("webhook_disabled", "Signed webhook intake is not configured.", 503)
    if not timestamp or not re.fullmatch(r"[0-9]{10}", timestamp):
        raise DomainError("invalid_webhook", "A valid, recent webhook signature is required.", 401)
    observed_time = time.time() if now is None else now
    if abs(observed_time - int(timestamp)) > 300:
        raise DomainError("invalid_webhook", "A valid, recent webhook signature is required.", 401)
    provided = (signature or "").removeprefix("sha256=")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", provided):
        raise DomainError("invalid_webhook", "A valid, recent webhook signature is required.", 401)
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw, hashlib.sha256)
    if not hmac.compare_digest(expected.hexdigest(), provided.lower()):
        raise DomainError("invalid_webhook", "A valid, recent webhook signature is required.", 401)
