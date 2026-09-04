from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from backend.app.database import get_db
from backend.app.models import Alert, AlertSchema, Camera, Watchlist, Detection

router = APIRouter(prefix="/api/alerts", tags=["Real-time Watchlist Alerts"])

@router.get("", response_model=List[AlertSchema])
def list_alerts(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Fetch live alerts with complete camera and suspect context."""
    query = db.query(Alert, Camera, Watchlist, Detection)\
        .join(Camera, Alert.camera_id == Camera.camera_id)\
        .outerjoin(Watchlist, Alert.watchlist_id == Watchlist.watchlist_id)\
        .outerjoin(Detection, Alert.detection_id == Detection.detection_id)

    if status:
        query = query.filter(Alert.status == status)

    results = query.order_by(Alert.created_at.desc()).limit(limit).all()

    formatted_alerts = []
    for alert, cam, watch, det in results:
        formatted_alerts.append(AlertSchema(
            alert_id=alert.alert_id,
            detection_id=alert.detection_id,
            watchlist_id=alert.watchlist_id,
            camera_id=alert.camera_id,
            plate_number=alert.plate_number,
            severity=alert.severity,
            alert_message=alert.alert_message,
            status=alert.status,
            created_at=alert.created_at,
            camera_name=cam.name if cam else None,
            department=cam.department if cam else None,
            latitude=cam.latitude if cam else None,
            longitude=cam.longitude if cam else None,
            snapshot_path=det.snapshot_path if det else None,
            vehicle_make_model=watch.vehicle_make_model if watch else None,
            crime_category=watch.crime_category if watch else None
        ))

    return formatted_alerts


@router.post("/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """Mark an alert as acknowledged by the command center officer."""
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "ACKNOWLEDGED"
    db.commit()
    return {"status": "success", "alert_id": alert_id, "new_status": "ACKNOWLEDGED"}
