from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from backend.app.database import get_db
from backend.app.models import Camera, CameraSchema
from backend.app.services.catalogue import sync_catalogue_with_db

router = APIRouter(prefix="/api", tags=["Model 1 CCTV Registry"])

@router.get("/cameras", response_model=List[CameraSchema])
def list_cameras(
    department: Optional[str] = None,
    status: Optional[str] = None,
    district: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Query the centralized CCTV registry (Model 1).
    Supports filtering by government department, district, and connectivity status.
    """
    query = db.query(Camera)
    if department:
        query = query.filter(Camera.department.ilike(f"%{department}%"))
    if status:
        query = query.filter(Camera.connectivity_status.ilike(status))
    if district:
        query = query.filter(Camera.district.ilike(district))
    return query.all()


@router.get("/cameras/{camera_id}", response_model=CameraSchema)
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    """Fetch individual camera record with streaming parameters."""
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera with ID '{camera_id}' not found in registry")
    return camera


@router.get("/cameras-geojson")
def get_cameras_geojson(db: Session = Depends(get_db)):
    """
    Format all camera registry points as standard GeoJSON FeatureCollection
    for seamless integration with Leaflet, Mapbox, or QGIS.
    """
    cameras = db.query(Camera).all()
    features = []
    for cam in cameras:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [cam.longitude, cam.latitude]
            },
            "properties": {
                "camera_id": cam.camera_id,
                "name": cam.name,
                "department": cam.department,
                "district": cam.district,
                "camera_type": cam.camera_type,
                "codec": cam.codec,
                "status": cam.connectivity_status,
                "rtsp_url": cam.rtsp_url,
                "whep_url": cam.whep_url,
                "hls_url": cam.hls_url,
                "location_description": cam.location_description
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }


@router.post("/sync-catalogue")
def trigger_sync(
    host: Optional[str] = None,
    ingest_url: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Sync camera catalogue directly from the government evaluation gateway:
    `curl -s http://<host>/api/ingest`
    """
    kwargs = {}
    if host:
        kwargs["host"] = host
    if ingest_url:
        kwargs["ingest_url"] = ingest_url
    return sync_catalogue_with_db(db, **kwargs)
