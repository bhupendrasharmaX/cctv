import datetime

from backend.app.models import Detection
from backend.app.services.route_tracer import (
    haversine_distance_km,
    trace_vehicle_trajectory,
)

PLATE = "GJ01AB1234"


def _sighting(db, camera_id, when, plate=PLATE, confidence=0.92):
    det = Detection(
        camera_id=camera_id,
        plate_number=plate,
        plate_raw=plate,
        confidence=confidence,
        vehicle_type="CAR",
        pts_timestamp_ms=0,
        capture_timestamp=when,
    )
    db.add(det)
    db.commit()
    return det


def test_haversine_matches_known_distance():
    # Ahmedabad -> Gandhinagar, ~23 km apart.
    km = haversine_distance_km(23.0225, 72.5714, 23.2156, 72.6369)
    assert 20 < km < 26


def test_missing_plate_returns_the_same_shape_as_a_hit(db):
    result = trace_vehicle_trajectory(db, "GJ99ZZ0000")
    assert result["summary"]["status"] == "NOT_FOUND"
    # Callers should not have to branch on which keys exist.
    for key in ("timeline", "geojson", "total_hops", "total_distance_km", "first_observed"):
        assert key in result
    assert result["geojson"]["type"] == "FeatureCollection"


def test_consecutive_frames_at_one_camera_collapse_into_a_single_hop(db, cameras):
    base = datetime.datetime(2026, 9, 9, 6, 0, 0)
    for offset in (0, 2, 4, 6):
        _sighting(db, "CAM-TEST-A", base + datetime.timedelta(seconds=offset))

    result = trace_vehicle_trajectory(db, PLATE)

    assert result["total_detections"] == 4
    assert result["total_hops"] == 1
    assert result["timeline"][0]["detection_count"] == 4
    assert result["timeline"][0]["dwell_seconds"] == 6


def test_return_visit_to_the_same_camera_is_a_separate_hop(db, cameras):
    """
    The regression this guards: grouping used to key only on camera_id, so a
    morning and an evening pass through one junction merged into a single hop
    with a nine-hour dwell, erasing a leg of the journey.
    """
    morning = datetime.datetime(2026, 9, 9, 6, 0, 0)
    evening = morning + datetime.timedelta(hours=9)

    _sighting(db, "CAM-TEST-A", morning)
    _sighting(db, "CAM-TEST-A", evening)

    result = trace_vehicle_trajectory(db, PLATE)

    assert result["total_hops"] == 2
    assert result["timeline"][0]["dwell_seconds"] == 0
    assert result["timeline"][1]["transit_time_seconds"] == 9 * 3600


def test_two_camera_journey_reports_distance_and_speed(db, cameras):
    start = datetime.datetime(2026, 9, 9, 6, 0, 0)
    _sighting(db, "CAM-TEST-A", start)
    # ~4.6 km in 10 minutes -> a plausible ~28 km/h city speed.
    _sighting(db, "CAM-TEST-B", start + datetime.timedelta(minutes=10))

    result = trace_vehicle_trajectory(db, PLATE)
    second = result["timeline"][1]

    assert result["total_hops"] == 2
    assert 4.0 < result["total_distance_km"] < 5.5
    assert 20 < second["est_speed_kmh"] < 40
    assert second["speed_implausible"] is False
    assert second["transit_time_formatted"] == "10m 0s"


def test_impossible_speed_is_flagged_not_presented_as_fact(db, cameras):
    """A cloned or misread plate shows up as two distant sightings seconds apart."""
    start = datetime.datetime(2026, 9, 9, 6, 0, 0)
    _sighting(db, "CAM-TEST-A", start)
    _sighting(db, "CAM-TEST-B", start + datetime.timedelta(seconds=5))

    result = trace_vehicle_trajectory(db, PLATE)

    assert result["timeline"][1]["speed_implausible"] is True
    assert result["implausible_legs"] == 1
    assert "verification" in result["summary"]["message"].lower()


def test_timestamps_carry_an_explicit_utc_offset(db, cameras):
    """
    Without the offset a browser parses the string as local time and every
    timestamp in the evidence docket silently shifts by the local offset.
    """
    _sighting(db, "CAM-TEST-A", datetime.datetime(2026, 9, 9, 6, 0, 0))

    result = trace_vehicle_trajectory(db, PLATE)
    first_seen = result["timeline"][0]["first_seen"]

    assert first_seen.endswith("+00:00")
    parsed = datetime.datetime.fromisoformat(first_seen)
    assert parsed.utcoffset() == datetime.timedelta(0)


def test_internal_datetime_helpers_are_not_leaked_to_callers(db, cameras):
    _sighting(db, "CAM-TEST-A", datetime.datetime(2026, 9, 9, 6, 0, 0))
    hop = trace_vehicle_trajectory(db, PLATE)["timeline"][0]
    assert not [k for k in hop if k.startswith("_")]
