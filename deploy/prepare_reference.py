"""Generate local-only Compose secrets after init-demo; never overwrite credentials."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path


def write_new(path: Path, value: str, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(value)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    local = root / ".local"
    if not all((local / name).is_file() for name in ("demo.env", "principals.json", "tokens.json")):
        raise SystemExit("Run uv run python -m crm_workflow.cli init-demo first")
    target = root / "deploy" / "secrets"
    target.mkdir(mode=0o700, exist_ok=True)
    names = ["postgres-owner-password", "postgres-app-password", "prometheus-token"]
    if (local / "compose.env").exists() or any((target / name).exists() for name in names):
        raise SystemExit("Reference credentials already exist; nothing was overwritten")
    values = dict(line.split("=", 1) for line in (local / "demo.env").read_text().splitlines() if "=" in line)
    owner_password = values["P06_POSTGRES_PASSWORD"]
    app_password = secrets.token_hex(32)
    # Files readable in their narrowly mounted containers; parent directory is private.
    write_new(target / names[0], owner_password + "\n", 0o644)
    write_new(target / names[1], app_password + "\n", 0o644)
    operator_token = json.loads((local / "tokens.json").read_text())["operator"]
    write_new(target / names[2], operator_token + "\n")
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    content = (
        f"P06_DATABASE_URL=postgresql+psycopg://p06_app:{app_password}@postgres:5432/p06\n"
        f"P06_MIGRATION_DATABASE_URL=postgresql+psycopg://p06_owner:{owner_password}@postgres:5432/p06\n"
        f"P06_UID={uid}\nP06_GID={gid}\n"
        f"N8N_ENCRYPTION_KEY={secrets.token_hex(32)}\n"
    )
    write_new(local / "compose.env", content)
    print("Reference credentials prepared. Start Compose with --env-file .local/compose.env.")


if __name__ == "__main__":
    main()
