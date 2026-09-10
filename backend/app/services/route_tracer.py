import datetime
import math
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from backend.app.config import HOP_GROUPING_WINDOW_SECONDS, IMPLAUSIBLE_SPEED_KMH
from backend.app.models import Detection, Camera, utc_iso
from backend.app.timewindow import TimeWindow, apply_window


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS points in kilometers."""
    R = 6371.0 # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 3)


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s"


def _window_payload(window: Optional[TimeWindow]) -> Dict[str, Any]:
    if window is None:
        return {"from": None, "to": None, "bounded": False}
    return {
        "from": utc_iso(window.start),
        "to": utc_iso(window.end),
        "bounded": window.is_bounded,
    }


def _empty_result(normalized_plate: str, window: Optional[TimeWindow] = None) -> Dict[str, Any]:
    """
    Same response shape as a successful trace. Callers should not have to branch
    on which keys exist just because a plate had no sightings.
    """
    # "Never seen" and "not seen in the window you asked about" are different
    # conclusions for an investigator, so the message says which one this is.
    if window is not None and window.is_bounded:
        message = (
            f"No CCTV detections for registration plate '{normalized_plate}' "
            f"within the requested window ({window.describe()}). The vehicle may "
            f"still have been recorded outside it."
        )
    else:
        message = f"No CCTV detections recorded for registration plate '{normalized_plate}'"

    return {
        "plate_number": normalized_plate,
        "total_hops": 0,
        "total_detections": 0,
        "total_distance_km": 0.0,
        "implausible_legs": 0,
        "first_observed": None,
        "last_observed": None,
        "window": _window_payload(window),
        "timeline": [],
        "geojson": {"type": "FeatureCollection", "features": []},
        "summary": {
            "status": "NOT_FOUND",
            "first_location": None,
            "last_location": None,
            "message": message,
        },
    }


def trace_vehicle_trajectory(
    db: Session,
    target_plate: str,
    window: Optional[TimeWindow] = None,
) -> Dict[str, Any]:
    """
    Core Evaluation Requirement:
    - Receive designated plate
    - Identify vehicle across multiple integrated departmental cameras
    - Calculate timestamped and location-wise movement history
    - Generate GIS route polyline with hop-by-hop analytics

    `window` scopes the reconstruction to an incident period. Hop grouping and
    transit maths then run over the filtered set, so a window that excludes the
    middle of a journey yields the legs that remain rather than a misleading
    straight line across the gap.
    """
    normalized_plate = "".join(c for c in target_plate.upper() if c.isalnum())

    query = db.query(Detection, Camera)\
        .join(Camera, Detection.camera_id == Camera.camera_id)\
        .filter(Detection.plate_number == normalized_plate)

    if window is not None:
        query = apply_window(query, Detection.capture_timestamp, window)

    records = query.order_by(Detection.capture_timestamp.asc()).all()

    if not records:
        return _empty_result(normalized_plate, window)

    # Group successive detections at the same camera into a single visit, but only
    # while they stay inside the grouping window. A vehicle that passes a junction
    # in the morning and again in the evening made two visits, not one nine-hour
    # dwell, and collapsing them would erase a leg of the journey.
    hops: List[Dict[str, Any]] = []
    current_hop: Optional[Dict[str, Any]] = None
    last_seen_dt: Optional[datetime.datetime] = None

    for det, cam in records:
        ts = det.capture_timestamp
        same_camera = current_hop is not None and current_hop["camera_id"] == cam.camera_id
        within_window = (
            last_seen_dt is not None
            and (ts - last_seen_dt).total_seconds() <= HOP_GROUPING_WINDOW_SECONDS
        )

        if same_camera and within_window:
            current_hop["last_seen"] = utc_iso(ts)
            current_hop["detection_count"] += 1
            current_hop["dwell_seconds"] = int((ts - current_hop["_first_dt"]).total_seconds())
            current_hop["confidence"] = max(current_hop["confidence"], det.confidence or 0.0)
            if det.snapshot_path and not current_hop["snapshot_path"]:
                current_hop["snapshot_path"] = det.snapshot_path
        else:
            if current_hop:
                hops.append(current_hop)
            current_hop = {
                "hop_index": len(hops) + 1,
                "camera_id": cam.camera_id,
                "camera_name": cam.name,
                "department": cam.department,
                "district": cam.district,
                "latitude": cam.latitude,
                "longitude": cam.longitude,
                "location_description": cam.location_description,
                "first_seen": utc_iso(ts),
                "last_seen": utc_iso(ts),
                "dwell_seconds": 0,
                "detection_count": 1,
                "snapshot_path": det.snapshot_path,
                "vehicle_type": det.vehicle_type,
                "confidence": det.confidence or 0.0,
                "pts_timestamp_ms": det.pts_timestamp_ms,
                "transit_time_seconds": None,
                "transit_time_formatted": None,
                "distance_from_prev_km": 0.0,
                "est_speed_kmh": 0.0,
                "speed_implausible": False,
                # Kept out of the response; used only for interval arithmetic.
                "_first_dt": ts,
                "_last_dt": ts,
            }

        current_hop["_last_dt"] = ts
        last_seen_dt = ts

    if current_hop:
        hops.append(current_hop)

    # Calculate inter-camera distance, transit duration and speed.
    total_distance_km = 0.0
    route_coordinates = []
    implausible_legs = 0

    for i, curr in enumerate(hops):
        route_coordinates.append([curr["longitude"], curr["latitude"]])
        if i == 0:
            continue

        prev = hops[i - 1]
        dist = haversine_distance_km(prev["latitude"], prev["longitude"], curr["latitude"], curr["longitude"])
        curr["distance_from_prev_km"] = dist
        total_distance_km += dist

        delta_sec = (curr["_first_dt"] - prev["_last_dt"]).total_seconds()
        curr["transit_time_seconds"] = int(delta_sec)
        curr["transit_time_formatted"] = _format_duration(delta_sec)

        if delta_sec > 0:
            speed_kmh = dist / (delta_sec / 3600.0)
            curr["est_speed_kmh"] = round(speed_kmh, 1)
            # Two distant cameras seeing the same plate seconds apart is the
            # signature of a cloned or misread plate. Surface it rather than
            # rendering 4,000 km/h as though it were an observation.
            curr["speed_implausible"] = speed_kmh > IMPLAUSIBLE_SPEED_KMH
        else:
            # Simultaneous sightings at two locations: physically impossible.
            curr["est_speed_kmh"] = None
            curr["speed_implausible"] = dist > 0.5

        if curr["speed_implausible"]:
            implausible_legs += 1

    for hop in hops:
        hop.pop("_first_dt", None)
        hop.pop("_last_dt", None)

    # GeoJSON FeatureCollection with points and route LineString
    geojson_features = []

    for hop in hops:
        geojson_features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [hop["longitude"], hop["latitude"]]
            },
            "properties": {
                "hop_index": hop["hop_index"],
                "camera_name": hop["camera_name"],
                "department": hop["department"],
                "first_seen": hop["first_seen"],
                "last_seen": hop["last_seen"],
                "transit_time": hop["transit_time_formatted"] or "Start Point",
                "speed_kmh": hop["est_speed_kmh"],
                "speed_implausible": hop["speed_implausible"],
                "snapshot_path": hop["snapshot_path"]
            }
        })

    if len(route_coordinates) >= 2:
        geojson_features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": route_coordinates
            },
            "properties": {
                "route_type": "VEHICLE_TRAJECTORY",
                "plate_number": normalized_plate,
                "total_distance_km": round(total_distance_km, 2)
            }
        })

    message = (
        f"Reconstructed cross-camera route across {len(hops)} departmental CCTV checkpoints."
    )
    if window is not None and window.is_bounded:
        message += f" Scoped to {window.describe()}."
    if implausible_legs:
        message += (
            f" {implausible_legs} leg(s) imply speeds above {IMPLAUSIBLE_SPEED_KMH:.0f} km/h "
            f"and need manual verification -- possible plate misread or cloned plate."
        )

    return {
        "plate_number": normalized_plate,
        "total_hops": len(hops),
        "total_detections": len(records),
        "total_distance_km": round(total_distance_km, 2),
        "implausible_legs": implausible_legs,
        "first_observed": hops[0]["first_seen"],
        "last_observed": hops[-1]["last_seen"],
        "window": _window_payload(window),
        "timeline": hops,
        "geojson": {
            "type": "FeatureCollection",
            "features": geojson_features
        },
        "summary": {
            "status": "TRACKED",
            "first_location": f"{hops[0]['camera_name']} ({hops[0]['department']})",
            "last_location": f"{hops[-1]['camera_name']} ({hops[-1]['department']})",
            "message": message
        }
    }
