"""Effect-key ownership and immutable observed evidence regressions.

All mutations target an isolated SQLite fixture; no real provider is contacted.
"""

from __future__ import annotations

import pytest

from crm_workflow.errors import DomainError
from crm_workflow.store import Store

REQUEST = {"operation": "change_delivery_date", "tenant_id": "synthetic", "scope": "approved"}
BEFORE = {"revision": 1, "requested_date": "2026-11-18"}
AFTER = {"revision": 2, "requested_date": "2026-11-20"}


@pytest.fixture
def journal(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'effect-journal.db'}")
    case = store.create_case(
        {"message_id": "synthetic-effect"},
        {"actor_id": "requester", "tenant_id": "synthetic"},
    )
    try:
        yield store, case
    finally:
        store.close()


def observed_events(store, case_id):
    return [
        event
        for event in store.get_case(case_id)["events"]
        if event["event_type"] == "effect.observed"
    ]


@pytest.mark.parametrize(
    ("system", "operation", "request"),
    [
        ("erp", "change_delivery_date", REQUEST),
        ("crm", "compensate_delivery_date", REQUEST),
        ("crm", "change_delivery_date", {**REQUEST, "scope": "different"}),
    ],
)
def test_effect_key_cannot_be_rebound_to_different_operation_or_payload(
    journal, system, operation, request
):
    store, case = journal
    original = store.prepare_effect(
        "stable-effect", case["id"], "crm", "change_delivery_date", REQUEST
    )
    before = store.get_case(case["id"])["events"]
    with pytest.raises(DomainError) as failure:
        store.prepare_effect("stable-effect", case["id"], system, operation, request)
    assert failure.value.code == "EFFECT_KEY_CONFLICT"
    assert store.effect("stable-effect") == original
    assert store.get_case(case["id"])["events"] == before


def test_repeated_identical_intent_and_remote_receipt_are_event_idempotent(journal):
    store, case = journal
    key = "stable-effect"
    original = store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    repeated = store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    assert original == repeated

    store.effect_attempt(key, 3)
    store.record_effect(key, BEFORE, AFTER)
    applied = store.effect(key)
    assert applied["status"] == "APPLIED"
    assert applied["attempts"] == 1
    assert len(observed_events(store, case["id"])) == 1

    # A lost response can produce the same verified receipt again.
    store.record_effect(key, dict(BEFORE), dict(AFTER))
    assert store.effect(key) == applied
    assert len(observed_events(store, case["id"])) == 1


@pytest.mark.parametrize(
    ("before", "after", "status"),
    [
        ({"revision": 9}, AFTER, "APPLIED"),
        (BEFORE, {"revision": 99}, "APPLIED"),
        (BEFORE, AFTER, "COMPENSATED"),
    ],
)
def test_conflicting_or_terminal_changing_receipt_cannot_overwrite_evidence(
    journal, before, after, status
):
    store, case = journal
    key = "stable-effect"
    store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    store.effect_attempt(key, 3)
    store.record_effect(key, BEFORE, AFTER)
    immutable = store.effect(key)
    event_count = len(observed_events(store, case["id"]))

    with pytest.raises(DomainError) as failure:
        store.record_effect(key, before, after, status=status)
    assert failure.value.code == "EFFECT_EVIDENCE_CONFLICT"
    assert store.effect(key) == immutable
    assert len(observed_events(store, case["id"])) == event_count


@pytest.mark.parametrize("first_attempt", [False, True])
def test_valid_recovered_receipt_may_complete_prepared_or_unknown_effect(journal, first_attempt):
    store, case = journal
    key = "recovered-effect"
    store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    if first_attempt:
        store.effect_attempt(key, 3)
    store.record_effect(key, BEFORE, AFTER)
    assert store.effect(key)["status"] == "APPLIED"
    assert len(observed_events(store, case["id"])) == 1


def test_final_refusal_cannot_be_silently_converted_into_applied_receipt(journal):
    store, case = journal
    key = "refused-effect"
    store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    store.effect_attempt(key, 3)
    store.reject_effect(key, "PROVIDER_FORBIDDEN", expected_attempts=1)
    refused = store.effect(key)
    assert refused["status"] == "REJECTED"
    before_events = store.get_case(case["id"])["events"]

    with pytest.raises(DomainError) as failure:
        store.record_effect(key, BEFORE, AFTER)
    assert failure.value.code == "EFFECT_EVIDENCE_CONFLICT"
    assert store.effect(key) == refused
    assert store.get_case(case["id"])["events"] == before_events


def test_compensation_key_is_separate_and_its_receipt_is_also_immutable(journal):
    store, case = journal
    key = "stable-effect:compensate"
    store.prepare_effect(key, case["id"], "crm", "compensate_delivery_date", REQUEST)
    store.effect_attempt(key, 3)
    store.record_effect(key, AFTER, BEFORE, status="COMPENSATED")
    original = store.effect(key)
    store.record_effect(key, AFTER, BEFORE, status="COMPENSATED")
    assert store.effect(key) == original
    assert len(observed_events(store, case["id"])) == 1
    with pytest.raises(DomainError, match="immutable"):
        store.record_effect(key, AFTER, BEFORE, status="APPLIED")
    assert store.effect(key) == original


def test_unobserved_or_arbitrary_status_cannot_be_persisted_as_a_remote_receipt(journal):
    store, case = journal
    key = "stable-effect"
    original = store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    with pytest.raises(DomainError) as failure:
        store.record_effect(key, BEFORE, AFTER, status="UNKNOWN")
    assert failure.value.code == "INVALID_EFFECT_STATUS"
    assert store.effect(key) == original
    assert observed_events(store, case["id"]) == []


def test_separate_store_instance_cannot_rewrite_other_instance_observed_evidence(journal):
    store, case = journal
    key = "stable-effect"
    store.prepare_effect(key, case["id"], "crm", "change_delivery_date", REQUEST)
    other = Store(str(store.engine.url), initialize=False)
    try:
        store.record_effect(key, BEFORE, AFTER)
        original = store.effect(key)
        with pytest.raises(DomainError) as failure:
            other.record_effect(key, BEFORE, {"revision": 8})
        assert failure.value.code == "EFFECT_EVIDENCE_CONFLICT"
        assert store.effect(key) == original
    finally:
        other.close()
