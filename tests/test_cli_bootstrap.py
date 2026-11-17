"""Fail-closed CLI fixture bootstrap tests. All writable paths are isolated pytest directories."""

from __future__ import annotations

import json
import sqlite3
import stat

import pytest

from crm_workflow import cli
from crm_workflow.config import Settings


def configured(monkeypatch, settings):
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))


@pytest.mark.parametrize(
    ("profile", "database_url"),
    [
        ("demo", "postgresql+psycopg://example:unused@invalid.example/demo"),
        ("salesforce", "sqlite:///.local/workflow.db"),
        ("demo", "sqlite:///:memory:"),
    ],
)
def test_init_demo_rejects_unsafe_targets_before_creating_anything(
    tmp_path, monkeypatch, profile, database_url
):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        profile=profile,
        database_url=database_url,
        mule_url="https://mule.example.invalid",
        mule_token="synthetic-mule-token",
        erp_url="https://erp.example.invalid",
        erp_token="synthetic-erp-token",
    )
    configured(monkeypatch, settings)

    def unexpected_store(*args, **kwargs):
        pytest.fail("Unsafe init-demo must never open a database")

    monkeypatch.setattr(cli, "Store", unexpected_store)
    with pytest.raises(SystemExit, match="requires profile=demo"):
        cli.init_demo()
    assert not (tmp_path / ".local").exists()


def test_init_demo_seeds_sqlite_and_exclusively_creates_private_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    configured(monkeypatch, Settings(database_url="sqlite:///.local/workflow.db"))
    cli.init_demo()

    local = tmp_path / ".local"
    credentials = [local / name for name in ("principals.json", "tokens.json", "demo.env")]
    for path in credentials:
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    tokens = json.loads((local / "tokens.json").read_text())
    assert set(tokens) == {"requester", "approver", "operator"}
    output = capsys.readouterr().out
    assert all(token not in output for token in tokens.values())
    with sqlite3.connect(local / "workflow.db") as database:
        assert database.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0] == 6

    before = {path.name: path.read_bytes() for path in credentials}
    with pytest.raises(SystemExit, match="already exist"):
        cli.init_demo()
    assert all(path.read_bytes() == before[path.name] for path in credentials)


def test_init_demo_rejects_dangling_credential_symlink(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configured(monkeypatch, Settings(database_url="sqlite:///.local/workflow.db"))
    local = tmp_path / ".local"
    local.mkdir()
    outside = tmp_path / "outside-secret.json"
    (local / "tokens.json").symlink_to(outside)
    with pytest.raises(SystemExit, match="already exist"):
        cli.init_demo()
    assert not outside.exists()
    assert not (local / "principals.json").exists()
    assert not (local / "workflow.db").exists()


def test_init_demo_closes_store_on_seed_failure_without_creating_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configured(monkeypatch, Settings(database_url="sqlite:///.local/workflow.db"))

    class FailingStore:
        closed = False

        def __init__(self, url):
            assert url == "sqlite:///.local/workflow.db"

        def close(self):
            self.closed = True

    store = FailingStore("sqlite:///.local/workflow.db")
    monkeypatch.setattr(cli, "Store", lambda url: store)

    def fail_seed(_store):
        raise RuntimeError("injected local database failure")

    monkeypatch.setattr(cli, "seed_demo", fail_seed)
    with pytest.raises(RuntimeError, match="injected local database failure"):
        cli.init_demo()

    assert store.closed is True
    assert not any(
        (tmp_path / ".local" / name).exists() for name in ("principals.json", "tokens.json", "demo.env")
    )
