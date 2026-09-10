from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from backend.app.config import MAX_PAGE_SIZE
from backend.app.database import get_db
from backend.app.models import Detection, DetectionSchema, DetectionCreate, Camera, utc_iso, utcnow
from backend.app.timewindow import TimeWindow, apply_window, resolve_window
from backend.app.services.route_tracer import trace_vehicle_trajectory
from backend.app.services.alert_engine import check_and_generate_alert, push_detection

router = APIRouter(prefix="/api", tags=["Vehicle Tracking & Detections"])


def _detection_query(db, plate, camera_id, vehicle_type, min_confidence, window: TimeWindow):
    query = db.query(Detection)
    if plate:
        clean_plate = "".join(c for c in plate.upper() if c.isalnum())
        if clean_plate:
            # Partial match: an operator who only caught part of a registration
            # can still work with what they have.
            query = query.filter(Detection.plate_number.ilike(f"%{clean_plate}%"))
    if camera_id:
        query = query.filter(Detection.camera_id == camera_id)
    if vehicle_type:
        query = query.filter(Detection.vehicle_type == vehicle_type.upper())
    if min_confidence is not None:
        query = query.filter(Detection.confidence >= min_confidence)
    return apply_window(query, Detection.capture_timestamp, window)


@router.get("/track-vehicle/{plate_number}")
def track_vehicle(
    plate_number: str,
    window: TimeWindow = Depends(resolve_window),
    db: Session = Depends(get_db),
):
    """
    Primary Evaluation Endpoint:
    Receive designated vehicle registration number from the evaluation jury.
    Returns:
    - Cross-camera identity verification
    - Timestamped & location-wise movement history
    - Hop-by-hop transit duration and estimated speed
    - GeoJSON route vector ready for instant GIS mapping

    Optional `from`/`to` scope the trace to an incident window. Without them the
    vehicle's entire recorded history is reconstructed, which is rarely what an
    investigation actually wants.
    """
    if not plate_number or len(plate_number.strip()) < 3:
        raise HTTPException(status_code=400, detail="Please provide a valid vehicle registration number")

    return trace_vehicle_trajectory(db, plate_number, window=window)


@router.get("/detections", response_model=List[DetectionSchema])
def list_detections(
    plate: Optional[str] = None,
    camera_id: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    window: TimeWindow = Depends(resolve_window),
    db: Session = Depends(get_db)
):
    """Search and filter CCTV vehicle detections."""
    query = _detection_query(db, plate, camera_id, vehicle_type, min_confidence, window)
    return query.order_by(Detection.capture_timestamp.desc()).offset(offset).limit(limit).all()


@router.get("/detections/search")
def search_detections(
    plate: Optional[str] = None,
    camera_id: Optional[str] = None,
    vehicle_type: Optional[str] = None,
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    window: TimeWindow = Depends(resolve_window),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Same filters as `/detections`, but joined to the camera and returned with a
    total count and the resolved window.

    The plain list endpoint cannot back a results table: it returns camera IDs
    with no names, and no total, so the UI can neither label a row nor tell an
    operator how many matches were left off the end.
    """
    base = _detection_query(db, plate, camera_id, vehicle_type, min_confidence, window)
    total = base.count()

    rows = (
        base.join(Camera, Detection.camera_id == Camera.camera_id)
        .with_entities(Detection, Camera)
        .order_by(Detection.capture_timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "returned": len(rows),
        "offset": offset,
        "limit": limit,
        "truncated": total > offset + len(rows),
        "window": {"from": utc_iso(window.start), "to": utc_iso(window.end)},
        "results": [
            {
                "detection_id": det.detection_id,
                "plate_number": det.plate_number,
                "plate_raw": det.plate_raw,
                "confidence": det.confidence,
                "vehicle_type": det.vehicle_type,
                "capture_timestamp": utc_iso(det.capture_timestamp),
                "snapshot_path": det.snapshot_path,
                "camera_id": cam.camera_id,
                "camera_name": cam.name,
                "department": cam.department,
                "district": cam.district,
                "latitude": cam.latitude,
                "longitude": cam.longitude,
            }
            for det, cam in rows
        ],
    }


@router.post("/detections", response_model=DetectionSchema)
def ingest_detection(data: DetectionCreate, db: Session = Depends(get_db)):
    """
    Ingest a new vehicle detection event from an AI stream worker.
    Automatically checks against the police watchlist and triggers instant alerts.
    """
    camera = db.query(Camera).filter(Camera.camera_id == data.camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {data.camera_id} not registered")

    clean_plate = "".join(c for c in data.plate_number.upper() if c.isalnum())
    if not clean_plate:
        raise HTTPException(status_code=400, detail="plate_number contains no alphanumeric characters")

    detection = Detection(
        camera_id=data.camera_id,
        plate_number=clean_plate,
        plate_raw=data.plate_raw or data.plate_number,
        confidence=data.confidence,
        vehicle_type=data.vehicle_type,
        pts_timestamp_ms=data.pts_timestamp_ms,
        capture_timestamp=utcnow(),
        snapshot_path=data.snapshot_path
    )
    db.add(detection)
    db.commit()
    db.refresh(detection)

    # Push every sighting to the live dashboard ticker, then cross-reference
    # against the watchlist (which raises its own, louder alert on a match).
    push_detection(detection, camera)
    check_and_generate_alert(db, detection, camera)

    return detection
