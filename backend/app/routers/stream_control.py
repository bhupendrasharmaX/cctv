from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models import Camera
from ai_engine.multi_stream_runner import stream_pool

router = APIRouter(prefix="/api/stream-control", tags=["AI Stream Orchestration"])

@router.post("/start/{camera_id}")
def start_ai_processing(camera_id: str, db: Session = Depends(get_db)):
    """Launch background AI analytics worker for a specific camera stream."""
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found in registry")

    success = stream_pool.start_worker(camera_id, camera.rtsp_url)
    if not success:
        raise HTTPException(status_code=429, detail="Maximum concurrent camera workers reached")

    return {"status": "success", "message": f"AI worker started for camera '{camera_id}'"}


@router.post("/stop/{camera_id}")
def stop_ai_processing(camera_id: str):
    """Halt background AI analytics worker for a specific camera stream."""
    stopped = stream_pool.stop_worker(camera_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Worker was not running for this camera")
    return {"status": "success", "message": f"AI worker stopped for camera '{camera_id}'"}


@router.get("/status")
def get_stream_pool_status():
    """Get runtime status of all active camera AI workers."""
    return stream_pool.get_status()
