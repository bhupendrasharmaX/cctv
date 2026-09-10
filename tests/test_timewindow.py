"""
Time-window scoping for investigative search.

Before this, no endpoint took a time range: tracing a plate returned its entire
recorded history with no way to scope to an incident window.
"""

import datetime

import pytest
from fastapi import HTTPException

from backend.app.models import Detection, to_naive_utc
from backend.app.services.route_tracer import trace_vehicle_trajectory
from backend.app.timewindow import TimeWindow, resolve_window

PLATE = "GJ01AB1234"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def _sighting(db, camera_id, when, plate=PLATE):
    det = Detection(
        camera_id=camera_id,
        plate_number=plate,
        plate_raw=plate,
        confidence=0.93,
        vehicle_type="CAR",
        pts_timestamp_ms=0,
        capture_timestamp=when,
    )
    db.add(det)
    db.commit()
    return det


# ------------------------------------------------------------------ normalize
def test_offset_aware_input_is_converted_to_utc():
    """
    The dashboard sends Asia/Kolkata wall-clock with an offset. Treating those
    digits as UTC would shift every search window by 5h30m.
    """
    ist_noon = datetime.datetime(2026, 9, 11, 12, 0, 0, tzinfo=IST)
    assert to_naive_utc(ist_noon) == datetime.datetime(2026, 9, 11, 6, 30, 0)


def test_naive_input_is_taken_as_utc_unchanged():
    naive = datetime.datetime(2026, 9, 11, 6, 30, 0)
    assert to_naive_utc(naive) == naive


def test_none_passes_through():
    assert to_naive_utc(None) is None


# ------------------------------------------------------------------ validation
def test_inverted_window_is_rejected():
    """
    An inverted range must not quietly return nothing -- an empty result reads
    as "this vehicle was never seen", the opposite conclusion.
    """
    with pytest.raises(HTTPException) as exc:
        resolve_window(
            datetime.datetime(2026, 9, 11, 18, 0),
            datetime.datetime(2026, 9, 11, 9, 0),
        )
    assert exc.value.status_code == 400
    assert "inverted" in exc.value.detail.lower()


def test_open_ended_and_absent_windows_are_allowed():
    assert resolve_window(None, None) == TimeWindow(None, None)
    only_start = resolve_window(datetime.datetime(2026, 9, 11, 9, 0), None)
    assert only_start.start is not None and only_start.end is None
    assert only_start.is_bounded is True
    assert TimeWindow(None, None).is_bounded is False


def test_equal_bounds_are_accepted():
    moment = datetime.datetime(2026, 9, 11, 9, 0)
    assert resolve_window(moment, moment).start == moment


# ------------------------------------------------------------------ tracing
def test_trace_without_a_window_returns_the_whole_history(db, cameras):
    _sighting(db, "CAM-TEST-A", datetime.datetime(2026, 9, 11, 6, 0))
    _sighting(db, "CAM-TEST-B", datetime.datetime(2026, 9, 11, 18, 0))

    result = trace_vehicle_trajectory(db, PLATE)
    assert result["total_detections"] == 2
    assert result["window"]["bounded"] is False


def test_window_excludes_sightings_outside_the_incident_period(db, cameras):
    _sighting(db, "CAM-TEST-A", datetime.datetime(2026, 9, 11, 6, 0))   # before
    _sighting(db, "CAM-TEST-A", datetime.datetime(2026, 9, 11, 10, 0))  # inside
    _sighting(db, "CAM-TEST-B", datetime.datetime(2026, 9, 11, 18, 0))  # after

    window = TimeWindow(
        start=datetime.datetime(2026, 9, 11, 9, 0),
        end=datetime.datetime(2026, 9, 11, 12, 0),
    )
    result = trace_vehicle_trajectory(db, PLATE, window=window)

    assert result["total_detections"] == 1
    assert result["total_hops"] == 1
    assert result["timeline"][0]["camera_id"] == "CAM-TEST-A"
    assert result["window"]["bounded"] is True
    assert "Scoped to" in result["summary"]["message"]


def test_window_bounds_are_inclusive(db, cameras):
    edge = datetime.datetime(2026, 9, 11, 9, 0)
    _sighting(db, "CAM-TEST-A", edge)

    result = trace_vehicle_trajectory(db, PLATE, window=TimeWindow(start=edge, end=edge))
    assert result["total_detections"] == 1


def test_empty_window_result_says_it_was_scoped(db, cameras):
    """
    "Never seen" and "not seen in the window you asked about" are different
    findings, and the message has to distinguish them.
    """
    _sighting(db, "CAM-TEST-A", datetime.datetime(2026, 9, 11, 6, 0))

    window = TimeWindow(
        start=datetime.datetime(2026, 9, 11, 20, 0),
        end=datetime.datetime(2026, 9, 11, 22, 0),
    )
    result = trace_vehicle_trajectory(db, PLATE, window=window)

    assert result["total_hops"] == 0
    message = result["summary"]["message"]
    assert "within the requested window" in message
    assert "outside it" in message
    # The unscoped wording must not be reused here.
    assert result["window"]["bounded"] is True


def test_empty_result_keeps_the_full_response_shape(db, cameras):
    result = trace_vehicle_trajectory(db, "GJ99ZZ0000", window=TimeWindow(None, None))
    for key in ("timeline", "geojson", "window", "total_hops", "implausible_legs"):
        assert key in result
