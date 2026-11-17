from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import ValidationError

from crm_workflow.config import Settings
from crm_workflow.errors import DomainError, TransientError
from crm_workflow.models import (
    TERMINAL_STATES,
    ActionPlan,
    Actor,
    ApprovalRequest,
    Availability,
    Customer,
    Order,
    OrderRequest,
    canonical_hash,
    timestamp,
    utcnow,
)


class CaseService:
    def __init__(self, store, crm, erp, proposer, settings: Settings):
        self.store, self.crm, self.erp, self.proposer, self.settings = store, crm, erp, proposer, settings

    @staticmethod
    def require_role(actor: Actor, *roles: str):
        if not set(actor.roles).intersection(roles):
            raise DomainError("FORBIDDEN", "This identity does not have the required role", 403)

    async def get_case(self, case_id: str, actor: Actor) -> dict:
        case = self.store.get_case(case_id)
        if case["tenant_id"] != actor.tenant_id:
            raise DomainError("NOT_FOUND", "Case not found", 404)
        return case

    async def list_cases(self, actor: Actor) -> list[dict]:
        return self.store.list_cases(actor.tenant_id)

    async def create_case(self, request: OrderRequest, actor: Actor) -> dict:
        self.require_role(actor, "requester")
        return self.store.create_case(request.model_dump(mode="json"), actor.model_dump())

    async def _call(self, case_id, system, operation, *args):
        maximum = self.settings.crm_concurrency if system == "crm" else self.settings.erp_concurrency
        lease = self.store.acquire_slot(system, maximum, self.settings.activity_timeout_seconds + 10)
        failed, delay = False, None
        try:
            self.store.consume_api_call(case_id, self.settings.max_case_api_calls)
            return await operation(*args)
        except TransientError as exc:
            failed, delay = True, exc.retry_after
            self.store.record_event(
                case_id,
                "system.transient_failure",
                {"system": system, "error_type": type(exc).__name__, "retry_after": delay},
            )
            raise
        finally:
            self.store.release_slot(
                lease,
                system,
                failed=failed,
                threshold=self.settings.circuit_failures,
                reset=self.settings.circuit_reset_seconds,
                retry_after=delay,
            )

    def _transition(self, case, state, reason, **kwargs):
        try:
            return self.store.transition(case["id"], {case["state"]}, state, reason, **kwargs)
        except DomainError as exc:
            if exc.code != "STATE_CONFLICT":
                raise
            # An overlapping activity/decision has advanced the case. Never turn that
            # successful transition into a failure or overwrite its business outcome.
            return self.store.get_case(case["id"])

    async def prepare(self, case_id: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] != "RECEIVED":
            return case
        request = OrderRequest.model_validate(case["request"])
        try:
            intent = await self._call(case_id, "llm", self.proposer.interpret, request)
            if (
                not date.today()
                < intent.requested_date
                <= date.today() + timedelta(days=self.settings.max_delivery_shift_days)
            ):
                raise DomainError(
                    "DATE_OUTSIDE_POLICY",
                    "Delivery date must be in the future and within the configured policy window",
                )
            people = await self._call(
                case_id, "crm", self.crm.customers, case["tenant_id"], intent.customer_reference
            )
            if len(people) != 1:
                raise DomainError(
                    "CUSTOMER_UNKNOWN" if not people else "CUSTOMER_AMBIGUOUS",
                    "Customer reference did not resolve to exactly one authorised customer",
                )
            customer = Customer.model_validate(people[0])
            if customer.tenant_id != case["tenant_id"] or customer.reference != intent.customer_reference:
                raise DomainError(
                    "REMOTE_IDENTITY_MISMATCH", "CRM returned an identity outside the requested scope", 403
                )
            items = await self._call(
                case_id,
                "crm",
                self.crm.orders,
                case["tenant_id"],
                customer.customer_id,
                intent.order_reference,
            )
            if len(items) != 1:
                raise DomainError(
                    "ORDER_UNKNOWN" if not items else "ORDER_AMBIGUOUS",
                    "Order reference did not resolve to exactly one authorised order",
                )
            order = Order.model_validate(items[0])
            if (
                order.tenant_id != case["tenant_id"]
                or order.customer_id != customer.customer_id
                or order.reference != intent.order_reference
            ):
                raise DomainError(
                    "REMOTE_IDENTITY_MISMATCH", "CRM order is outside the requested customer scope", 403
                )
            stock = Availability.model_validate(
                await self._call(case_id, "erp", self.erp.availability, case["tenant_id"], order.sku)
            )
            if stock.tenant_id != case["tenant_id"] or stock.sku != order.sku:
                raise DomainError(
                    "REMOTE_IDENTITY_MISMATCH", "Inventory belongs to a different tenant or SKU", 403
                )
            if stock.available < order.quantity:
                return self._transition(
                    case, "ESCALATED", "Insufficient stock; no delivery date change has been authorised"
                )
            if order.requested_date == intent.requested_date:
                raise DomainError(
                    "NO_CHANGE_NEEDED", "The requested delivery date already matches the CRM order"
                )
            plan = ActionPlan(
                case_id=case_id,
                tenant_id=case["tenant_id"],
                requester_id=case["requester_id"],
                customer=customer,
                order=order,
                availability=stock,
                requested_date=intent.requested_date,
                expires_at=utcnow() + timedelta(seconds=self.settings.approval_ttl_seconds),
            ).model_dump(mode="json")
            plan["hash"] = canonical_hash(plan)
            self.store.record_event(
                case_id,
                "proposal.structured",
                {
                    "provider": self.proposer.name,
                    "request_hash": canonical_hash(case["request"]),
                    "intent": intent.model_dump(mode="json"),
                },
            )
            return self._transition(
                case,
                "AWAITING_APPROVAL",
                "A separate approver must authorise this exact plan",
                changes={"plan": plan},
            )
        except DomainError as exc:
            state = (
                "ESCALATED"
                if exc.code in {"PROVIDER_FORBIDDEN", "PROVIDER_UNAUTHENTICATED", "REMOTE_IDENTITY_MISMATCH"}
                else "NEEDS_CLARIFICATION"
            )
            return self._transition(case, state, f"{exc.code}: {exc.message}")
        except (ValidationError, KeyError, TypeError) as exc:
            return self._transition(
                case,
                "ESCALATED",
                f"REMOTE_SCHEMA: response did not match the versioned contract ({type(exc).__name__})",
            )

    @staticmethod
    def _plan(case: dict, *, require_approval: bool = True, require_unexpired: bool = True) -> dict:
        plan = dict(case.get("plan") or {})
        digest = plan.pop("hash", None)
        try:
            checked = ActionPlan.model_validate(plan)
        except ValidationError as exc:
            raise DomainError("INVALID_PLAN", "Stored plan no longer matches the approved contract") from exc
        if (
            digest != canonical_hash(plan)
            or checked.case_id != case["id"]
            or checked.tenant_id != case["tenant_id"]
        ):
            raise DomainError("PLAN_TAMPERED", "Plan scope or integrity changed")
        if checked.requester_id != case["requester_id"]:
            raise DomainError("PLAN_TAMPERED", "Requester identity changed")
        if require_unexpired and checked.expires_at <= utcnow():
            raise DomainError("APPROVAL_EXPIRED", "Approved plan has expired")
        if require_approval:
            approval = case.get("approval") or {}
            if (
                approval.get("plan_hash") != digest
                or approval.get("decision") != "approve"
                or approval.get("actor_id") == case["requester_id"]
                or approval.get("tenant_id") != case["tenant_id"]
            ):
                raise DomainError(
                    "APPROVAL_SCOPE", "No valid independent approval covers this exact plan", 403
                )
        return {**plan, "hash": digest}

    async def approve(self, case_id: str, approval: ApprovalRequest, actor: Actor) -> dict:
        self.require_role(actor, "approver")
        case = await self.get_case(case_id, actor)
        if case["requester_id"] == actor.actor_id:
            raise DomainError("SEPARATION_OF_DUTIES", "The requester cannot approve their own case", 403)
        if case["state"] != "AWAITING_APPROVAL":
            raise DomainError("STATE_CONFLICT", "Case is not awaiting an approval")
        plan = self._plan(case, require_approval=False)
        if approval.plan_hash != plan["hash"]:
            raise DomainError("STALE_APPROVAL", "The approval refers to a different plan")
        saved = {
            **approval.model_dump(),
            "actor_id": actor.actor_id,
            "tenant_id": actor.tenant_id,
            "approved_at": timestamp(),
        }
        return self.store.transition(
            case_id,
            {"AWAITING_APPROVAL"},
            "APPROVED" if approval.decision == "approve" else "REJECTED",
            "Decision recorded by a separate authorised approver",
            changes={"approval": saved},
            outbox_kind="workflow.decision",
            decision_expiry=datetime.fromisoformat(plan["expires_at"]).timestamp(),
        )

    async def expire(self, case_id: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] != "AWAITING_APPROVAL":
            return case
        plan = self._plan(case, require_approval=False, require_unexpired=False)
        deadline = datetime.fromisoformat(plan["expires_at"])
        if deadline.tzinfo is None:
            raise DomainError("INVALID_PLAN", "Approval deadline must be timezone-aware")
        if utcnow() < deadline:
            # A premature activity invocation cannot shorten the approved waiting window.
            return self.store.get_case(case_id)
        try:
            return self._transition(
                case,
                "EXPIRED",
                "No valid approval was committed before the plan expired",
                expiry_gate=plan["expires_at"],
            )
        except DomainError as exc:
            if exc.code != "APPROVAL_NOT_EXPIRED":
                raise
            # A deadline race can resolve only after the transactional guard executes.
            return self.store.get_case(case_id)

    @staticmethod
    def _crm_request(case, plan, *, compensation=False, original=None):
        payload = {
            "tenant_id": case["tenant_id"],
            "customer_id": plan["order"]["customer_id"],
            "effect_key": f"{case['id']}:crm" + (":compensate" if compensation else ""),
            "expected_revision": original["after"]["revision"] if compensation else plan["order"]["revision"],
            "operation": "compensate_delivery_date" if compensation else "change_delivery_date",
            "requested_date": plan["order"]["requested_date"] if compensation else plan["requested_date"],
            "approved_plan_hash": plan["hash"],
            "expires_at": plan["expires_at"],
        }
        if compensation:
            payload["compensates_effect_key"] = f"{case['id']}:crm"
        return payload

    @staticmethod
    def _validate_crm_effect(observed, case, plan, *, payload):
        try:
            before, after = Order.model_validate(observed["before"]), Order.model_validate(observed["after"])
        except (ValidationError, KeyError, TypeError) as exc:
            raise DomainError("EFFECT_UNPROVEN", "CRM effect evidence is incomplete") from exc
        if (
            observed.get("effect_key") != payload["effect_key"]
            or observed.get("order_id") != plan["order"]["order_id"]
            or observed.get("approved_plan_hash") != plan["hash"]
            or observed.get("observed_revision") != after.revision
            or before.order_id != after.order_id
            or after.order_id != plan["order"]["order_id"]
            or before.tenant_id != case["tenant_id"]
            or after.tenant_id != case["tenant_id"]
            or before.customer_id != payload["customer_id"]
            or after.customer_id != payload["customer_id"]
            or before.revision != payload["expected_revision"]
            or after.revision != before.revision + 1
            or after.requested_date.isoformat() != payload["requested_date"]
            or after.last_effect_key != payload["effect_key"]
            or before.sku != after.sku
            or before.quantity != after.quantity
            or before.reference != after.reference
            or before.sku != plan["order"]["sku"]
            or before.quantity != plan["order"]["quantity"]
        ):
            raise DomainError("EFFECT_SCOPE_MISMATCH", "Remote effect does not prove the approved mutation")
        expected_before = dict(plan["order"])
        if payload["operation"] == "compensate_delivery_date":
            expected_before.update(
                requested_date=plan["requested_date"],
                revision=plan["order"]["revision"] + 1,
                last_effect_key=f"{case['id']}:crm",
            )
        expected_after = {
            **expected_before,
            "requested_date": payload["requested_date"],
            "revision": expected_before["revision"] + 1,
            "last_effect_key": payload["effect_key"],
        }
        if (
            before.model_dump(mode="json") != expected_before
            or after.model_dump(mode="json") != expected_after
        ):
            raise DomainError(
                "EFFECT_SCOPE_MISMATCH", "CRM changed a value outside the approved field and revision"
            )
        return observed

    async def execute_crm(self, case_id: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] != "APPROVED":
            return case
        key = f"{case_id}:crm"
        try:
            # Reconciliation remains permitted after expiry; a new write does not.
            plan = self._plan(case, require_unexpired=False)
            payload = self._crm_request(case, plan)
            self.store.prepare_effect(key, case_id, "crm", payload["operation"], payload)
            observed = await self._call(case_id, "crm", self.crm.effect, case["tenant_id"], key)
            if observed is None:
                self._plan(case)
                current = Order.model_validate(
                    await self._call(
                        case_id, "crm", self.crm.order, case["tenant_id"], plan["order"]["order_id"]
                    )
                ).model_dump(mode="json")
                stock = Availability.model_validate(
                    await self._call(
                        case_id, "erp", self.erp.availability, case["tenant_id"], plan["order"]["sku"]
                    )
                ).model_dump(mode="json")
                if current != plan["order"] or stock != plan["availability"]:
                    raise DomainError(
                        "PRECONDITION_CHANGED", "CRM or availability changed after the plan was approved"
                    )
                self.store.effect_attempt(key, self.settings.retry_max_attempts)
                observed = await self._call(
                    case_id, "crm", self.crm.apply, plan["order"]["order_id"], payload, case["correlation_id"]
                )
            self._validate_crm_effect(observed, case, plan, payload=payload)
            self.store.record_effect(key, observed["before"], observed["after"])
            return self._transition(
                case, "CRM_APPLIED", "CRM effect was observed and matched the approved plan"
            )
        except DomainError as exc:
            effect = self.store.effect(key)
            uncertain = effect and effect["status"] in {"UNKNOWN", "APPLIED"}
            return self._transition(
                case,
                "RECONCILIATION_REQUIRED" if uncertain else "APPROVAL_INVALIDATED",
                f"{exc.code}: {exc.message}",
            )

    @staticmethod
    def _reservation_payload(case, plan):
        return {
            "effect_key": f"{case['id']}:stock",
            "tenant_id": case["tenant_id"],
            "order_id": plan["order"]["order_id"],
            "sku": plan["order"]["sku"],
            "quantity": plan["order"]["quantity"],
            "expected_revision": plan["availability"]["revision"],
            "approved_plan_hash": plan["hash"],
            "expires_at": plan["expires_at"],
        }

    @staticmethod
    def _validate_reservation(result, payload):
        if result.get("status") != "reserved" or any(result.get(k) != v for k, v in payload.items()):
            raise DomainError("RESERVATION_UNPROVEN", "Reservation does not match the approved stock scope")

    async def reserve_stock(self, case_id: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] != "CRM_APPLIED":
            return case
        plan = self._plan(case, require_unexpired=False)
        payload = self._reservation_payload(case, plan)
        key = payload["effect_key"]
        journal = self.store.prepare_effect(key, case_id, "erp", "reserve_stock", payload)
        observed = await self._call(case_id, "erp", self.erp.reservation, case["tenant_id"], key)
        if observed is None:
            self._plan(case)
            self.store.effect_attempt(key, self.settings.retry_max_attempts)
            try:
                observed = await self._call(case_id, "erp", self.erp.reserve, payload, case["correlation_id"])
            except DomainError as exc:
                if journal["attempts"] == 0 and exc.code in {
                    "STOCK_CHANGED",
                    "INSUFFICIENT_STOCK",
                    "STATE_CHANGED",
                    "APPROVAL_EXPIRED",
                    "PROVIDER_FORBIDDEN",
                    "PROVIDER_UNAUTHENTICATED",
                    "REMOTE_REJECTED",
                }:
                    self.store.reject_effect(key, exc.code, expected_attempts=1)
                raise
        self._validate_reservation(observed, payload)
        self.store.record_effect(key, plan["availability"], observed)
        return self._transition(
            case, "STOCK_RESERVED", "ERP reservation was observed against its idempotency key"
        )

    async def _readback(self, case):
        plan = self._plan(case, require_unexpired=False)
        current = Order.model_validate(
            await self._call(case["id"], "crm", self.crm.order, case["tenant_id"], plan["order"]["order_id"])
        ).model_dump(mode="json")
        if (
            current["tenant_id"] != case["tenant_id"]
            or current["order_id"] != plan["order"]["order_id"]
            or current["customer_id"] != plan["order"]["customer_id"]
        ):
            raise DomainError(
                "REMOTE_IDENTITY_MISMATCH", "CRM readback returned an object outside this case scope", 502
            )
        reservation = await self._call(
            case["id"], "erp", self.erp.reservation, case["tenant_id"], f"{case['id']}:stock"
        )
        if reservation and (
            reservation.get("tenant_id") != case["tenant_id"]
            or reservation.get("order_id") != plan["order"]["order_id"]
        ):
            raise DomainError(
                "REMOTE_IDENTITY_MISMATCH", "ERP readback returned an object outside this case scope", 502
            )
        crm_effect = self.store.effect(f"{case['id']}:crm")
        compensation = self.store.effect(f"{case['id']}:crm:compensate")
        compensated = compensation and compensation["status"] == "COMPENSATED"
        expected = (
            compensation["after"]
            if compensated
            else (crm_effect["after"] if crm_effect and crm_effect["status"] == "APPLIED" else None)
        )
        differences = []
        if expected != current:
            differences.append("CRM current state differs from the observed workflow effect")
        if compensated:
            if reservation is not None:
                differences.append("An ERP reservation exists after CRM compensation")
        else:
            try:
                self._validate_reservation(reservation or {}, self._reservation_payload(case, plan))
            except DomainError:
                differences.append("ERP reservation is absent or differs from the approved scope")
        return {
            "checked_at": timestamp(),
            "crm_order": current,
            "reservation": reservation,
            "matches": not differences,
            "differences": differences,
            "expected_outcome": "compensated" if compensated else "fulfilled",
            "profile": self.settings.profile,
            "provider_acceptance": "not_asserted",
        }

    async def verify(self, case_id: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] != "STOCK_RESERVED":
            return case
        observed = await self._readback(case)
        return self._transition(
            case,
            "COMPLETED" if observed["matches"] else "RECONCILIATION_REQUIRED",
            "CRM and ERP rereads match the approved effects"
            if observed["matches"]
            else "Remote readback differs; no blind rollback",
            changes={"reconciliation": observed},
            outbox_kind="notification.result",
        )

    async def reconcile(self, case_id: str, actor: Actor) -> dict:
        self.require_role(actor, "operator")
        case = await self.get_case(case_id, actor)
        if not case.get("approval") or case["approval"]["decision"] != "approve":
            raise DomainError("NO_APPROVED_PLAN", "There is no approved effect to reconcile")
        observed = await self._readback(case)
        # Keep workflow outcome as history; report live drift explicitly instead of relabelling old completion.
        return self._transition(
            case,
            case["state"],
            "Operator requested a fresh remote readback",
            changes={"reconciliation": observed},
            event_type="reconciliation.observed",
        )

    async def compensate(self, case_id: str, reason: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] in TERMINAL_STATES:
            return case
        try:
            plan = self._plan(case, require_unexpired=False)
            reservation = await self._call(
                case_id, "erp", self.erp.reservation, case["tenant_id"], f"{case_id}:stock"
            )
            if reservation is not None:
                self._validate_reservation(reservation, self._reservation_payload(case, plan))
                self.store.record_effect(f"{case_id}:stock", plan["availability"], reservation)
                case = self._transition(
                    case, "STOCK_RESERVED", "Lost ERP response reconciled; compensation is unnecessary"
                )
                return await self.verify(case_id)
            stock_journal = self.store.effect(f"{case_id}:stock")
            if stock_journal and stock_journal["status"] == "UNKNOWN":
                raise DomainError(
                    "STOCK_OUTCOME_UNCERTAIN",
                    "A stock write may still be in flight; absence of a receipt does not authorise compensation",
                )
            original = await self._call(case_id, "crm", self.crm.effect, case["tenant_id"], f"{case_id}:crm")
            if original is None:
                return self._transition(
                    case,
                    "RECONCILIATION_REQUIRED",
                    "CRM effect not found; absence alone does not prove a lost write failed",
                )
            if not plan["compensation_allowed"]:
                raise DomainError("COMPENSATION_DENIED", "The approved plan did not authorise compensation")
            payload = self._crm_request(case, plan, compensation=True, original=original)
            self._validate_crm_effect(original, case, plan, payload=self._crm_request(case, plan))
            key = payload["effect_key"]
            self.store.prepare_effect(key, case_id, "crm", payload["operation"], payload)
            restored = await self._call(case_id, "crm", self.crm.effect, case["tenant_id"], key)
            if restored is None:
                self._plan(case)
                current = await self._call(
                    case_id, "crm", self.crm.order, case["tenant_id"], plan["order"]["order_id"]
                )
                if current != original["after"]:
                    raise DomainError("COMPENSATION_CONFLICT", "A newer CRM change prevents compensation")
                self.store.effect_attempt(key, self.settings.retry_max_attempts)
                restored = await self._call(
                    case_id, "crm", self.crm.apply, plan["order"]["order_id"], payload, case["correlation_id"]
                )
            self._validate_crm_effect(restored, case, plan, payload=payload)
            self.store.record_effect(key, restored["before"], restored["after"], status="COMPENSATED")
            current = await self._call(
                case_id, "crm", self.crm.order, case["tenant_id"], plan["order"]["order_id"]
            )
            if current != restored["after"]:
                raise DomainError("COMPENSATION_CONFLICT", "CRM changed after the compensation effect")
            return self._transition(
                case,
                "COMPENSATED",
                "CRM date was conditionally restored; original effects remain in the journal",
                changes={"compensation_reason": reason[:200]},
                outbox_kind="notification.result",
            )
        except DomainError as exc:
            return self._transition(
                case,
                "RECONCILIATION_REQUIRED",
                f"{exc.code}: {exc.message}",
                outbox_kind="notification.result",
            )

    async def fail(self, case_id: str, reason: str) -> dict:
        case = self.store.get_case(case_id)
        if case["state"] in TERMINAL_STATES:
            return case
        has_effect = any(e["status"] in {"UNKNOWN", "APPLIED", "COMPENSATED"} for e in case["effects"])
        return self._transition(
            case,
            "RECONCILIATION_REQUIRED" if has_effect else "FAILED",
            reason[:200],
            outbox_kind="notification.result",
        )
