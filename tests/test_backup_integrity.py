"""Isolated SQLite backup safety and provenance regressions; no provider database is used."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
import stat
from contextlib import closing

import pytest

from crm_workflow import cli


def simple_database(tmp_path):
    path = tmp_path / "source.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE fixture (value INTEGER NOT NULL)")
        db.execute("INSERT INTO fixture VALUES (1)")
        db.commit()
    return path


def test_backup_file_is_private_before_sqlite_opens_it(tmp_path, monkeypatch):
    source = simple_database(tmp_path)
    destination = tmp_path / "backup.db"
    real_connect = sqlite3.connect
    inspected = []

    def inspect_connect(path, *args, **kwargs):
        if str(path) == str(destination):
            assert destination.exists()
            inspected.append(stat.S_IMODE(destination.stat().st_mode))
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(cli.sqlite3, "connect", inspect_connect)
    cli.backup(str(source), str(destination))
    assert inspected == [0o600]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    with closing(real_connect(destination)) as db:
        assert db.execute("SELECT value FROM fixture").fetchone()[0] == 1


def test_backup_rejects_existing_file_and_dangling_symlink(tmp_path):
    source = simple_database(tmp_path)
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"keep-existing-backup")
    with pytest.raises(SystemExit, match="already exists"):
        cli.backup(str(source), str(existing))
    assert existing.read_bytes() == b"keep-existing-backup"

    missing = tmp_path / "outside.db"
    link = tmp_path / "dangling.db"
    link.symlink_to(missing)
    with pytest.raises(SystemExit, match="already exists"):
        cli.backup(str(source), str(link))
    assert link.is_symlink()
    assert not missing.exists()


def test_backup_failure_removes_only_new_incomplete_destination(tmp_path, monkeypatch):
    source = simple_database(tmp_path)
    destination = tmp_path / "failed-backup.db"
    real_connect = sqlite3.connect

    def inject_failure(path, *args, **kwargs):
        if str(path) == str(destination):
            assert stat.S_IMODE(destination.stat().st_mode) == 0o600
            raise RuntimeError("injected SQLite destination failure")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(cli.sqlite3, "connect", inject_failure)
    with pytest.raises(RuntimeError, match="injected SQLite destination failure"):
        cli.backup(str(source), str(destination))
    assert not destination.exists()
    assert source.exists()


def test_restore_check_hashes_the_restored_wal_snapshot_not_only_main_file(tmp_path, monkeypatch):
    source = tmp_path / "wal-source.db"
    output = tmp_path / "restore-evidence.json"
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.executescript(
            "CREATE TABLE cases(id TEXT PRIMARY KEY);"
            "CREATE TABLE effects(case_id TEXT NOT NULL);"
            "CREATE TABLE case_events(id TEXT);"
            "CREATE TABLE outbox(id TEXT);"
            "INSERT INTO cases(id) VALUES ('synthetic-case');"
            "INSERT INTO effects(case_id) VALUES ('synthetic-case');"
        )
        writer.commit()
        assert (tmp_path / "wal-source.db-wal").stat().st_size > 0

        original_backup = cli.backup
        captured_snapshots = []

        def capture_snapshot(src, dst):
            original_backup(src, dst)
            captured_snapshots.append(hashlib.sha256(Path(dst).read_bytes()).hexdigest())

        monkeypatch.setattr(cli, "backup", capture_snapshot)
        cli.restore_check(str(source), str(output))
        report = json.loads(output.read_text())
        assert report["integrity"] == "ok"
        assert report["orphan_effects"] == 0
        assert report["restored_counts"]["cases"] == 1
        assert report["restored_counts"]["effects"] == 1
        assert report["restored_snapshot_sha256"] == captured_snapshots[0]
        assert report["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert report["source_sha256"] != report["restored_snapshot_sha256"]
        assert "WAL" in report["source_sha256_scope"]
    finally:
        writer.close()
