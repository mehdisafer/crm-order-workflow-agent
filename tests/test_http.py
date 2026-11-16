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


@pytest.mark.parametrize("header", ["NaN", "Infinity", "-Infinity", "1e309"])
def test_nonfinite_upstream_retry_hints_are_ignored(header):
    assert retry_after_seconds(header) is None


def test_excessive_retry_hints_are_bounded_without_truncating_one_day():
    future = format_datetime(datetime.now(UTC) + timedelta(days=5), usegmt=True)
    assert retry_after_seconds("1000000000000") == 86400
    assert retry_after_seconds(future) == 86400
    assert retry_after_seconds("-17") == 0


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("1000000000000", 86400),
        ("Infinity", None),
    ],
)
async def test_mocked_provider_429_never_returns_an_unbounded_retry_delay(header, expected):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header})

    client = MuleCRM("https://example.invalid", "synthetic", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(TransientError) as raised:
            await client.order("demo-industrial", "synthetic-order")
        assert len(calls) == 1
        assert raised.value.retry_after == expected
        assert header not in str(raised.value)
    finally:
        await client.close()
