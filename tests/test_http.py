import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from crm_workflow.errors import DomainError, TransientError, UnknownOutcome
from crm_workflow.gateways import MuleCRM, retry_after_seconds


@pytest.mark.parametrize(
    "code,error",
    [
        (401, DomainError),
        (403, DomainError),
        (409, DomainError),
        (429, TransientError),
        (500, TransientError),
        (503, TransientError),
    ],
)
async def test_http_classification_has_no_hidden_retry(code, error):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            code, json={"private": "never forward this body"}, headers={"Retry-After": "17"}
        )

    client = MuleCRM("https://example.invalid", "synthetic", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(error) as exc:
            await client.order("demo-industrial", "123")
        assert len(calls) == 1
        assert "private" not in str(exc.value)
        if code == 429:
            assert exc.value.retry_after == 17
    finally:
        await client.close()


async def test_http_write_timeout_is_unknown_and_never_repeated_in_client():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("injected response loss")

    client = MuleCRM("https://example.invalid", "synthetic", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(UnknownOutcome):
            await client.apply("123", {"effect_key": "known-key"}, "corr-123")
        assert len(calls) == 1
        assert calls[0].headers["X-Correlation-ID"] == "corr-123"
        assert json.loads(calls[0].content)["effect_key"] == "known-key"
    finally:
        await client.close()


def test_retry_after_accepts_date_and_delta_without_shortening_budget():
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    assert 118 <= retry_after_seconds(future) <= 120
    assert retry_after_seconds("86400") == 86400
    assert retry_after_seconds("invalid") is None
