from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import datetime
from backend.app.database import get_db
from backend.app.models import Detection, DetectionSchema, DetectionCreate, Camera
from backend.app.services.route_tracer import trace_vehicle_trajectory
from backend.app.services.alert_engine import check_and_generate_alert

router = APIRouter(prefix="/api", tags=["Vehicle Tracking & Detections"])

@router.get("/track-vehicle/{plate_number}")
def track_vehicle(plate_number: str, db: Session = Depends(get_db)):
    """
    Primary Evaluation Endpoint:
    Receive designated vehicle registration number from the evaluation jury.
    Returns:
    - Cross-camera identity verification
    - Timestamped & location-wise movement history
    - Hop-by-hop transit duration and estimated speed
    - GeoJSON route vector ready for instant GIS mapping
    """
    if not plate_number or len(plate_number.strip()) < 3:
        raise HTTPException(status_code=400, detail="Please provide a valid vehicle registration number")

    result = trace_vehicle_trajectory(db, plate_number)
    return result


@router.get("/detections", response_model=List[DetectionSchema])
def list_detections(
    plate: Optional[str] = None,
    camera_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Search and filter live CCTV vehicle detections."""
    query = db.query(Detection)
    if plate:
        clean_plate = "".join(c for c in plate.upper() if c.isalnum())
        query = query.filter(Detection.plate_number.ilike(f"%{clean_plate}%"))
    if camera_id:
        query = query.filter(Detection.camera_id == camera_id)

    return query.order_by(Detection.capture_timestamp.desc()).limit(limit).all()


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
    detection = Detection(
        camera_id=data.camera_id,
        plate_number=clean_plate,
        plate_raw=data.plate_raw or data.plate_number,
        confidence=data.confidence,
        vehicle_type=data.vehicle_type,
        pts_timestamp_ms=data.pts_timestamp_ms,
        capture_timestamp=datetime.datetime.utcnow(),
        snapshot_path=data.snapshot_path
    )
    db.add(detection)
    db.commit()
    db.refresh(detection)

    # Cross-reference with watchlist and fire real-time alert if matched
    check_and_generate_alert(db, detection, camera)

    return detection
