"""Regression gates for deployment privilege separation and bootstrap readiness."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from crm_workflow.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_reference_credentials_are_explicitly_scoped_and_not_overwritten(tmp_path):
    local = tmp_path / ".local"
    local.mkdir()
    values = {
        key: secrets.token_urlsafe(24)
        for key in ("P06_WEBHOOK_SECRET", "P06_ERP_TOKEN", "P06_POSTGRES_PASSWORD", "P06_LLM_TOKEN")
    }
    (local / "demo.env").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    (local / "principals.json").write_text('{"principals": []}')
    (local / "tokens.json").write_text(json.dumps({"operator": "synthetic-operator-fixture"}))
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    script = deploy / "prepare_reference.py"
    shutil.copyfile(ROOT / "deploy/prepare_reference.py", script)
    prepared = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    assert all(value not in prepared.stdout + prepared.stderr for value in values.values())
    interpolation = dict(line.split("=", 1) for line in (local / "compose.env").read_text().splitlines())
    config = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text())
    for name in ("api", "worker", "erp"):
        service = config["services"][name]
        assert "env_file" not in service
        environment = {
            key: re.sub(r"\$\{([A-Z0-9_]+)(?::[^}]*)?\}", lambda m: interpolation[m[1]], value)
            for key, value in service["environment"].items()
        }
        assert "p06_app:" in environment["P06_DATABASE_URL"]
        assert environment["P06_ERP_TOKEN"] == values["P06_ERP_TOKEN"]
        assert values["P06_POSTGRES_PASSWORD"] not in json.dumps(environment)
        assert interpolation["N8N_ENCRYPTION_KEY"] not in json.dumps(environment)
        assert values["P06_LLM_TOKEN"] not in json.dumps(environment)
        assert ("P06_WEBHOOK_SECRET" in environment) is (name == "api")
    assert config["services"]["migrate"]["environment"]["P06_DATABASE_URL"].startswith(
        "${P06_MIGRATION_DATABASE_URL:"
    )
    preserved = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    repeated = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert repeated.returncode != 0
    assert all(path.read_bytes() == content for path, content in preserved.items())


def test_postgres_health_waits_for_tcp_after_bootstrap():
    config = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text())
    health = config["services"]["postgres"]["healthcheck"]["test"]
    assert "-h 127.0.0.1" in " ".join(health)
    assert config["services"]["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"

@pytest.mark.parametrize(
    "endpoint",
    [
        "http://erp:8001",
        "http://public-erp.invalid",
        "ftp://erp.invalid",
        "https://",
        "https://user:password@erp.invalid",
        "https://erp.invalid?apikey=must-not-be-in-url",
    ],
)
def test_real_provider_requires_valid_tls_erp_endpoint(endpoint):
    with pytest.raises(ValueError, match="HTTPS ERP"):
        Settings(
            profile="salesforce",
            mule_url="https://mule.example.invalid",
            mule_token="synthetic-mule-credential",
            erp_url=endpoint,
            erp_token="synthetic-erp-credential",
        )


@pytest.mark.parametrize(
    "endpoint",
    ["http://public-erp.invalid", "http://127.0.0.1:8001", "http://erp:8001/"],
)
def test_insecure_synthetic_override_does_not_allow_other_http_endpoints(endpoint):
    with pytest.raises(ValueError, match="HTTPS ERP"):
        Settings(
            profile="salesforce",
            mule_url="https://mule.example.invalid",
            mule_token="synthetic-mule-credential",
            erp_url=endpoint,
            erp_token="synthetic-erp-credential",
            allow_insecure_synthetic_erp_http=True,
        )


def test_real_provider_allows_verified_tls_and_explicit_synthetic_reference():
    base = {
        "profile": "salesforce",
        "mule_url": "https://mule.example.invalid",
        "mule_token": "synthetic-mule-credential",
        "erp_token": "synthetic-erp-credential",
    }
    secure = Settings(**base, erp_url="https://erp.example.invalid", erp_ca_file="/run/secrets/erp-ca.pem")
    assert secure.erp_ca_file == "/run/secrets/erp-ca.pem"
    assert secure.allow_insecure_synthetic_erp_http is False
    synthetic = Settings(
        **base, erp_url="http://erp:8001", allow_insecure_synthetic_erp_http=True
    )
    assert synthetic.erp_url == "http://erp:8001"
    overlay = yaml.safe_load((ROOT / "deploy/compose.salesforce.yaml").read_text())
    for service in ("api", "worker"):
        assert overlay["services"][service]["environment"]["P06_ERP_URL"] == "http://erp:8001"
        assert (
            overlay["services"][service]["environment"]["P06_ALLOW_INSECURE_SYNTHETIC_ERP_HTTP"]
            == "true"
        )
