from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, SecretStr, model_validator

from crm_workflow.models import StrictModel


class Settings(StrictModel):
    profile: Literal["demo", "salesforce"] = "demo"
    database_url: str = "sqlite:///.local/workflow.db"
    auth_file: str = ".local/principals.json"
    webhook_secret: SecretStr = SecretStr("")
    webhook_tenant_id: str = "demo-industrial"
    webhook_actor_id: str = "n8n-trigger"
    max_request_bytes: int = Field(default=16384, ge=1024, le=1048576)
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "p06-order-exceptions-v1"
    worker_concurrency: int = Field(default=8, ge=1, le=64)
    temporal_activity_rate_limit: float = Field(default=20, gt=0, le=100)
    approval_ttl_seconds: int = Field(default=900, ge=5, le=86400)
    activity_timeout_seconds: int = Field(default=40, ge=5, le=300)
    activity_total_timeout_seconds: int = Field(default=180, ge=20, le=3600)
    retry_max_attempts: int = Field(default=4, ge=1, le=8)
    request_timeout_seconds: float = Field(default=5, gt=0, le=30)
    max_case_api_calls: int = Field(default=80, ge=10, le=200)
    crm_concurrency: int = Field(default=4, ge=1, le=20)
    erp_concurrency: int = Field(default=4, ge=1, le=20)
    circuit_failures: int = Field(default=3, ge=1, le=20)
    circuit_reset_seconds: int = Field(default=15, ge=1, le=300)
    mule_url: str = ""
    mule_ca_file: str = ""
    mule_token: SecretStr = SecretStr("")
    erp_url: str = ""
    erp_token: SecretStr = SecretStr("")
    proposer: Literal["rules", "ollama"] = "rules"
    llm_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:4b"
    allow_external_llm: bool = False
    max_delivery_shift_days: int = Field(default=90, ge=1, le=365)

    @model_validator(mode="after")
    def validate_deployment(self):
        if self.profile == "salesforce":
            if not self.mule_url.startswith("https://") or not self.mule_token.get_secret_value():
                raise ValueError("salesforce profile requires an HTTPS MuleSoft endpoint and external token")
            if not self.erp_url or not self.erp_token.get_secret_value():
                raise ValueError("salesforce profile requires an explicit ERP endpoint and token")
        from urllib.parse import urlparse

        if self.proposer == "ollama" and not self.allow_external_llm:
            if urlparse(self.llm_url).hostname not in {"localhost", "127.0.0.1", "::1", "ollama"}:
                raise ValueError("External LLM transmission requires explicit allow_external_llm")
        if self.activity_timeout_seconds <= self.request_timeout_seconds * 4:
            raise ValueError("activity timeout must allow the bounded precondition and readback calls")
        return self

    @classmethod
    def from_env(cls) -> Settings:
        config_path = Path(os.getenv("P06_CONFIG", "config/demo.yaml"))
        data = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        data = data or {}
        for key in cls.model_fields:
            value = os.getenv(f"P06_{key.upper()}")
            if value is not None:
                data[key] = value
        return cls.model_validate(data)
