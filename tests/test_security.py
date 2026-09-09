"""
Shared-token access control.

The platform shipped with no access control at all: the camera registry
including RTSP URLs, the watchlist with owner names and FIR numbers, and AI
worker control were readable and writable by anyone who could reach the port.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import security
from backend.app.database import Base, engine
from backend.app.main import app

TOKEN = "test-platform-token-9f2a"


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def secured(monkeypatch):
    monkeypatch.setattr(security, "API_TOKEN", TOKEN)
    return TOKEN


# ---------------------------------------------------------------- disabled
def test_open_by_default_so_local_development_is_unchanged(client):
    assert security.API_TOKEN == ""
    assert client.get("/api/cameras").status_code == 200


# ---------------------------------------------------------------- enabled
def test_guarded_route_rejects_a_missing_token(client, secured):
    response = client.get("/api/cameras")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_guarded_route_rejects_a_wrong_token(client, secured):
    response = client.get("/api/cameras", headers={"Authorization": "Bearer not-the-token"})
    assert response.status_code == 401


def test_bearer_token_is_accepted(client, secured):
    response = client.get("/api/cameras", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


def test_x_api_token_header_is_accepted(client, secured):
    response = client.get("/api/cameras", headers={"X-API-Token": TOKEN})
    assert response.status_code == 200


def test_watchlist_writes_are_guarded(client, secured):
    """Adding a vehicle to a police watchlist must not be an anonymous action."""
    payload = {"plate_number": "GJ99ZZ0001", "crime_category": "Test"}
    assert client.post("/api/watchlist", json=payload).status_code == 401
    assert client.post(
        "/api/watchlist", json=payload, headers={"Authorization": f"Bearer {TOKEN}"}
    ).status_code == 200


def test_worker_control_is_guarded(client, secured):
    assert client.get("/api/stream-control/status").status_code == 401


def test_health_stays_open_for_load_balancers(client, secured):
    """It must not leak registry or watchlist detail either."""
    response = client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["auth_required"] is True
    assert set(body) == {"status", "auth_required", "dashboard_clients", "ai_workers"}


# ---------------------------------------------------------------- websocket
def test_alert_stream_rejects_an_unauthenticated_client(client, secured):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/alerts") as ws:
            ws.receive_json()


def test_alert_stream_accepts_the_token_as_a_query_parameter(client, secured):
    # A WebSocket handshake carries no custom headers, so this is the only
    # channel available to a browser.
    with client.websocket_connect(f"/ws/alerts?token={TOKEN}") as ws:
        assert ws is not None


# ---------------------------------------------------------------- comparison
def test_token_comparison_is_constant_time(secured):
    """
    A plain `==` leaks the token prefix through response timing, which is
    enough to recover it byte by byte.
    """
    import inspect
    source = inspect.getsource(security._token_matches)
    assert "compare_digest" in source

    assert security._token_matches(TOKEN) is True
    assert security._token_matches(TOKEN[:-1]) is False
    assert security._token_matches("") is False
    assert security._token_matches(None) is False
