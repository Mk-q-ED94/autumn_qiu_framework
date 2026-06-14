"""Tests for the optional API-key gate on the HTTP bridge.

When ``AUTUMN_API_KEY`` is unset (the default for local single-user runs) the
server is wide open, exactly as before. When it is set, every endpoint except
``/health`` (and CORS preflight) requires the shared secret — this is what makes
the server safe to bind beyond localhost.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402


@pytest.fixture
def app_client():
    with TestClient(create_app()) as c:
        yield c


def test_no_key_configured_is_open(app_client, monkeypatch):
    # Backward-compatible default: no AUTUMN_API_KEY → no auth.
    monkeypatch.delenv("AUTUMN_API_KEY", raising=False)
    assert app_client.get("/integrations/catalog").status_code == 200


def test_health_stays_open_even_with_key(app_client, monkeypatch):
    # A container/uptime probe must never have to carry the secret.
    monkeypatch.setenv("AUTUMN_API_KEY", "s3cret")
    assert app_client.get("/health").status_code == 200


def test_protected_endpoint_401_without_key(app_client, monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "s3cret")
    r = app_client.get("/integrations/catalog")
    assert r.status_code == 401
    assert "API key" in r.json()["detail"]


def test_bearer_header_accepted(app_client, monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "s3cret")
    r = app_client.get(
        "/integrations/catalog", headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200


def test_x_api_key_header_accepted(app_client, monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "s3cret")
    r = app_client.get("/integrations/catalog", headers={"X-API-Key": "s3cret"})
    assert r.status_code == 200


def test_wrong_key_rejected(app_client, monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "s3cret")
    r = app_client.get("/integrations/catalog", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_key_can_rotate_without_restart(app_client, monkeypatch):
    # The env is read per-request, so a rotated secret takes effect immediately.
    monkeypatch.setenv("AUTUMN_API_KEY", "first")
    assert app_client.get(
        "/integrations/catalog", headers={"X-API-Key": "first"},
    ).status_code == 200
    monkeypatch.setenv("AUTUMN_API_KEY", "second")
    assert app_client.get(
        "/integrations/catalog", headers={"X-API-Key": "first"},
    ).status_code == 401
    assert app_client.get(
        "/integrations/catalog", headers={"X-API-Key": "second"},
    ).status_code == 200


def test_post_endpoints_also_gated(app_client, monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "s3cret")
    r = app_client.post("/integrations/connect", json={"id": "github", "args": {}})
    assert r.status_code == 401
