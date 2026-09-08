import datetime

from backend.app.models import Alert, Detection, Watchlist, utcnow
from backend.app.services.alert_engine import (
    check_and_generate_alert,
    levenshtein_distance,
)


def _detect(db, camera_id, plate, when=None):
    det = Detection(
        camera_id=camera_id,
        plate_number=plate,
        plate_raw=plate,
        confidence=0.94,
        vehicle_type="CAR",
        pts_timestamp_ms=0,
        capture_timestamp=when or utcnow(),
    )
    db.add(det)
    db.commit()
    db.refresh(det)
    return det


def test_levenshtein_basics():
    assert levenshtein_distance("GJ01AB1234", "GJ01AB1234") == 0
    assert levenshtein_distance("GJ01AB1234", "GJ01AB1284") == 1
    assert levenshtein_distance("GJ01AB1234", "MH12CD9999") > 1


def test_exact_match_raises_a_confirmed_alert(db, cameras, watchlist_entry):
    det = _detect(db, "CAM-TEST-A", "GJ01AB1234")
    alert = check_and_generate_alert(db, det, cameras[0])

    assert alert is not None
    assert alert.match_type == "EXACT"
    assert alert.severity == "CRITICAL"
    assert alert.plate_number == "GJ01AB1234"
    assert alert.matched_plate == "GJ01AB1234"
    assert "CONFIRMED MATCH" in alert.alert_message


def test_unlisted_plate_raises_nothing(db, cameras, watchlist_entry):
    det = _detect(db, "CAM-TEST-A", "GJ27XY5555")
    assert check_and_generate_alert(db, det, cameras[0]) is None
    assert db.query(Alert).count() == 0


def test_fuzzy_match_reports_what_the_camera_actually_read(db, cameras, watchlist_entry):
    """
    The bug this guards: a one-character-off read used to produce the message
    "Suspect vehicle GJ01AB1234 detected", quoting the watchlist plate as if it
    were the observation. An officer must see the plate that was actually read.
    """
    det = _detect(db, "CAM-TEST-A", "GJ01AB1284")
    alert = check_and_generate_alert(db, det, cameras[0])

    assert alert is not None
    assert alert.match_type == "FUZZY_UNCONFIRMED"
    assert alert.plate_number == "GJ01AB1284"     # what the camera saw
    assert alert.matched_plate == "GJ01AB1234"    # what it resembles
    assert "GJ01AB1284" in alert.alert_message
    assert "UNCONFIRMED" in alert.alert_message
    # A near-miss is a lead to verify, not a confirmed CRITICAL sighting.
    assert alert.severity == "REVIEW"


def test_exact_match_wins_over_an_earlier_fuzzy_candidate(db, cameras, watchlist_entry):
    """Both plates are on the list; the exact one must be the one that matches."""
    db.add(Watchlist(
        plate_number="GJ01AB1284",
        crime_category="Wanted",
        severity="HIGH",
        active=True,
    ))
    db.commit()

    det = _detect(db, "CAM-TEST-A", "GJ01AB1284")
    alert = check_and_generate_alert(db, det, cameras[0])

    assert alert.match_type == "EXACT"
    assert alert.matched_plate == "GJ01AB1284"


def test_dwell_frames_produce_one_alert_not_a_burst(db, cameras, watchlist_entry):
    """
    A vehicle sits in frame for several sampled frames. Each becomes its own
    detection, but the operator should get one alert, with a sighting count.
    """
    base = utcnow()
    alerts = [
        check_and_generate_alert(
            db, _detect(db, "CAM-TEST-A", "GJ01AB1234", base + datetime.timedelta(seconds=i * 2)), cameras[0]
        )
        for i in range(5)
    ]

    assert sum(a is not None for a in alerts) == 1
    assert db.query(Alert).count() == 1
    assert db.query(Alert).one().sighting_count == 5


def test_cooldown_is_scoped_per_camera(db, cameras, watchlist_entry):
    """The same vehicle at the *next* junction is new information."""
    check_and_generate_alert(db, _detect(db, "CAM-TEST-A", "GJ01AB1234"), cameras[0])
    second = check_and_generate_alert(db, _detect(db, "CAM-TEST-B", "GJ01AB1234"), cameras[1])

    assert second is not None
    assert db.query(Alert).count() == 2


def test_inactive_watchlist_entries_are_ignored(db, cameras, watchlist_entry):
    watchlist_entry.active = False
    db.commit()

    det = _detect(db, "CAM-TEST-A", "GJ01AB1234")
    assert check_and_generate_alert(db, det, cameras[0]) is None
