from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from backend.app.config import MAX_PAGE_SIZE
from backend.app.database import get_db
from backend.app.models import Alert, AlertSchema, Camera, Watchlist, Detection
from backend.app.timewindow import TimeWindow, apply_window, resolve_window

router = APIRouter(prefix="/api/alerts", tags=["Real-time Watchlist Alerts"])


@router.get("", response_model=List[AlertSchema])
def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    plate: Optional[str] = None,
    camera_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    window: TimeWindow = Depends(resolve_window),
    db: Session = Depends(get_db)
):
    """Fetch alerts with complete camera and suspect context, scoped to a window."""
    # Camera is outer-joined: an alert must remain visible even if the camera is
    # later removed from the registry. It is evidence, not a live status row.
    query = db.query(Alert, Camera, Watchlist, Detection)\
        .outerjoin(Camera, Alert.camera_id == Camera.camera_id)\
        .outerjoin(Watchlist, Alert.watchlist_id == Watchlist.watchlist_id)\
        .outerjoin(Detection, Alert.detection_id == Detection.detection_id)

    if status:
        query = query.filter(Alert.status == status.upper())
    if severity:
        query = query.filter(Alert.severity == severity.upper())
    if plate:
        clean_plate = "".join(c for c in plate.upper() if c.isalnum())
        if clean_plate:
            query = query.filter(Alert.plate_number.ilike(f"%{clean_plate}%"))
    if camera_id:
        query = query.filter(Alert.camera_id == camera_id)

    query = apply_window(query, Alert.created_at, window)
    results = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit).all()

    formatted_alerts = []
    for alert, cam, watch, det in results:
        formatted_alerts.append(AlertSchema(
            alert_id=alert.alert_id,
            detection_id=alert.detection_id,
            watchlist_id=alert.watchlist_id,
            camera_id=alert.camera_id,
            plate_number=alert.plate_number,
            matched_plate=alert.matched_plate,
            match_type=alert.match_type,
            severity=alert.severity,
            alert_message=alert.alert_message,
            status=alert.status,
            sighting_count=alert.sighting_count,
            created_at=alert.created_at,
            camera_name=cam.name if cam else None,
            department=cam.department if cam else None,
            latitude=cam.latitude if cam else None,
            longitude=cam.longitude if cam else None,
            snapshot_path=det.snapshot_path if det else None,
            vehicle_make_model=watch.vehicle_make_model if watch else None,
            crime_category=watch.crime_category if watch else None,
            fir_number=watch.fir_number if watch else None,
            police_station=watch.police_station if watch else None
        ))

    return formatted_alerts


@router.get("/stats")
def alert_stats(db: Session = Depends(get_db)):
    """Counts for the dashboard header, so the badge survives a page reload."""
    return {
        "new": db.query(Alert).filter(Alert.status == "NEW").count(),
        "acknowledged": db.query(Alert).filter(Alert.status == "ACKNOWLEDGED").count(),
        "resolved": db.query(Alert).filter(Alert.status == "RESOLVED").count(),
        "total": db.query(Alert).count(),
    }


@router.post("/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """Mark an alert as acknowledged by the command center officer."""
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "ACKNOWLEDGED"
    db.commit()
    return {"status": "success", "alert_id": alert_id, "new_status": "ACKNOWLEDGED"}


@router.post("/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    """Close out an alert once the vehicle has been intercepted or cleared."""
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "RESOLVED"
    db.commit()
    return {"status": "success", "alert_id": alert_id, "new_status": "RESOLVED"}
