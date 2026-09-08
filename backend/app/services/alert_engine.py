import asyncio
import datetime
import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import WebSocket
from sqlalchemy.orm import Session

from backend.app.config import ALERT_COOLDOWN_SECONDS, FUZZY_MATCH_MIN_LENGTH
from backend.app.models import Alert, Camera, Detection, Watchlist, utc_iso, utcnow

logger = logging.getLogger("cctv.alert_engine")


# ==================== Event loop bridge ====================
# Detections are produced from three places, none of which run on the server's
# event loop: the sync `POST /api/detections` handler (FastAPI runs sync
# endpoints in a threadpool), the StreamWorker threads, and the offline
# simulation script. Broadcasting therefore has to be handed *back* to the loop
# explicitly. The loop is registered once at startup by the FastAPI lifespan.
_server_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()


def register_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once from the FastAPI lifespan so worker threads can reach the loop."""
    global _server_loop
    with _loop_lock:
        _server_loop = loop
    logger.info("Registered server event loop for cross-thread alert broadcasting.")


def _dispatch(coro) -> bool:
    """
    Schedule a coroutine on the server loop from any thread.
    Returns True if it was actually scheduled.
    """
    loop = _server_loop
    if loop is not None and not loop.is_closed():
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
            return True
        except RuntimeError as e:
            logger.warning(f"Could not schedule broadcast on server loop: {e}")

    # Fallback: we may already be running on a loop (e.g. an async caller).
    try:
        asyncio.get_running_loop().create_task(coro)
        return True
    except RuntimeError:
        pass

    coro.close()
    logger.warning("No event loop available - broadcast dropped.")
    return False


# ==================== WebSocket fan-out ====================
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

    async def _send_to_all(self, message: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Dropping dead WebSocket client: {e}")
                self.disconnect(connection)

    async def broadcast_alert(self, alert_data: Dict[str, Any]):
        await self._send_to_all({"type": "WATCHLIST_ALERT", "data": alert_data})

    async def broadcast_detection(self, detection_data: Dict[str, Any]):
        await self._send_to_all({"type": "LIVE_DETECTION", "data": detection_data})

    async def broadcast_worker_status(self, status: Dict[str, Any]):
        await self._send_to_all({"type": "WORKER_STATUS", "data": status})


ws_manager = ConnectionManager()


def push_detection(detection: Detection, camera: Camera) -> None:
    """Publish a plain (non-watchlist) sighting to the live dashboard ticker."""
    _dispatch(ws_manager.broadcast_detection({
        "detection_id": detection.detection_id,
        "plate_number": detection.plate_number,
        "plate_raw": detection.plate_raw,
        "confidence": detection.confidence,
        "vehicle_type": detection.vehicle_type,
        "camera_id": camera.camera_id,
        "camera_name": camera.name,
        "department": camera.department,
        "latitude": camera.latitude,
        "longitude": camera.longitude,
        "snapshot_path": detection.snapshot_path,
        "timestamp": utc_iso(detection.capture_timestamp),
    }))


def push_worker_status(status: Dict[str, Any]) -> None:
    """Publish AI worker pool changes so the viewer tiles can reflect them."""
    _dispatch(ws_manager.broadcast_worker_status(status))


# ==================== Plate matching ====================
def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute string edit distance for fuzzy license plate matching."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _find_watchlist_match(db: Session, detected_plate: str):
    """
    Exact match across the whole active watchlist first; only if nothing matches
    exactly do we fall back to a single-character fuzzy pass. Exact-first stops a
    fuzzy hit on an early row from shadowing a real exact match further down.
    """
    active_watchlist = db.query(Watchlist).filter(Watchlist.active == True).all()

    for item in active_watchlist:
        if detected_plate == item.plate_number.strip().upper():
            return item, "EXACT"

    if len(detected_plate) >= FUZZY_MATCH_MIN_LENGTH:
        for item in active_watchlist:
            target = item.plate_number.strip().upper()
            # Fuzzy pass for dirty/partially occluded plates ('0' vs 'D', '8' vs 'B').
            if len(target) >= FUZZY_MATCH_MIN_LENGTH and levenshtein_distance(detected_plate, target) == 1:
                return item, "FUZZY_UNCONFIRMED"

    return None, None


def _recent_duplicate_alert(db: Session, plate: str, camera_id: str) -> Optional[Alert]:
    """
    A vehicle dwells in frame for several sampled frames and each one produces its
    own detection. Without this window a single pass generates a burst of
    identical CRITICAL alerts and buries the operator.
    """
    if ALERT_COOLDOWN_SECONDS <= 0:
        return None
    cutoff = utcnow() - datetime.timedelta(seconds=ALERT_COOLDOWN_SECONDS)
    return (
        db.query(Alert)
        .filter(
            Alert.plate_number == plate,
            Alert.camera_id == camera_id,
            Alert.created_at >= cutoff,
        )
        .order_by(Alert.created_at.desc())
        .first()
    )


def check_and_generate_alert(
    db: Session,
    detection: Detection,
    camera: Camera,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> Optional[Alert]:
    """
    Cross-reference an incoming CCTV detection against the active watchlist and,
    on a hit, persist an Alert and push it to every connected dashboard.
    """
    detected_plate = detection.plate_number.strip().upper()
    matched_item, match_type = _find_watchlist_match(db, detected_plate)

    if not matched_item:
        return None

    duplicate = _recent_duplicate_alert(db, detected_plate, camera.camera_id)
    if duplicate:
        duplicate.sighting_count = (duplicate.sighting_count or 1) + 1
        duplicate.last_seen_at = detection.capture_timestamp
        db.commit()
        logger.debug(
            f"Suppressed duplicate alert for {detected_plate} at {camera.camera_id} "
            f"(within {ALERT_COOLDOWN_SECONDS}s cooldown)."
        )
        return None

    is_fuzzy = match_type != "EXACT"
    # Never present a fuzzy hit as though the camera read the watchlist plate --
    # the officer has to see what was actually on the vehicle.
    if is_fuzzy:
        alert_msg = (
            f"[POSSIBLE MATCH - UNCONFIRMED] Camera read '{detected_plate}', which differs by one "
            f"character from watchlist plate '{matched_item.plate_number}'. "
            f"Crime: {matched_item.crime_category}. FIR: {matched_item.fir_number or 'N/A'}. "
            f"Location: {camera.name} ({camera.department}). Visual confirmation required."
        )
    else:
        alert_msg = (
            f"[CONFIRMED MATCH] Suspect vehicle {detected_plate} detected at "
            f"{camera.name} ({camera.department}). Crime: {matched_item.crime_category}. "
            f"FIR: {matched_item.fir_number or 'N/A'}"
        )

    alert = Alert(
        detection_id=detection.detection_id,
        watchlist_id=matched_item.watchlist_id,
        camera_id=camera.camera_id,
        plate_number=detected_plate,
        matched_plate=matched_item.plate_number,
        match_type=match_type,
        # A one-character-off read is a lead, not a confirmed sighting.
        severity=matched_item.severity if not is_fuzzy else "REVIEW",
        alert_message=alert_msg,
        status="NEW",
        sighting_count=1,
        last_seen_at=detection.capture_timestamp,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    alert_payload = {
        "alert_id": alert.alert_id,
        "detection_id": detection.detection_id,
        "plate_number": alert.plate_number,
        "matched_watchlist_plate": matched_item.plate_number,
        "match_type": match_type,
        "is_confirmed": not is_fuzzy,
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
        "confidence": detection.confidence,
        "timestamp": utc_iso(alert.created_at),
    }

    if loop is not None:
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast_alert(alert_payload), loop)
    else:
        _dispatch(ws_manager.broadcast_alert(alert_payload))

    logger.info(f"ALERT [{match_type}] {detected_plate} at {camera.camera_id}")
    return alert
