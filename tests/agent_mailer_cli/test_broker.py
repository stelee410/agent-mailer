"""Tests for agent_mailer_cli.broker error classification + backoff helpers.

Covers:
  • 4xx → PermanentBrokerError (caller exits)
  • 5xx → TransientBrokerError (caller backs off)
  • backoff_delay base=60 (SPEC §9.2) + cap=600
  • sleep_with_jitter stays within ±10%
  • inbox parsing returns InboxMessage objects
  • verify_agent surfaces JSON
"""
from __future__ import annotations

import asyncio
import statistics

import httpx
import pytest

from agent_mailer_cli.broker import (
    BrokerClient,
    PermanentBrokerError,
    TransientBrokerError,
    backoff_delay,
    sleep_with_jitter,
)


def _client_with_handler(handler) -> BrokerClient:
    """Build a BrokerClient whose underlying httpx uses MockTransport."""
    client = BrokerClient("https://broker.test", "key-XYZ")
    transport = httpx.MockTransport(handler)
    # Replace the internal client so requests are intercepted.
    client._client = httpx.AsyncClient(  # noqa: SLF001 — test-only override
        base_url=client.broker_url,
        headers={"X-API-Key": client.api_key},
        transport=transport,
    )
    return client


# -------- backoff helpers --------


def test_backoff_delay_base_60_aligns_with_spec() -> None:
    """SPEC §9.2: 60s ~ 600s exponential backoff."""
    assert backoff_delay(1) == 60.0
    assert backoff_delay(2) == 120.0
    assert backoff_delay(3) == 240.0
    assert backoff_delay(4) == 480.0


def test_backoff_delay_caps_at_600() -> None:
    assert backoff_delay(10) == 600.0
    assert backoff_delay(100) == 600.0


def test_backoff_delay_explicit_base_still_works() -> None:
    assert backoff_delay(1, base=10.0, cap=600.0) == 10.0


def test_sleep_with_jitter_stays_within_band() -> None:
    """sleep_with_jitter should hit the requested duration ±10% (modulo timing
    noise on a busy machine, which we account for)."""
    delays: list[float] = []

    async def measure_one() -> float:
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        await sleep_with_jitter(0.2, jitter_frac=0.1)
        return loop.time() - t0

    async def gather():
        for _ in range(5):
            delays.append(await measure_one())

    asyncio.run(gather())

    # Each sample within 0.18..0.22 plus generous machine slack.
    for d in delays:
        assert 0.15 <= d <= 0.30, f"sleep_with_jitter out of band: {d}"
    # Average should sit close to the target.
    assert 0.17 <= statistics.mean(delays) <= 0.25


def test_sleep_with_jitter_zero_returns_immediately() -> None:
    async def go():
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        await sleep_with_jitter(0)
        return loop.time() - t0

    elapsed = asyncio.run(go())
    assert elapsed < 0.05


# -------- BrokerClient classification --------


def test_4xx_raises_permanent() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid api_key"})

    async def go():
        async with _client_with_handler(handler) as client:
            await client.fetch_inbox("agent@x", "id-1")

    with pytest.raises(PermanentBrokerError) as exc:
        asyncio.run(go())
    assert exc.value.status_code == 401


def test_404_raises_permanent() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "agent not found"})

    async def go():
        async with _client_with_handler(handler) as client:
            await client.verify_agent("missing-id")

    with pytest.raises(PermanentBrokerError) as exc:
        asyncio.run(go())
    assert exc.value.status_code == 404


def test_5xx_raises_transient() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream busy")

    async def go():
        async with _client_with_handler(handler) as client:
            await client.fetch_inbox("agent@x", "id-1")

    with pytest.raises(TransientBrokerError):
        asyncio.run(go())


def test_500_raises_transient() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def go():
        async with _client_with_handler(handler) as client:
            await client.verify_agent("id-1")

    with pytest.raises(TransientBrokerError):
        asyncio.run(go())


def test_network_error_raises_transient() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async def go():
        async with _client_with_handler(handler) as client:
            await client.fetch_inbox("agent@x", "id-1")

    with pytest.raises(TransientBrokerError):
        asyncio.run(go())


def test_inbox_returns_parsed_messages() -> None:
    payload = [
        {"id": "m-1", "thread_id": "t-1", "from_agent": "x@y", "to_agent": "me@y",
         "subject": "hi", "is_read": False, "created_at": "2026-05-09T05:00:00Z"},
        {"id": "m-2", "thread_id": "t-2", "from_agent": "x@y", "to_agent": "me@y",
         "subject": "again", "is_read": True, "created_at": "2026-05-09T05:01:00Z"},
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/messages/inbox/me@y"
        assert req.url.params.get("agent_id") == "id-1"
        assert req.headers["x-api-key"] == "key-XYZ"
        return httpx.Response(200, json=payload)

    async def go():
        async with _client_with_handler(handler) as client:
            return await client.fetch_inbox("me@y", "id-1")

    msgs = asyncio.run(go())
    assert [m.id for m in msgs] == ["m-1", "m-2"]
    assert msgs[0].is_read is False and msgs[1].is_read is True
    assert msgs[0].subject == "hi"


def test_inbox_rejects_non_list_response() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": []})  # broker contract violation

    async def go():
        async with _client_with_handler(handler) as client:
            await client.fetch_inbox("me@y", "id-1")

    with pytest.raises(TransientBrokerError):
        asyncio.run(go())


def test_verify_agent_returns_dict() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/agents/id-1"
        return httpx.Response(200, json={"id": "id-1", "name": "tester", "address": "t@x"})

    async def go():
        async with _client_with_handler(handler) as client:
            return await client.verify_agent("id-1")

    data = asyncio.run(go())
    assert data["name"] == "tester"
