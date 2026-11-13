from __future__ import annotations

from dataclasses import dataclass

from crm_workflow.config import Settings
from crm_workflow.demo import DemoCRM, DemoERP
from crm_workflow.gateways import HTTPERP, MuleCRM
from crm_workflow.proposer import OllamaProposer, RulesProposer
from crm_workflow.service import CaseService
from crm_workflow.store import Store


@dataclass
class Runtime:
    settings: Settings
    store: Store
    service: CaseService

    async def close(self):
        for client in (self.service.crm, self.service.erp, self.service.proposer):
            close = getattr(client, "close", None)
            if close:
                await close()
        self.store.close()


def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or Settings.from_env()
    store = Store(settings.database_url, initialize=False)
    if not store.ping():
        raise RuntimeError("Schema missing: run python -m crm_workflow.cli migrate before starting services")
    crm = (
        DemoCRM(store)
        if settings.profile == "demo"
        else MuleCRM(
            settings.mule_url,
            settings.mule_token.get_secret_value(),
            settings.request_timeout_seconds,
            ca_file=settings.mule_ca_file or None,
        )
    )
    erp = (
        HTTPERP(settings.erp_url, settings.erp_token.get_secret_value(), settings.request_timeout_seconds)
        if settings.erp_url
        else DemoERP(store)
    )
    proposer = (
        RulesProposer()
        if settings.proposer == "rules"
        else OllamaProposer(settings.llm_url, settings.llm_model, settings.request_timeout_seconds)
    )
    return Runtime(settings, store, CaseService(store, crm, erp, proposer, settings))
