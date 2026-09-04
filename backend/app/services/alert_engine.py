import logging
import asyncio
from typing import Dict, Any, Optional, Set, List
from sqlalchemy.orm import Session
from backend.app.models import Watchlist, Alert, Detection, Camera
from fastapi import WebSocket

logger = logging.getLogger("cctv.alert_engine")

# Global WebSocket connection manager for live alert broadcasting
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Dashboard WebSocket connected. Active clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Dashboard WebSocket disconnected. Active clients: {len(self.active_connections)}")

    async def broadcast_alert(self, alert_data: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json({"type": "WATCHLIST_ALERT", "data": alert_data})
            except Exception as e:
                logger.error(f"Error sending WebSocket alert: {e}")
                self.disconnect(connection)

    async def broadcast_detection(self, detection_data: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json({"type": "LIVE_DETECTION", "data": detection_data})
            except Exception as e:
                self.disconnect(connection)

ws_manager = ConnectionManager()


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute string edit distance for fuzzy license plate matching."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def check_and_generate_alert(
    db: Session,
    detection: Detection,
    camera: Camera,
    loop: Optional[asyncio.AbstractEventLoop] = None
) -> Optional[Alert]:
    """
    Continuous cross-referencing of incoming CCTV detection against watchlist.
    Performs O(1) exact match and Levenshtein fuzzy match (dist <= 1).
    """
    detected_plate = detection.plate_number.strip().upper()
    active_watchlist = db.query(Watchlist).filter(Watchlist.active == True).all()

    matched_item = None
    match_type = "EXACT"

    for item in active_watchlist:
        target = item.plate_number.strip().upper()
        if detected_plate == target:
            matched_item = item
            match_type = "EXACT"
            break
        elif len(detected_plate) >= 8 and len(target) >= 8:
            # Fuzzy match for dirty/partially occluded plates (e.g., '0' vs 'D', '8' vs 'B')
            if levenshtein_distance(detected_plate, target) == 1:
                matched_item = item
                match_type = "FUZZY_CONFIRMED"
                break

    if not matched_item:
        return None

    # Construct alert message
    alert_msg = (
        f"[{match_type} MATCH] Suspect vehicle {matched_item.plate_number} detected at "
        f"{camera.name} ({camera.department}). Crime: {matched_item.crime_category}. "
        f"FIR: {matched_item.fir_number or 'N/A'}"
    )

    alert = Alert(
        detection_id=detection.detection_id,
        watchlist_id=matched_item.watchlist_id,
        camera_id=camera.camera_id,
        plate_number=detected_plate,
        severity=matched_item.severity,
        alert_message=alert_msg,
        status="NEW"
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    # Format broadcast payload
    alert_payload = {
        "alert_id": alert.alert_id,
        "detection_id": detection.detection_id,
        "plate_number": alert.plate_number,
        "matched_watchlist_plate": matched_item.plate_number,
        "match_type": match_type,
        "severity": alert.severity,
        "alert_message": alert.alert_message,
        "crime_category": matched_item.crime_category,
        "vehicle_make_model": matched_item.vehicle_make_model,
        "vehicle_owner": matched_item.vehicle_owner,
        "fir_number": matched_item.fir_number,
        "police_station": matched_item.police_station,
        "camera_id": camera.camera_id,
        "camera_name": camera.name,
        "department": camera.department,
        "latitude": camera.latitude,
        "longitude": camera.longitude,
        "snapshot_path": detection.snapshot_path,
        "timestamp": alert.created_at.isoformat()
    }

    # Asynchronously dispatch to connected dashboard WebSockets
    try:
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast_alert(alert_payload), loop)
        else:
            try:
                running_loop = asyncio.get_running_loop()
                running_loop.create_task(ws_manager.broadcast_alert(alert_payload))
            except RuntimeError:
                pass
    except Exception as e:
        logger.error(f"Failed to push alert through WebSocket: {e}")

    return alert
