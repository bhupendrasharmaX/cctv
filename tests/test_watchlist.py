"""
Watchlist lifecycle.

The deactivate endpoint existed from the start but nothing in the UI called it,
so a vehicle could be put under surveillance and never taken off. A recovered
car left on the list keeps raising CRITICAL alerts at every junction it passes.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.database import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.models import Alert, Camera, Detection, Watchlist, utcnow
from backend.app.services.alert_engine import check_and_generate_alert

PLATE = "GJ44TEST0001"


@pytest.fixture()
def client():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        session.query(Watchlist).filter(Watchlist.plate_number == PLATE).delete()
        session.commit()
    finally:
        session.close()

    with TestClient(app) as c:
        yield c


def _add(client, plate=PLATE):
    response = client.post("/api/watchlist", json={
        "plate_number": plate,
        "crime_category": "Stolen Vehicle",
        "fir_number": "FIR-WL-001",
        "severity": "CRITICAL",
    })
    assert response.status_code == 200
    return response.json()


def _plates(client, active_only=True):
    response = client.get("/api/watchlist", params={"active_only": active_only})
    assert response.status_code == 200
    return {row["plate_number"]: row for row in response.json()}


def test_deactivate_removes_the_entry_from_the_active_list(client):
    entry = _add(client)
    assert PLATE in _plates(client)

    response = client.delete(f"/api/watchlist/{entry['watchlist_id']}")
    assert response.status_code == 200
    assert response.json()["active"] is False

    assert PLATE not in _plates(client)


def test_deactivate_keeps_the_record(client):
    """
    A soft deactivate, not a delete: existing alerts reference this row for
    their FIR and crime category, and an alert already acted on has to stay
    explicable afterwards.
    """
    entry = _add(client)
    client.delete(f"/api/watchlist/{entry['watchlist_id']}")

    inactive = _plates(client, active_only=False)
    assert PLATE in inactive
    assert inactive[PLATE]["active"] is False
    assert inactive[PLATE]["crime_category"] == "Stolen Vehicle"
    assert inactive[PLATE]["fir_number"] == "FIR-WL-001"


def test_reactivate_restores_the_entry_as_it_stands(client):
    entry = _add(client)
    client.delete(f"/api/watchlist/{entry['watchlist_id']}")

    response = client.post(f"/api/watchlist/{entry['watchlist_id']}/reactivate")
    assert response.status_code == 200

    body = response.json()
    assert body["active"] is True
    # Restoring must not quietly reset the case details the way a re-POST does.
    assert body["crime_category"] == "Stolen Vehicle"
    assert body["fir_number"] == "FIR-WL-001"
    assert PLATE in _plates(client)


def test_unknown_ids_are_rejected(client):
    assert client.delete("/api/watchlist/999999").status_code == 404
    assert client.post("/api/watchlist/999999/reactivate").status_code == 404


def test_a_deactivated_vehicle_stops_raising_alerts(db, cameras):
    """The behaviour the whole feature exists for."""
    entry = Watchlist(
        plate_number=PLATE,
        crime_category="Stolen Vehicle",
        severity="CRITICAL",
        active=True,
    )
    db.add(entry)
    db.commit()

    def sight():
        det = Detection(
            camera_id="CAM-TEST-A",
            plate_number=PLATE,
            plate_raw=PLATE,
            confidence=0.95,
            vehicle_type="CAR",
            pts_timestamp_ms=0,
            capture_timestamp=utcnow(),
        )
        db.add(det)
        db.commit()
        db.refresh(det)
        return det

    assert check_and_generate_alert(db, sight(), cameras[0]) is not None

    entry.active = False
    db.commit()

    # A different camera, so the cooldown cannot be what suppresses this.
    assert check_and_generate_alert(db, sight(), cameras[1]) is None
