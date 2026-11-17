"""Transactional case projections, effect intents, outbox and shared admission limits.

PostgreSQL is the deployment target. SQLite is an explicit isolated demo/test profile.
All case transitions use optimistic compare-and-set, including on SQLite.
"""

from __future__ import annotations

import copy
import time
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from crm_workflow.errors import DomainError, TransientError
from crm_workflow.models import TERMINAL_STATES, canonical_hash, timestamp

metadata = MetaData()
schema = Table("schema_version", metadata, Column("version", Integer, primary_key=True))
cases = Table(
    "cases",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("message_id", String(100), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("state", String(40), nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("api_calls", Integer, nullable=False, default=0),
    Column("data", JSON, nullable=False),
    UniqueConstraint("tenant_id", "message_id", name="uq_case_message"),
)
events = Table(
    "case_events",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("case_id", String(100), ForeignKey("cases.id"), nullable=False, index=True),
    Column("event_type", String(100), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", String(40), nullable=False),
)
effects = Table(
    "effects",
    metadata,
    Column("effect_key", String(150), primary_key=True),
    Column("case_id", String(100), ForeignKey("cases.id"), nullable=False, index=True),
    Column("system", String(20), nullable=False),
    Column("operation", String(80), nullable=False),
    Column("status", String(30), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("request", JSON, nullable=False),
    Column("before", JSON),
    Column("after", JSON),
    Column("attempts", Integer, nullable=False, default=0),
)
outbox = Table(
    "outbox",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("case_id", String(100), ForeignKey("cases.id"), nullable=False),
    Column("kind", String(50), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("available_at", Float, nullable=False),
    Column("delivered_at", Float),
    Column("last_error", String(200)),
    Column("dead", Integer, default=0),
)
systems = Table(
    "system_limits",
    metadata,
    Column("name", String(20), primary_key=True),
    Column("failures", Integer, nullable=False, default=0),
    Column("open_until", Float, nullable=False, default=0),
    Column("version", Integer, nullable=False, default=1),
)
leases = Table(
    "system_leases",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("system", String(20), nullable=False),
    Column("expires_at", Float, nullable=False),
)


class Store:
    def __init__(self, url: str, *, initialize: bool = True):
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        kwargs = (
            {"connect_args": {"check_same_thread": False, "timeout": 15}} if url.startswith("sqlite") else {}
        )
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, pool_pre_ping=True, **kwargs)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def sqlite_pragmas(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")

        if initialize:
            self.migrate()

    def migrate(self):
        metadata.create_all(self.engine)
        with self.engine.begin() as db:
            versions = list(db.scalars(select(schema.c.version)))
            if versions and versions != [1]:
                raise RuntimeError("Unsupported schema version; follow migration runbook")
            if not versions:
                db.execute(insert(schema).values(version=1))
            for system in ("crm", "erp", "llm"):
                if not db.scalar(select(systems.c.name).where(systems.c.name == system)):
                    db.execute(insert(systems).values(name=system, failures=0, open_until=0, version=1))

    def ping(self) -> bool:
        with self.engine.connect() as db:
            return db.scalar(select(schema.c.version)) == 1

    @staticmethod
    def _event(db, case_id, event_type, payload):
        db.execute(
            insert(events).values(
                id=str(uuid.uuid4()),
                case_id=case_id,
                event_type=event_type,
                payload=payload,
                created_at=timestamp(),
            )
        )

    @staticmethod
    def _outbox(db, case_id, kind, payload, suffix=""):
        db.execute(
            insert(outbox).values(
                id=f"{case_id}:{kind}{suffix}",
                case_id=case_id,
                kind=kind,
                payload=payload,
                attempts=0,
                available_at=time.time(),
                dead=0,
            )
        )

    def create_case(self, request: dict, actor: dict) -> dict:
        digest = canonical_hash({"request": request, "requester_id": actor["actor_id"]})
        case_id = str(uuid.uuid4())
        data = {
            "schema_version": "1.0",
            "id": case_id,
            "correlation_id": case_id,
            "tenant_id": actor["tenant_id"],
            "requester_id": actor["actor_id"],
            "request": request,
            "state": "RECEIVED",
            "reason": "Request durably accepted; waiting for the Temporal worker.",
            "plan": None,
            "approval": None,
            "created_at": timestamp(),
            "updated_at": timestamp(),
        }
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(cases).values(
                        id=case_id,
                        tenant_id=actor["tenant_id"],
                        message_id=request["message_id"],
                        payload_hash=digest,
                        state="RECEIVED",
                        version=1,
                        api_calls=0,
                        data=data,
                    )
                )
                self._event(db, case_id, "request.accepted", {"actor_id": actor["actor_id"]})
                self._outbox(db, case_id, "workflow.start", {"case_id": case_id})
        except IntegrityError:
            with self.engine.connect() as db:
                row = (
                    db.execute(
                        select(cases).where(
                            and_(
                                cases.c.tenant_id == actor["tenant_id"],
                                cases.c.message_id == request["message_id"],
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
            if row is None:
                raise
            if row["payload_hash"] != digest:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", "Message ID was already used with another payload or actor"
                ) from None
            return self.get_case(row["id"])
        return self.get_case(case_id)

    def get_case(self, case_id: str) -> dict:
        with self.engine.connect() as db:
            row = db.execute(select(cases).where(cases.c.id == case_id)).mappings().first()
            if row is None:
                raise DomainError("NOT_FOUND", "Case not found", 404)
            data = copy.deepcopy(row["data"])
            data["api_calls"] = row["api_calls"]
            data["effects"] = [
                dict(r) for r in db.execute(select(effects).where(effects.c.case_id == case_id)).mappings()
            ]
            data["events"] = [
                dict(r)
                for r in db.execute(
                    select(events)
                    .where(events.c.case_id == case_id)
                    .order_by(events.c.created_at, events.c.id)
                ).mappings()
            ]
        return data

    def list_cases(self, tenant_id: str) -> list[dict]:
        with self.engine.connect() as db:
            ids = list(
                db.scalars(
                    select(cases.c.id)
                    .where(cases.c.tenant_id == tenant_id)
                    .order_by(cases.c.data["created_at"].as_string().desc())
                    .limit(500)
                )
            )
        return sorted((self.get_case(i) for i in ids), key=lambda x: x["created_at"], reverse=True)

    def transition(
        self,
        case_id: str,
        allowed: set | frozenset,
        state: str,
        reason: str,
        *,
        changes: dict | None = None,
        event_type: str | None = None,
        outbox_kind: str | None = None,
        decision_expiry: float | None = None,
        expiry_gate: str | None = None,
    ) -> dict:
        with self.engine.begin() as db:
            row = db.execute(select(cases).where(cases.c.id == case_id).with_for_update()).mappings().one()
            if row["state"] not in allowed:
                raise DomainError("STATE_CONFLICT", "Case state changed; reload the case before continuing")
            if decision_expiry is not None and time.time() >= decision_expiry:
                raise DomainError("APPROVAL_EXPIRED", "The approval plan has expired")
            if expiry_gate is not None:
                current_deadline = (row["data"].get("plan") or {}).get("expires_at")
                if current_deadline != expiry_gate:
                    raise DomainError("STATE_CONFLICT", "Approval deadline changed; reload the case")
                if time.time() < datetime.fromisoformat(expiry_gate).timestamp():
                    raise DomainError("APPROVAL_NOT_EXPIRED", "The approval deadline has not passed")
            data = copy.deepcopy(row["data"])
            data.update(changes or {})
            data.update(state=state, reason=reason, updated_at=timestamp())
            result = db.execute(
                update(cases)
                .where(and_(cases.c.id == case_id, cases.c.version == row["version"]))
                .values(data=data, state=state, version=row["version"] + 1)
            )
            if result.rowcount != 1:
                raise DomainError("STATE_CONFLICT", "Concurrent case update; reload")
            self._event(
                db, case_id, event_type or f"case.{state.lower()}", {"state": state, "reason": reason}
            )
            if outbox_kind:
                self._outbox(db, case_id, outbox_kind, {"case_id": case_id, "state": state})
            if state in TERMINAL_STATES and row["state"] != state and outbox_kind != "notification.result":
                self._outbox(db, case_id, "notification.result", {"case_id": case_id, "state": state})
        return self.get_case(case_id)

    def record_event(self, case_id: str, event_type: str, payload: dict):
        with self.engine.begin() as db:
            self._event(db, case_id, event_type, payload)

    def prepare_effect(self, key: str, case_id: str, system: str, operation: str, request: dict):
        digest = canonical_hash(request)
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(effects).values(
                        effect_key=key,
                        case_id=case_id,
                        system=system,
                        operation=operation,
                        status="PREPARED",
                        request_hash=digest,
                        request=request,
                        attempts=0,
                    )
                )
                self._event(db, case_id, "effect.prepared", {"effect_key": key, "system": system})
        except IntegrityError:
            existing = self.effect(key)
            if existing is None or existing["request_hash"] != digest or existing["case_id"] != case_id:
                raise DomainError(
                    "EFFECT_KEY_CONFLICT", "Effect key was reused with a different payload"
                ) from None
        return self.effect(key)

    def effect(self, key: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(effects).where(effects.c.effect_key == key)).mappings().first()
            return dict(row) if row else None

    def effect_attempt(self, key: str, max_attempts: int):
        with self.engine.begin() as db:
            result = db.execute(
                update(effects)
                .where(
                    and_(
                        effects.c.effect_key == key,
                        effects.c.status.in_(["PREPARED", "UNKNOWN"]),
                        effects.c.attempts < max_attempts,
                    )
                )
                .values(attempts=effects.c.attempts + 1, status="UNKNOWN")
            )
            if result.rowcount != 1:
                observed = db.scalar(select(effects.c.status).where(effects.c.effect_key == key))
                if observed in {"APPLIED", "COMPENSATED"}:
                    raise DomainError(
                        "EFFECT_ALREADY_OBSERVED",
                        "An overlapping attempt already recorded this effect; reconcile it",
                    )
                raise DomainError(
                    "WRITE_BUDGET_EXHAUSTED", "Write attempt budget exhausted; reconcile before replay"
                )

    def record_effect(self, key: str, before: dict | None, after: dict, *, status: str = "APPLIED"):
        with self.engine.begin() as db:
            row = db.execute(select(effects).where(effects.c.effect_key == key)).mappings().one()
            db.execute(
                update(effects)
                .where(effects.c.effect_key == key)
                .values(status=status, before=before, after=after)
            )
            self._event(
                db,
                row["case_id"],
                "effect.observed",
                {"effect_key": key, "system": row["system"], "status": status},
            )

    def reject_effect(self, key: str, code: str, expected_attempts: int):
        """Only a definitive first-attempt refusal proves that no earlier timed-out attempt committed."""
        with self.engine.begin() as db:
            row = db.execute(select(effects).where(effects.c.effect_key == key)).mappings().one()
            changed = db.execute(
                update(effects)
                .where(
                    and_(
                        effects.c.effect_key == key,
                        effects.c.status == "UNKNOWN",
                        effects.c.attempts == expected_attempts,
                    )
                )
                .values(status="REJECTED")
            )
            if changed.rowcount:
                self._event(db, row["case_id"], "effect.refused", {"effect_key": key, "code": code})

    def consume_api_call(self, case_id: str, maximum: int):
        with self.engine.begin() as db:
            result = db.execute(
                update(cases)
                .where(and_(cases.c.id == case_id, cases.c.api_calls < maximum))
                .values(api_calls=cases.c.api_calls + 1)
            )
            if result.rowcount != 1:
                raise DomainError(
                    "API_BUDGET_EXHAUSTED", "Case API budget exhausted; operator reconciliation required"
                )

    def acquire_slot(self, system: str, maximum: int, duration: float) -> str:
        now = time.time()
        key = str(uuid.uuid4())
        with self.engine.begin() as db:
            row = (
                db.execute(select(systems).where(systems.c.name == system).with_for_update()).mappings().one()
            )
            if row["open_until"] > now:
                raise TransientError(f"{system} circuit is open", row["open_until"] - now)
            # This CAS serialises admission across workers even where FOR UPDATE is ignored.
            changed = db.execute(
                update(systems)
                .where(and_(systems.c.name == system, systems.c.version == row["version"]))
                .values(version=row["version"] + 1)
            )
            if changed.rowcount != 1:
                raise TransientError(f"{system} admission contention", 1)
            db.execute(delete(leases).where(leases.c.expires_at < now))
            count = db.scalar(select(func.count()).select_from(leases).where(leases.c.system == system))
            if count >= maximum:
                raise TransientError(f"{system} concurrency limit reached", 1)
            db.execute(insert(leases).values(id=key, system=system, expires_at=now + duration))
        return key

    def release_slot(
        self,
        key: str,
        system: str,
        *,
        failed: bool,
        threshold: int,
        reset: int,
        retry_after: float | None = None,
    ):
        from sqlalchemy import case

        with self.engine.begin() as db:
            # Acquire the system write lock before touching leases, the same order
            # as acquire_slot. On SQLite, a no-op UPDATE also serializes writers.
            db.execute(
                update(systems).where(systems.c.name == system).values(version=systems.c.version)
            )
            lease_expiry = db.scalar(
                select(leases.c.expires_at).where(and_(leases.c.id == key, leases.c.system == system))
            )
            if lease_expiry is None:
                # A duplicate or superseded worker must not change circuit state.
                return
            db.execute(delete(leases).where(and_(leases.c.id == key, leases.c.system == system)))
            if lease_expiry <= time.time():
                # Expired owners cannot reset newer failure counts or open a circuit.
                return
            failures = systems.c.failures + 1 if failed else 0
            opened = systems.c.open_until
            if failed:
                now = time.time()
                deadlines = [
                    now + max(0, retry_after or 0),
                    case((failures >= threshold, now + reset), else_=0),
                ]
                for deadline in deadlines:
                    opened = case((opened < deadline, deadline), else_=opened)
            db.execute(
                update(systems)
                .where(systems.c.name == system)
                .values(failures=failures, open_until=opened, version=systems.c.version + 1)
            )

    def pending_outbox(self, limit: int = 100) -> list[dict]:
        with self.engine.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    select(outbox)
                    .where(
                        and_(
                            outbox.c.delivered_at.is_(None),
                            outbox.c.available_at <= time.time(),
                            outbox.c.dead == 0,
                        )
                    )
                    .order_by(outbox.c.available_at, outbox.c.id)
                    .limit(limit)
                ).mappings()
            ]

    def ack_outbox(self, event_id: str):
        with self.engine.begin() as db:
            db.execute(
                update(outbox)
                .where(outbox.c.id == event_id)
                .values(delivered_at=time.time(), last_error=None, dead=0)
            )

    def fail_outbox(self, event_id: str, error: str, max_attempts: int = 8):
        with self.engine.begin() as db:
            row = db.execute(select(outbox).where(outbox.c.id == event_id).with_for_update()).mappings().one()
            if row["delivered_at"] is not None or row["dead"]:
                return
            attempt = row["attempts"] + 1
            db.execute(
                update(outbox)
                .where(
                    and_(
                        outbox.c.id == event_id,
                        outbox.c.delivered_at.is_(None),
                        outbox.c.dead == 0,
                        outbox.c.attempts == row["attempts"],
                    )
                )
                .values(
                    attempts=attempt,
                    last_error=error[:200],
                    available_at=time.time() + min(2**attempt, 300),
                    dead=int(attempt >= max_attempts),
                )
            )

    def case_counts(self, tenant_id: str) -> dict:
        with self.engine.connect() as db:
            return dict(
                db.execute(
                    select(cases.c.state, func.count())
                    .where(cases.c.tenant_id == tenant_id)
                    .group_by(cases.c.state)
                ).all()
            )

    def outbox_stats(self, tenant_id: str | None = None) -> dict:
        with self.engine.connect() as db:
            source = outbox.join(cases, outbox.c.case_id == cases.c.id) if tenant_id is not None else outbox
            scope = cases.c.tenant_id == tenant_id if tenant_id is not None else True
            return {
                "pending": db.scalar(
                    select(func.count())
                    .select_from(source)
                    .where(and_(scope, outbox.c.delivered_at.is_(None)))
                ),
                "dead": db.scalar(
                    select(func.count()).select_from(source).where(and_(scope, outbox.c.dead == 1))
                ),
            }

    def replay_outbox(self, event_id: str):
        """Explicit CLI operation, preserving the original event and idempotency identity."""
        with self.engine.begin() as db:
            row = (
                db.execute(select(outbox).where(outbox.c.id == event_id).with_for_update()).mappings().first()
            )
            if not row or not row["dead"] or row["delivered_at"]:
                raise DomainError("NOT_REPLAYABLE", "Only dead, undelivered outbox entries can be replayed")
            db.execute(
                update(outbox)
                .where(outbox.c.id == event_id)
                .values(dead=0, attempts=0, available_at=time.time())
            )
            self._event(db, row["case_id"], "outbox.replay_requested", {"event_id": event_id})

    def close(self):
        self.engine.dispose()
