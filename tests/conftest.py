import os
import sys
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway database *before* any app module is imported,
# so tests never touch data/cctv.db.
_TMP_DB = Path(tempfile.mkdtemp(prefix="sentinel-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.database import Base, SessionLocal, engine  # noqa: E402
from backend.app.models import Camera, Watchlist  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def cameras(db):
    """Two Ahmedabad junctions roughly 4.6 km apart."""
    made = [
        Camera(
            camera_id="CAM-TEST-A",
            name="Pakwan Crossroad",
            department="Gujarat Police Traffic Branch",
            district="Ahmedabad",
            latitude=23.0489,
            longitude=72.5054,
            rtsp_url="rtsp://localhost:8554/stream/1",
        ),
        Camera(
            camera_id="CAM-TEST-B",
            name="Nehrunagar Circle",
            department="Gujarat Police Traffic Branch",
            district="Ahmedabad",
            latitude=23.0187,
            longitude=72.5443,
            rtsp_url="rtsp://localhost:8554/stream/2",
        ),
    ]
    db.add_all(made)
    db.commit()
    return made


@pytest.fixture()
def watchlist_entry(db):
    entry = Watchlist(
        plate_number="GJ01AB1234",
        vehicle_owner="Representative Record",
        vehicle_make_model="Maruti Swift",
        crime_category="Stolen",
        fir_number="FIR-TEST-001",
        police_station="Satellite PS",
        severity="CRITICAL",
        active=True,
    )
    db.add(entry)
    db.commit()
    return entry
