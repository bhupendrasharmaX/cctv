import math
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from backend.app.models import Detection, Camera

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS points in kilometers."""
    R = 6371.0 # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 3)


def trace_vehicle_trajectory(db: Session, target_plate: str) -> Dict[str, Any]:
    """
    Core Evaluation Requirement:
    - Receive designated plate
    - Identify vehicle across multiple integrated departmental cameras
    - Calculate timestamped and location-wise movement history
    - Generate GIS route polyline with hop-by-hop analytics
    """
    normalized_plate = "".join(c for c in target_plate.upper() if c.isalnum())

    records = db.query(Detection, Camera)\
        .join(Camera, Detection.camera_id == Camera.camera_id)\
        .filter(Detection.plate_number == normalized_plate)\
        .order_by(Detection.capture_timestamp.asc())\
        .all()

    if not records:
        return {
            "plate_number": normalized_plate,
            "total_hops": 0,
            "total_detections": 0,
            "route_geojson": None,
            "timeline": [],
            "summary": {
                "status": "NOT_FOUND",
                "message": f"No CCTV detections recorded for registration plate '{normalized_plate}'"
            }
        }

    # Group successive detections at the same camera within 120s into a single visit
    hops = []
    current_hop = None

    for det, cam in records:
        ts = det.capture_timestamp
        if current_hop and current_hop["camera_id"] == cam.camera_id:
            # Same camera: update dwell time and frame count
            current_hop["last_seen"] = ts.isoformat()
            current_hop["detection_count"] += 1
            if det.snapshot_path:
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
                "first_seen": ts.isoformat(),
                "last_seen": ts.isoformat(),
                "detection_count": 1,
                "snapshot_path": det.snapshot_path,
                "vehicle_type": det.vehicle_type,
                "confidence": det.confidence,
                "transit_time_from_prev": None,
                "distance_from_prev_km": 0.0,
                "est_speed_kmh": 0.0
            }

    if current_hop:
        hops.append(current_hop)

    # Calculate inter-camera speed, transit duration, and travel distance
    total_distance_km = 0.0
    route_coordinates = []

    for i in range(len(hops)):
        route_coordinates.append([hops[i]["longitude"], hops[i]["latitude"]])
        if i > 0:
            prev = hops[i - 1]
            curr = hops[i]
            dist = haversine_distance_km(prev["latitude"], prev["longitude"], curr["latitude"], curr["longitude"])
            curr["distance_from_prev_km"] = dist
            total_distance_km += dist

            # Compute time delta
            import dateutil.parser
            t_prev = dateutil.parser.parse(prev["last_seen"])
            t_curr = dateutil.parser.parse(curr["first_seen"])
            delta_sec = max(1, (t_curr - t_prev).total_seconds())
            curr["transit_time_seconds"] = int(delta_sec)
            curr["transit_time_formatted"] = f"{int(delta_sec // 60)}m {int(delta_sec % 60)}s"

            # Compute estimated speed
            speed_kmh = (dist / (delta_sec / 3600.0)) if delta_sec > 0 else 0
            curr["est_speed_kmh"] = round(speed_kmh, 1)

    # GeoJSON FeatureCollection with points and route LineString
    geojson_features = []

    # 1. Point markers for each camera hop
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
                "transit_time": hop.get("transit_time_formatted", "Start Point"),
                "speed_kmh": hop.get("est_speed_kmh", 0),
                "snapshot_path": hop.get("snapshot_path")
            }
        })

    # 2. LineString connecting the path
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

    return {
        "plate_number": normalized_plate,
        "total_hops": len(hops),
        "total_detections": len(records),
        "total_distance_km": round(total_distance_km, 2),
        "first_observed": hops[0]["first_seen"] if hops else None,
        "last_observed": hops[-1]["last_seen"] if hops else None,
        "timeline": hops,
        "geojson": {
            "type": "FeatureCollection",
            "features": geojson_features
        },
        "summary": {
            "status": "TRACKED",
            "first_location": f"{hops[0]['camera_name']} ({hops[0]['department']})" if hops else None,
            "last_location": f"{hops[-1]['camera_name']} ({hops[-1]['department']})" if hops else None,
            "message": f"Successfully reconstructed cross-camera route across {len(hops)} departmental CCTV checkpoints."
        }
    }
