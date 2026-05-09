"""Lightweight async client for the broker REST API used by the watcher.

The watcher only needs two endpoints (§17): inbox polling and identity
verification. Everything else (send/reply/forward/read) is invoked by the
spawned Claude subprocess.

Errors classify into Permanent (4xx that won't fix on retry) and Transient
(5xx, network, JSON). Callers decide whether to bail or back off.
"""
from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Optional

import httpx


class PermanentBrokerError(Exception):
    """4xx response from broker — caller should exit instead of retrying."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class TransientBrokerError(Exception):
    """5xx, timeout, or connection error — caller should back off and retry."""


@dataclass
class InboxMessage:
    id: str
    thread_id: str
    from_agent: str
    to_agent: str
    subject: str
    is_read: bool
    created_at: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InboxMessage":
        return cls(
            id=data["id"],
            thread_id=data.get("thread_id", ""),
            from_agent=data.get("from_agent", ""),
            to_agent=data.get("to_agent", ""),
            subject=data.get("subject", ""),
            is_read=bool(data.get("is_read", False)),
            created_at=data.get("created_at", ""),
            raw=data,
        )


class BrokerClient:
    def __init__(self, broker_url: str, api_key: str, *, timeout: float = 30.0):
        self.broker_url = broker_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.broker_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    async def __aenter__(self) -> "BrokerClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_inbox(self, address: str, agent_id: str) -> list[InboxMessage]:
        """GET /messages/inbox/{address}?agent_id=..."""
        try:
            r = await self._client.get(
                f"/messages/inbox/{address}",
                params={"agent_id": agent_id},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientBrokerError(f"network error: {exc}") from exc

        _raise_for_status(r)
        try:
            data = r.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise TransientBrokerError(f"malformed JSON from broker: {exc}") from exc
        if not isinstance(data, list):
            raise TransientBrokerError(f"expected list, got {type(data).__name__}")
        return [InboxMessage.from_dict(item) for item in data]

    async def verify_agent(self, agent_id: str) -> dict[str, Any]:
        """GET /agents/{agent_id} — used at startup to verify api_key + agent_id."""
        try:
            r = await self._client.get(f"/agents/{agent_id}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientBrokerError(f"network error: {exc}") from exc
        _raise_for_status(r)
        try:
            return r.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise TransientBrokerError(f"malformed JSON from broker: {exc}") from exc

    async def fetch_message(self, msg_id: str) -> dict[str, Any]:
        try:
            r = await self._client.get(f"/messages/{msg_id}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientBrokerError(f"network error: {exc}") from exc
        _raise_for_status(r)
        return r.json()


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    if 400 <= response.status_code < 500:
        raise PermanentBrokerError(
            response.status_code,
            f"broker {response.request.method} {response.request.url} -> {response.status_code}: "
            f"{_truncate(response.text, 400)}",
        )
    raise TransientBrokerError(
        f"broker {response.request.method} {response.request.url} -> {response.status_code}: "
        f"{_truncate(response.text, 200)}"
    )


def _truncate(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1] + "…"


async def sleep_with_jitter(seconds: float, jitter_frac: float = 0.1) -> None:
    """Sleep with up to ±10% jitter to avoid thundering-herd polling."""
    if seconds <= 0:
        return
    jitter = seconds * jitter_frac
    delay = max(0.1, seconds + random.uniform(-jitter, jitter))
    await asyncio.sleep(delay)


def backoff_delay(attempt: int, base: float = 30.0, cap: float = 600.0) -> float:
    """Exponential backoff with cap. attempt is 1-indexed."""
    return min(cap, base * (2 ** (attempt - 1)))
