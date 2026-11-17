"""Guard CLI storage side-effect order with isolated synthetic databases."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError

from crm_workflow import cli
from crm_workflow.config import Settings
from crm_workflow.models import Actor, OrderRequest
from crm_workflow.store import Store


def configure(monkeypatch, settings: Settings):
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))


def command(monkeypatch, *arguments: str):
    monkeypatch.setattr(sys, "argv", ["crm-workflow", *arguments])
    cli.main()


@pytest.mark.parametrize(
    ("profile", "count"),
    [
        ("demo", "0"),
        ("demo", "1001"),
        ("salesforce", "3"),
    ],
)
def test_forbidden_seed_never_constructs_store(tmp_path, monkeypatch, profile, count):
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "must-not-be-created.db"
    configure(
        monkeypatch,
        Settings(
            profile=profile,
            database_url=f"sqlite:///{database}",
            mule_url="https://mule.invalid",
            mule_token="synthetic-mule-token",
            erp_url="https://erp.invalid",
            erp_token="synthetic-erp-token",
        ),
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Rejected seed command must not instantiate Store or seed any data")

    monkeypatch.setattr(cli, "Store", unexpected)
    monkeypatch.setattr(cli, "seed_demo", unexpected)
    with pytest.raises(SystemExit, match="Seeding requires demo profile"):
        command(monkeypatch, "seed-demo", "--count", count)
    assert not database.exists()


def test_valid_demo_seed_retains_initialisation_and_selected_fixture_count(tmp_path, monkeypatch):
    database = tmp_path / "fixtures.db"
    configure(monkeypatch, Settings(database_url=f"sqlite:///{database}"))
    command(monkeypatch, "seed-demo", "--count", "2")
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0] == 4
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 1
    # Repeated seeding does not overwrite existing synthetic orders.
    command(monkeypatch, "seed-demo", "--count", "2")
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0] == 4


def test_explicit_migrate_still_initializes_empty_store(tmp_path, monkeypatch):
    database = tmp_path / "migration.db"
    configure(monkeypatch, Settings(database_url=f"sqlite:///{database}"))
    command(monkeypatch, "migrate")
    with closing(sqlite3.connect(database)) as db:
        names = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_version", "cases", "effects", "outbox"}.issubset(names)
    assert "demo_orders" not in names


def test_replay_does_not_create_schema_in_an_existing_unmigrated_db(tmp_path, monkeypatch):
    database = tmp_path / "unmigrated.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE sentinel (value INTEGER NOT NULL)")
        db.execute("INSERT INTO sentinel VALUES (7)")
        db.commit()

    configure(monkeypatch, Settings(database_url=f"sqlite:///{database}"))
    with pytest.raises(SQLAlchemyError):
        command(monkeypatch, "replay-outbox", "no-such-event")

    with closing(sqlite3.connect(database)) as db:
        names = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert db.execute("SELECT value FROM sentinel").fetchone()[0] == 7
    assert names == {"sentinel"}


def test_replay_retains_original_event_identity_and_payload(tmp_path, monkeypatch):
    database = tmp_path / "replay.db"
    url = f"sqlite:///{database}"
    actor = Actor(actor_id="requester", tenant_id="demo-industrial", roles=["requester"])
    request = OrderRequest(
        message_id="synthetic-replay",
        customer_reference="CUST-001",
        order_reference="ORD-1001",
        requested_date=date.today() + timedelta(days=10),
    )

    original_store = Store(url)
    try:
        case = original_store.create_case(request.model_dump(mode="json"), actor.model_dump())
        pending = original_store.pending_outbox()
        assert len(pending) == 1
        event = pending[0]
        original_store.fail_outbox(event["id"], "injected error", max_attempts=1)
        assert original_store.outbox_stats()["dead"] == 1
    finally:
        original_store.close()

    configure(monkeypatch, Settings(database_url=url))
    command(monkeypatch, "replay-outbox", event["id"])

    checked = Store(url, initialize=False)
    try:
        pending = checked.pending_outbox()
        assert len(pending) == 1
        assert pending[0]["id"] == event["id"]
        assert pending[0]["case_id"] == case["id"]
        assert pending[0]["payload"] == event["payload"]
        assert pending[0]["attempts"] == 0
        assert checked.outbox_stats()["dead"] == 0
        events = checked.get_case(case["id"])["events"]
        assert len([row for row in events if row["event_type"] == "outbox.replay_requested"]) == 1
    finally:
        checked.close()
