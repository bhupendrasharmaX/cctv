"""
End-to-end guard on the real-time alert path.

The regression this exists for: `check_and_generate_alert` only broadcast if it
could find a *running* event loop, but every producer of detections runs off the
loop -- the sync `POST /api/detections` handler (FastAPI runs sync endpoints in a
threadpool), the StreamWorker threads, and the simulation script. The resulting
RuntimeError was swallowed, so no alert ever reached a dashboard and the failure
was completely silent.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.models import Camera, Watchlist


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if not session.query(Camera).filter(Camera.camera_id == "CAM-WS-TEST").first():
            session.add(Camera(
                camera_id="CAM-WS-TEST",
                name="Websocket Test Junction",
                department="Gujarat Police Traffic Branch",
                district="Ahmedabad",
                latitude=23.0489,
                longitude=72.5054,
                rtsp_url="rtsp://localhost:8554/stream/99",
            ))
        if not session.query(Watchlist).filter(Watchlist.plate_number == "GJ01AB1234").first():
            session.add(Watchlist(
                plate_number="GJ01AB1234",
                crime_category="Stolen Vehicle / Grand Larceny",
                severity="CRITICAL",
                fir_number="FIR-WS-001",
                active=True,
            ))
        session.commit()
    finally:
        session.close()

    # `with` runs the lifespan, which is what registers the event loop.
    with TestClient(app) as c:
        yield c


def _post_detection(client, plate):
    return client.post("/api/detections", json={
        "camera_id": "CAM-WS-TEST",
        "plate_number": plate,
        "confidence": 0.95,
        "vehicle_type": "CAR",
    })


def test_watchlist_hit_reaches_a_connected_dashboard(client):
    with client.websocket_connect("/ws/alerts") as ws:
        response = _post_detection(client, "GJ01AB1234")
        assert response.status_code == 200

        messages = [ws.receive_json(), ws.receive_json()]
        by_type = {m["type"]: m["data"] for m in messages}

        # Every sighting feeds the live ticker...
        assert "LIVE_DETECTION" in by_type
        assert by_type["LIVE_DETECTION"]["plate_number"] == "GJ01AB1234"

        # ...and a watchlist hit additionally raises the alert.
        assert "WATCHLIST_ALERT" in by_type
        alert = by_type["WATCHLIST_ALERT"]
        assert alert["plate_number"] == "GJ01AB1234"
        assert alert["match_type"] == "EXACT"
        assert alert["is_confirmed"] is True
        assert alert["camera_name"] == "Websocket Test Junction"
        assert alert["timestamp"].endswith("+00:00")


def test_unlisted_plate_produces_a_sighting_but_no_alert(client):
    with client.websocket_connect("/ws/alerts") as ws:
        assert _post_detection(client, "GJ27XY7777").status_code == 200
        message = ws.receive_json()
        assert message["type"] == "LIVE_DETECTION"
        assert message["data"]["plate_number"] == "GJ27XY7777"


def test_detection_timestamps_are_utc_qualified_over_the_api(client):
    body = _post_detection(client, "GJ27XY8888").json()
    assert body["capture_timestamp"].endswith("+00:00")


def test_sync_catalogue_refuses_an_attacker_supplied_url(client):
    """
    `ingest_url` used to be caller-controlled, so this endpoint would fetch any
    address named and write the response into the camera registry.
    """
    response = client.post("/api/sync-catalogue", params={"host": "http://169.254.169.254/latest/meta-data"})
    assert response.status_code == 400
    assert "bare hostname" in response.json()["detail"]


def test_detection_limit_is_capped(client):
    assert client.get("/api/detections", params={"limit": 100000}).status_code == 422
