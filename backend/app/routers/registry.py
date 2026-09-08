from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
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
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Query the centralized CCTV registry (Model 1).
    Supports filtering by government department, district, connectivity status,
    and a free-text search across camera name, ID and location description.
    """
    query = db.query(Camera)
    if department:
        query = query.filter(Camera.department.ilike(f"%{department}%"))
    if status:
        query = query.filter(Camera.connectivity_status.ilike(status))
    if district:
        query = query.filter(Camera.district.ilike(district))
    if search:
        term = f"%{search}%"
        query = query.filter(
            Camera.name.ilike(term)
            | Camera.camera_id.ilike(term)
            | Camera.location_description.ilike(term)
        )
    return query.order_by(Camera.camera_id).all()


@router.get("/cameras/facets")
def camera_facets(db: Session = Depends(get_db)):
    """
    Distinct departments, districts and statuses with counts.
    Lets the dashboard build its filter controls from the live registry instead
    of hardcoding a department list that drifts out of date.
    """
    def _facet(column):
        rows = db.query(column, func.count()).group_by(column).order_by(column).all()
        return [{"value": value, "count": count} for value, count in rows if value]

    return {
        "departments": _facet(Camera.department),
        "districts": _facet(Camera.district),
        "statuses": _facet(Camera.connectivity_status),
        "camera_types": _facet(Camera.camera_type),
        "total": db.query(Camera).count(),
    }


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
                # RTSP/WHEP URLs are deliberately omitted: this feed is for map
                # rendering, and stream credentials do not belong in a payload
                # that gets handed to third-party GIS tooling.
                "location_description": cam.location_description
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }


@router.post("/sync-catalogue")
def trigger_sync(
    host: Optional[str] = Query(
        None,
        description="Gateway hostname (not a full URL). Defaults to GOVT_GATEWAY_HOST.",
    ),
    db: Session = Depends(get_db)
):
    """
    Sync the camera catalogue from the configured government evaluation gateway:
    `curl -s http://<host>/api/ingest`

    The full ingest URL is intentionally NOT accepted from the caller. Accepting
    an arbitrary URL here turned this endpoint into an unauthenticated SSRF: the
    server would fetch any address the caller named and write the response
    straight into the camera registry. The host is validated as a bare hostname
    and the URL is assembled server-side.
    """
    kwargs = {}
    if host:
        if "/" in host or ":" in host or host.startswith("http"):
            raise HTTPException(
                status_code=400,
                detail="host must be a bare hostname or IP, e.g. '10.0.0.5' - not a URL",
            )
        kwargs["host"] = host
    return sync_catalogue_with_db(db, **kwargs)
