import asyncio
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from crm_workflow.errors import DomainError, TransientError, UnknownOutcome
from crm_workflow.gateways import HTTPSystem, MuleCRM, retry_after_seconds


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


@pytest.mark.parametrize("method,error_type", [("GET", TransientError), ("POST", UnknownOutcome)])
async def test_slow_http_stream_obeys_one_total_request_budget(method, error_type):
    # Use a real loopback transport: every chunk arrives before HTTPX's per-read
    # timeout, but their combined duration exceeds the total request budget.
    attempts = []
    finished = asyncio.Event()

    async def upstream(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            content_length = next(
                (
                    int(line.partition(b":")[2].strip())
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                ),
                0,
            )
            body = await reader.readexactly(content_length)
            attempts.append((headers.split(b"\r\n", 1)[0], body))
            parts = [b'{"ok":', b" ", b" ", b" ", b" ", b"true}"]
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(sum(map(len, parts))).encode()
                + b"\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
            for part in parts:
                await asyncio.sleep(0.05)
                writer.write(part)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass  # The bounded client closes this unfinished response.
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            finished.set()

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = HTTPSystem(f"http://127.0.0.1:{port}", "synthetic", timeout=0.2)
    payload = {"effect_key": "slow-response-immutable-key"}
    try:
        async with asyncio.timeout(2):
            with pytest.raises(error_type):
                await client.request(method, "/slow", **({"json": payload} if method == "POST" else {}))
            await finished.wait()
        assert len(attempts) == 1
        assert attempts[0][0] == f"{method} /slow HTTP/1.1".encode()
        if method == "POST":
            assert json.loads(attempts[0][1]) == payload
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


async def test_external_cancellation_propagates_and_closes_response_without_retry():
    started = asyncio.Event()
    closed = asyncio.Event()
    attempts = []
    peer_reads = []

    async def upstream(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            content_length = next(
                int(line.partition(b":")[2].strip())
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            attempts.append(await reader.readexactly(content_length))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n")
            await writer.drain()
            started.set()
            # Keep the response incomplete. Cancellation must close this real
            # connection, not turn an external worker stop into a transient error.
            peer_reads.append(await reader.read())
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = HTTPSystem(f"http://127.0.0.1:{port}", "synthetic")
    payload = {"effect_key": "cancelled-write"}
    task = asyncio.create_task(client.request("POST", "/effects", json=payload))
    try:
        async with asyncio.timeout(2):
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await closed.wait()
        assert len(attempts) == 1
        assert json.loads(attempts[0]) == payload
        assert peer_reads == [b""]
    finally:
        if not task.done():
            task.cancel()
        await client.close()
        server.close()
        await server.wait_closed()
