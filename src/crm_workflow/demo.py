"""Persistent synthetic systems for local exercises, never Salesforce/MuleSoft emulators.

The reference systems implement their own atomic compare-and-set and effect ledger.
They deliberately identify themselves as synthetic in capability responses and UI links.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, and_, insert, select, update

from crm_workflow.errors import DomainError
from crm_workflow.models import canonical_hash, utcnow

demo_meta = MetaData()
customers = Table(
    "demo_customers",
    demo_meta,
    Column("id", String(100), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("reference", String(100), nullable=False),
    Column("data", JSON),
)
orders = Table(
    "demo_orders",
    demo_meta,
    Column("id", String(100), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("customer_id", String(100), nullable=False),
    Column("reference", String(100), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("data", JSON),
)
crm_effects = Table(
    "demo_crm_effects",
    demo_meta,
    Column("key", String(150), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("request_hash", String(64)),
    Column("data", JSON),
)
inventory = Table(
    "demo_inventory",
    demo_meta,
    Column("id", String(200), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("sku", String(100), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("available", Integer, nullable=False),
)
reservations = Table(
    "demo_reservations",
    demo_meta,
    Column("key", String(150), primary_key=True),
    Column("tenant_id", String(100), nullable=False),
    Column("request_hash", String(64)),
    Column("data", JSON),
)


def seed_demo(store, *, count: int = 3):
    """Only insert absent synthetic fixtures; startup never overwrites observed effects."""
    demo_meta.create_all(store.engine)
    with store.engine.begin() as db:
        for tenant, suffix in [("demo-industrial", ""), ("other-industrial", "-other")]:
            customer_id = f"customer-001{suffix}"
            if not db.scalar(select(customers.c.id).where(customers.c.id == customer_id)):
                data = {
                    "customer_id": customer_id,
                    "tenant_id": tenant,
                    "reference": "CUST-001",
                    "name": "Fictional Industrial Components",
                }
                db.execute(
                    insert(customers).values(
                        id=customer_id, tenant_id=tenant, reference="CUST-001", data=data
                    )
                )
            for index in range(count):
                order_id, reference, sku = (
                    f"order-{1001 + index}{suffix}",
                    f"ORD-{1001 + index}",
                    f"SKU-{index + 1:03d}",
                )
                if not db.scalar(select(orders.c.id).where(orders.c.id == order_id)):
                    data = {
                        "order_id": order_id,
                        "tenant_id": tenant,
                        "customer_id": customer_id,
                        "reference": reference,
                        "sku": sku,
                        "quantity": 10,
                        "requested_date": (date.today() + timedelta(days=7)).isoformat(),
                        "revision": 1,
                        "crm_url": f"demo://orders/{order_id}",
                        "last_effect_key": None,
                    }
                    db.execute(
                        insert(orders).values(
                            id=order_id,
                            tenant_id=tenant,
                            customer_id=customer_id,
                            reference=reference,
                            revision=1,
                            data=data,
                        )
                    )
                inv_id = f"{tenant}:{sku}"
                if not db.scalar(select(inventory.c.id).where(inventory.c.id == inv_id)):
                    db.execute(
                        insert(inventory).values(
                            id=inv_id, tenant_id=tenant, sku=sku, revision=1, available=100
                        )
                    )


class DemoCRM:
    def __init__(self, store):
        self.store = store

    async def capabilities(self):
        return {
            "system": "synthetic-crm",
            "schema_version": "1.0",
            "provider_verified": False,
            "operations": ["change_delivery_date", "compensate_delivery_date"],
        }

    async def customers(self, tenant_id, reference):
        with self.store.engine.connect() as db:
            return list(
                db.scalars(
                    select(customers.c.data).where(
                        and_(customers.c.tenant_id == tenant_id, customers.c.reference == reference)
                    )
                )
            )

    async def orders(self, tenant_id, customer_id, reference):
        with self.store.engine.connect() as db:
            return list(
                db.scalars(
                    select(orders.c.data).where(
                        and_(
                            orders.c.tenant_id == tenant_id,
                            orders.c.customer_id == customer_id,
                            orders.c.reference == reference,
                        )
                    )
                )
            )

    async def order(self, tenant_id, order_id):
        with self.store.engine.connect() as db:
            data = db.scalar(
                select(orders.c.data).where(and_(orders.c.id == order_id, orders.c.tenant_id == tenant_id))
            )
        if data is None:
            raise DomainError("NOT_FOUND", "Order not found for this tenant", 404)
        return data

    async def effect(self, tenant_id, key):
        with self.store.engine.connect() as db:
            return db.scalar(
                select(crm_effects.c.data).where(
                    and_(crm_effects.c.key == key, crm_effects.c.tenant_id == tenant_id)
                )
            )

    async def apply(self, order_id, payload, correlation_id):
        digest = canonical_hash(payload)
        with self.store.engine.begin() as db:
            previous = (
                db.execute(select(crm_effects).where(crm_effects.c.key == payload["effect_key"]))
                .mappings()
                .first()
            )
            if previous:
                if previous["tenant_id"] != payload["tenant_id"] or previous["request_hash"] != digest:
                    raise DomainError(
                        "EFFECT_KEY_CONFLICT", "Remote effect key conflicts with the requested mutation"
                    )
                return {**previous["data"], "replayed": True}
            row = (
                db.execute(
                    select(orders)
                    .where(and_(orders.c.id == order_id, orders.c.tenant_id == payload["tenant_id"]))
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row or row["customer_id"] != payload["customer_id"]:
                raise DomainError("NOT_FOUND", "Order identity is outside the authorised scope", 404)
            before = row["data"]
            if row["revision"] != payload["expected_revision"]:
                raise DomainError("STATE_CHANGED", "CRM revision changed before mutation")
            if utcnow() >= datetime.fromisoformat(payload["expires_at"]):
                raise DomainError("APPROVAL_EXPIRED", "Approved mutation expired before the remote write")
            if payload["operation"] not in {"change_delivery_date", "compensate_delivery_date"}:
                raise DomainError("OPERATION_DENIED", "Operation is not allowed", 403)
            if payload["operation"] == "compensate_delivery_date":
                original = db.scalar(
                    select(crm_effects.c.data).where(crm_effects.c.key == payload["compensates_effect_key"])
                )
                if (
                    not original
                    or original["after"] != before
                    or original["before"]["requested_date"] != payload["requested_date"]
                ):
                    raise DomainError(
                        "COMPENSATION_CONFLICT", "Original effect no longer matches the CRM state"
                    )
            after = {
                **before,
                "requested_date": payload["requested_date"],
                "revision": before["revision"] + 1,
                "last_effect_key": payload["effect_key"],
            }
            result = db.execute(
                update(orders)
                .where(and_(orders.c.id == order_id, orders.c.revision == before["revision"]))
                .values(data=after, revision=after["revision"])
            )
            if result.rowcount != 1:
                raise DomainError("STATE_CHANGED", "Concurrent CRM update")
            response = {
                "effect_key": payload["effect_key"],
                "order_id": order_id,
                "before": before,
                "after": after,
                "replayed": False,
                "observed_revision": after["revision"],
                "approved_plan_hash": payload["approved_plan_hash"],
                "request_hash": digest,
            }
            db.execute(
                insert(crm_effects).values(
                    key=payload["effect_key"],
                    tenant_id=payload["tenant_id"],
                    request_hash=digest,
                    data=response,
                )
            )
        return response

    def human_change(self, order_id: str, requested_date: str):
        """Test/seed utility only. Never exposed over the operator API."""
        with self.store.engine.begin() as db:
            row = db.execute(select(orders).where(orders.c.id == order_id).with_for_update()).mappings().one()
            data = {
                **row["data"],
                "requested_date": requested_date,
                "revision": row["revision"] + 1,
                "last_effect_key": None,
            }
            db.execute(
                update(orders).where(orders.c.id == order_id).values(data=data, revision=data["revision"])
            )


class DemoERP:
    def __init__(self, store):
        self.store = store

    async def availability(self, tenant_id, sku):
        with self.store.engine.connect() as db:
            row = (
                db.execute(
                    select(inventory).where(and_(inventory.c.tenant_id == tenant_id, inventory.c.sku == sku))
                )
                .mappings()
                .first()
            )
        if row is None:
            raise DomainError("SKU_UNKNOWN", "SKU has no availability record", 404)
        return {k: row[k] for k in ("tenant_id", "sku", "revision", "available")}

    async def reservation(self, tenant_id, key):
        with self.store.engine.connect() as db:
            return db.scalar(
                select(reservations.c.data).where(
                    and_(reservations.c.key == key, reservations.c.tenant_id == tenant_id)
                )
            )

    async def reserve(self, payload, correlation_id):
        digest = canonical_hash(payload)
        with self.store.engine.begin() as db:
            existing = (
                db.execute(select(reservations).where(reservations.c.key == payload["effect_key"]))
                .mappings()
                .first()
            )
            if existing:
                if existing["tenant_id"] != payload["tenant_id"] or existing["request_hash"] != digest:
                    raise DomainError(
                        "EFFECT_KEY_CONFLICT", "Reservation key conflicts with its original request"
                    )
                return {**existing["data"], "replayed": True}
            if datetime.fromisoformat(payload["expires_at"]) <= utcnow():
                raise DomainError("APPROVAL_EXPIRED", "Reservation authorisation has expired")
            row = (
                db.execute(
                    select(inventory)
                    .where(
                        and_(inventory.c.tenant_id == payload["tenant_id"], inventory.c.sku == payload["sku"])
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None or row["revision"] != payload["expected_revision"]:
                raise DomainError("STOCK_CHANGED", "Availability changed since approval")
            if not 0 < payload["quantity"] <= row["available"]:
                raise DomainError("INSUFFICIENT_STOCK", "Requested stock is no longer available")
            changed = db.execute(
                update(inventory)
                .where(and_(inventory.c.id == row["id"], inventory.c.revision == row["revision"]))
                .values(available=row["available"] - payload["quantity"], revision=row["revision"] + 1)
            )
            if changed.rowcount != 1:
                raise DomainError("STOCK_CHANGED", "Concurrent reservation changed availability")
            result = {**payload, "status": "reserved", "revision": row["revision"] + 1, "replayed": False}
            db.execute(
                insert(reservations).values(
                    key=payload["effect_key"],
                    tenant_id=payload["tenant_id"],
                    request_hash=digest,
                    data=result,
                )
            )
        return result

    def change_stock(self, tenant_id: str, sku: str, available: int):
        with self.store.engine.begin() as db:
            db.execute(
                update(inventory)
                .where(and_(inventory.c.tenant_id == tenant_id, inventory.c.sku == sku))
                .values(available=available, revision=inventory.c.revision + 1)
            )
