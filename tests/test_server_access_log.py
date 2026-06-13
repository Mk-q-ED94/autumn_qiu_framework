"""Tests for GET /memory/audit/access_log endpoint."""
import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402
from autumn.core.memory.backends import DictBackend  # noqa: E402
from autumn.core.memory.base import MemoryArea  # noqa: E402
from autumn.core.workspace.wp4 import WP4Mem  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_autumn():
    """Minimal Autumn-shaped object with a real WP4 audit log (DictBackend)."""
    wp4_mem = MemoryArea("wp4", DictBackend())

    class _Autumn:
        def __init__(self):
            self.wp4 = WP4Mem(None, wp4_mem, zones={})
        async def close(self): pass

    return _Autumn()


def _add(autumn, action, requester="mom2", query="test query", reason="test reason",
         decision_reason="ok", redact=False, entries=None, mediated_by="a4"):
    asyncio.run(
        autumn.wp4.memory.append_history(
            {
                "ts": time.time(),
                "action": action,
                "requester": requester,
                "query": query,
                "reason": reason,
                "decision_reason": decision_reason,
                "redact": redact,
                "entries": entries or ["e1"],
                "mediated_by": mediated_by,
            },
            tags=["access", action],
        )
    )


@pytest.fixture
def client_with_autumn():
    app = create_app()
    autumn = _make_autumn()
    with TestClient(app) as client:
        app.state.autumn = autumn
        yield client, autumn


# ── empty log ─────────────────────────────────────────────────────────────────


def test_access_log_empty(client_with_autumn):
    client, _ = client_with_autumn
    r = client.get("/memory/audit/access_log")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == []
    assert body["total"] == 0


# ── entries returned ──────────────────────────────────────────────────────────


def test_access_log_returns_entries(client_with_autumn):
    client, autumn = client_with_autumn
    _add(autumn, "mom1_access_granted", query="db host", reason="need db")
    _add(autumn, "mom1_access_denied", requester="mom3", query="secrets", reason="curiosity",
         decision_reason="not need-to-know")

    r = client.get("/memory/audit/access_log")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["entries"]) == 2

    # newest first
    first = body["entries"][0]
    assert first["action"] == "mom1_access_denied"
    assert first["requester"] == "mom3"
    assert first["query"] == "secrets"
    assert first["decision_reason"] == "not need-to-know"

    second = body["entries"][1]
    assert second["action"] == "mom1_access_granted"
    assert second["requester"] == "mom2"
    assert second["query"] == "db host"
    assert second["mediated_by"] == "a4"


def test_access_log_entry_has_required_fields(client_with_autumn):
    client, autumn = client_with_autumn
    _add(autumn, "mom1_access_granted", entries=["id1", "id2"], mediated_by="a4")

    body = client.get("/memory/audit/access_log").json()
    entry = body["entries"][0]
    assert "id" in entry
    assert "timestamp" in entry
    assert isinstance(entry["timestamp"], float)
    assert entry["entry_ids"] == ["id1", "id2"]
    assert entry["redact"] is False
    assert entry["mediated_by"] == "a4"


# ── verdict filter ────────────────────────────────────────────────────────────


def test_access_log_filter_granted(client_with_autumn):
    client, autumn = client_with_autumn
    _add(autumn, "mom1_access_granted")
    _add(autumn, "mom1_access_denied")
    _add(autumn, "mom1_access_granted")

    r = client.get("/memory/audit/access_log?verdict=granted")
    body = r.json()
    assert body["total"] == 2
    assert all(e["action"] == "mom1_access_granted" for e in body["entries"])


def test_access_log_filter_denied(client_with_autumn):
    client, autumn = client_with_autumn
    _add(autumn, "mom1_access_granted")
    _add(autumn, "mom1_access_denied", requester="mom3")
    _add(autumn, "mom1_access_denied", requester="mom2")

    r = client.get("/memory/audit/access_log?verdict=denied")
    body = r.json()
    assert body["total"] == 2
    assert all(e["action"] == "mom1_access_denied" for e in body["entries"])


def test_access_log_filter_unknown_verdict_returns_all(client_with_autumn):
    client, autumn = client_with_autumn
    _add(autumn, "mom1_access_granted")
    _add(autumn, "mom1_access_denied")

    r = client.get("/memory/audit/access_log?verdict=unknown_value")
    body = r.json()
    assert body["total"] == 2


# ── pagination ────────────────────────────────────────────────────────────────


def test_access_log_pagination(client_with_autumn):
    client, autumn = client_with_autumn
    for i in range(5):
        _add(autumn, "mom1_access_granted", query=f"query {i}")

    r = client.get("/memory/audit/access_log?limit=2&offset=0")
    body = r.json()
    assert body["total"] == 5
    assert len(body["entries"]) == 2

    r2 = client.get("/memory/audit/access_log?limit=2&offset=2")
    assert len(r2.json()["entries"]) == 2

    r3 = client.get("/memory/audit/access_log?limit=2&offset=4")
    assert len(r3.json()["entries"]) == 1


# ── 503 when no autumn ────────────────────────────────────────────────────────


def test_access_log_unconfigured_returns_503():
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/memory/audit/access_log")
    assert r.status_code == 503
